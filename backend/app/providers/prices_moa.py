from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

from ..config import DATA_DIR, PRESET_MARKET_CODES, SNAPSHOT_DIR

MOA_URL = "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx"

F_DATE = "交易日期"
F_CATEGORY_CODE = "種類代碼"
F_CROP_CODE = "作物代號"
F_CROP = "作物名稱"
F_MARKET_CODE = "市場代號"
F_MARKET_NAME = "市場名稱"
F_UPPER = "上價"
F_MIDDLE = "中價"
F_LOWER = "下價"
F_AVG = "平均價"
F_VOLUME = "交易量"

MARKET_OVERRIDES = {
    "423": "東勢區",
    "400": "臺中市",
    "420": "豐原區",
}


def _norm_name(value: str | None) -> str:
    return (value or "").replace("台", "臺").strip()


def parse_roc_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    match = re.match(r"^(\d{2,3})[./-](\d{1,2})[./-](\d{1,2})$", str(value).strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return dt.date(year + 1911, month, day)
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def fetch_raw(timeout: int = 60) -> list[dict[str, Any]]:
    response = requests.get(MOA_URL, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    data = response.json()
    if isinstance(data, dict):
        data = data.get("Data") or data.get("data") or []
    if not isinstance(data, list):
        raise ValueError("unexpected MOA response")
    return [row for row in data if isinstance(row, dict)]


def normalize_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in raw_rows:
        crop_name = str(row.get(F_CROP) or "").strip()
        market_code = str(row.get(F_MARKET_CODE) or "").strip()
        market_name = _norm_name(row.get(F_MARKET_NAME))
        trade_date = parse_roc_date(row.get(F_DATE))
        avg = to_float(row.get(F_AVG))
        volume = to_float(row.get(F_VOLUME)) or 0.0
        if not crop_name or crop_name in {"休市", "休市日"}:
            continue
        if not market_code or trade_date is None or avg is None or avg <= 0:
            continue
        records.append(
            {
                "date": trade_date.isoformat(),
                "category_code": str(row.get(F_CATEGORY_CODE) or "").strip(),
                "crop_code": str(row.get(F_CROP_CODE) or "").strip(),
                "crop_name": crop_name,
                "market_code": market_code,
                "market_name": market_name,
                "market_display": MARKET_OVERRIDES.get(market_code, market_name),
                "upper": to_float(row.get(F_UPPER)),
                "middle": to_float(row.get(F_MIDDLE)),
                "lower": to_float(row.get(F_LOWER)),
                "avg": avg,
                "volume": volume,
                "imported": "進口" in crop_name,
            }
        )
    return records


def aggregate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (record["date"], record["crop_name"], record["market_code"])
        group = groups.get(key)
        if group is None:
            group = {
                "date": record["date"],
                "crop_name": record["crop_name"],
                "market_code": record["market_code"],
                "market_name": record["market_name"],
                "market_display": record["market_display"],
                "upper": record["upper"],
                "middle": record["middle"],
                "lower": record["lower"],
                "volume": 0.0,
                "weighted": 0.0,
                "avg_sum": 0.0,
                "rows": 0,
                "imported": record["imported"],
            }
            groups[key] = group
        group["volume"] += record["volume"]
        group["weighted"] += record["avg"] * record["volume"]
        group["avg_sum"] += record["avg"]
        group["rows"] += 1

    aggregated: list[dict[str, Any]] = []
    for group in groups.values():
        if group["volume"] > 0:
            avg = group["weighted"] / group["volume"]
        else:
            avg = group["avg_sum"] / max(group["rows"], 1)
        aggregated.append(
            {
                "date": group["date"],
                "crop_name": group["crop_name"],
                "market_code": group["market_code"],
                "market_name": group["market_name"],
                "market_display": group["market_display"],
                "upper": group["upper"],
                "middle": group["middle"],
                "lower": group["lower"],
                "avg": round(avg, 2),
                "avg_raw": avg,
                "volume": round(group["volume"], 2),
                "rows": group["rows"],
                "imported": group["imported"],
            }
        )
    aggregated.sort(key=lambda item: (item["crop_name"], item["market_code"]))
    return aggregated


def build_markets(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for record in records:
        code = record["market_code"]
        entry = by_code.setdefault(
            code,
            {"code": code, "names": defaultdict(int), "crops": set(), "rows": 0},
        )
        entry["names"][record["market_name"]] += 1
        entry["crops"].add(record["crop_name"])
        entry["rows"] += 1

    markets: list[dict[str, Any]] = []
    for code, entry in by_code.items():
        display = MARKET_OVERRIDES.get(code) or max(entry["names"], key=entry["names"].get)
        markets.append(
            {
                "code": code,
                "name": display,
                "api_names": sorted(entry["names"].keys()),
                "crop_count": len(entry["crops"]),
                "row_count": entry["rows"],
                "preset": code in PRESET_MARKET_CODES,
            }
        )
    markets.sort(key=lambda item: (not item["preset"], item["name"]))
    return markets


def load_crop_map() -> dict[str, str]:
    path = DATA_DIR / "crops.json"
    if not path.exists():
        return {}
    crops = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for crop in crops:
        for api_name in crop.get("api_names", []):
            mapping[api_name] = crop["id"]
    return mapping


def build_snapshot() -> dict[str, Any]:
    raw_rows = fetch_raw()
    records = normalize_rows(raw_rows)
    aggregated = aggregate_records(records)
    crop_map = load_crop_map()
    for item in aggregated:
        item["crop_id"] = crop_map.get(item["crop_name"])
    trade_dates = sorted({record["date"] for record in records})
    trade_date = trade_dates[-1] if trade_dates else dt.date.today().isoformat()
    markets = build_markets(records)
    return {
        "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "record_count": len(records),
        "records": records,
        "aggregated": aggregated,
        "markets": markets,
    }


def save_snapshot(snapshot: dict[str, Any]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    dated = SNAPSHOT_DIR / f"prices_{snapshot['trade_date']}.json"
    latest = SNAPSHOT_DIR / "prices_latest.json"
    dated.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    return dated


def load_latest_snapshot() -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / "prices_latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_previous_snapshot(before_date: str) -> dict[str, Any] | None:
    candidates: list[tuple[str, Path]] = []
    for path in SNAPSHOT_DIR.glob("prices_*.json"):
        if path.name == "prices_latest.json":
            continue
        match = re.search(r"prices_(\d{4}-\d{2}-\d{2})\.json$", path.name)
        if not match:
            continue
        date_value = match.group(1)
        if date_value < before_date:
            candidates.append((date_value, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return json.loads(candidates[-1][1].read_text(encoding="utf-8"))


def _previous_price_map(before_date: str) -> dict[tuple[str, str], float]:
    previous = load_previous_snapshot(before_date)
    if previous is None:
        return {}
    crop_map = load_crop_map()
    result: dict[tuple[str, str], float] = {}
    for item in previous.get("aggregated", []):
        crop_id = item.get("crop_id") or crop_map.get(item["crop_name"])
        if not crop_id:
            continue
        result[(crop_id, item["market_code"])] = item["avg"]
    return result


def get_prices_for(
    crop_ids: list[str] | None,
    market_codes: list[str] | None,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if snapshot is None:
        snapshot = load_latest_snapshot()
    if snapshot is None:
        snapshot = build_snapshot()
        save_snapshot(snapshot)

    crop_filter = set(crop_ids or [])
    market_filter = set(market_codes or [])
    trade_date = snapshot["trade_date"]
    crop_map = load_crop_map()

    history: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for item in snapshot.get("aggregated", []):
        crop_id = item.get("crop_id")
        if crop_id:
            history[(crop_id, item["market_code"])][item["date"]] = item.get("avg_raw", item["avg"])

    results: list[dict[str, Any]] = []
    for item in snapshot.get("aggregated", []):
        if item["date"] != trade_date:
            continue
        crop_id = item.get("crop_id")
        if crop_filter and crop_id not in crop_filter:
            continue
        if market_filter and item["market_code"] not in market_filter:
            continue
        dates = history.get((crop_id, item["market_code"]), {}) if crop_id else {}
        prior_dates = [date for date in dates if date < trade_date]
        prev_avg_raw = dates[max(prior_dates)] if prior_dates else None
        avg_raw = item.get("avg_raw", item["avg"])
        change_raw = avg_raw - prev_avg_raw if prev_avg_raw is not None else None
        prev_avg = round(prev_avg_raw, 2) if prev_avg_raw is not None else None
        change = round(change_raw, 2) if change_raw is not None else None

        raw_rows: list[dict[str, Any]] = []
        for raw in snapshot.get("records", []):
            if raw.get("date") != trade_date or raw.get("market_code") != item["market_code"]:
                continue
            raw_crop_id = crop_map.get(raw.get("crop_name"))
            if crop_id:
                if raw_crop_id != crop_id:
                    continue
            elif raw.get("crop_name") != item["crop_name"]:
                continue
            raw_rows.append(
                {
                    "crop_name": raw.get("crop_name"),
                    "crop_code": raw.get("crop_code"),
                    "market_code": raw.get("market_code"),
                    "market_name": raw.get("market_name"),
                    "market_display": raw.get("market_display"),
                    "upper": raw.get("upper"),
                    "middle": raw.get("middle"),
                    "lower": raw.get("lower"),
                    "avg": raw.get("avg"),
                    "volume": raw.get("volume"),
                    "date": raw.get("date"),
                    "imported": raw.get("imported", False),
                }
            )
        raw_rows.sort(key=lambda row: (row.get("crop_code") or "", row.get("crop_name") or ""))

        results.append(
            {
                "crop_id": crop_id,
                "crop_name": item["crop_name"],
                "market_code": item["market_code"],
                "market_name": item["market_name"],
                "market_display": item["market_display"],
                "avg": item["avg"],
                "avg_raw": avg_raw,
                "upper": item["upper"],
                "middle": item["middle"],
                "lower": item["lower"],
                "volume": item["volume"],
                "date": item["date"],
                "imported": item.get("imported", False),
                "prev_avg": prev_avg,
                "prev_avg_raw": prev_avg_raw,
                "change": change,
                "change_raw": change_raw,
                "raw_row_count": len(raw_rows),
                "raw_rows": raw_rows,
            }
        )

    order = {crop_id: index for index, crop_id in enumerate(crop_ids or [])}
    results.sort(key=lambda item: (order.get(item["crop_id"] or "", 999), item["market_code"]))
    return results
