from __future__ import annotations

import calendar
import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import requests

from ..config import (
    CWA_API_KEY,
    CWA_BASE,
    CLIMATE_NORMALS_DATASET,
    CLIMATE_STATION_ID,
    CLIMATE_STATION_NAME,
    CODIS_STATION_URL,
    SNAPSHOT_DIR,
)

TAIPEI = ZoneInfo("Asia/Taipei")
BASELINES_FILE = SNAPSHOT_DIR / "climate_baselines.json"
BASELINE_WINDOWS = (
    ("last30", 30, "近30年"),
    ("last10", 10, "近10年"),
    ("last5", 5, "近5年"),
    ("last_year", 1, "去年"),
)


class ClimateError(RuntimeError):
    pass


def _ci_get(mapping: Any, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    if key in mapping:
        return mapping[key]
    lowered = key.lower()
    for candidate, value in mapping.items():
        if isinstance(candidate, str) and candidate.lower() == lowered:
            return value
    return default


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])


def _codis_rows(start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    payload = {
        "date": start.strftime("%Y-%m"),
        "type": "report_month",
        "stn_ID": CLIMATE_STATION_ID,
        "stn_type": "cwb",
        "more": "0",
        "start": f"{start.isoformat()}T00:00:00",
        "end": f"{end.isoformat()}T23:59:59",
    }
    response = requests.post(CODIS_STATION_URL, data=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 200:
        raise ClimateError(str(result.get("message") or "CODiS request failed"))
    rows: list[dict[str, Any]] = []
    for block in result.get("data") or []:
        rows.extend(block.get("dts") or [])
    return rows


def _summarize_rows(rows: list[dict[str, Any]], start: dt.date, end: dt.date) -> dict[str, Any] | None:
    temperatures: list[float] = []
    precipitation: list[float] = []
    dates: list[dt.date] = []
    for row in rows:
        date_text = str(row.get("DataDate") or "")[:10]
        try:
            current = dt.date.fromisoformat(date_text)
        except ValueError:
            continue
        if current < start or current > end:
            continue
        dates.append(current)
        temperature = _to_float(_ci_get(_ci_get(row, "AirTemperature") or {}, "Mean"))
        rainfall = _to_float(_ci_get(_ci_get(row, "Precipitation") or {}, "Accumulation"))
        if temperature is not None and temperature >= -50:
            temperatures.append(temperature)
        if rainfall is not None and rainfall >= 0:
            precipitation.append(rainfall)
    if not dates:
        return None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": len(dates),
        "as_of": max(dates).isoformat(),
        "mean_t": round(sum(temperatures) / len(temperatures), 1) if temperatures else None,
        "rainfall": round(sum(precipitation), 1) if precipitation else 0.0,
    }


def _yearly_series(year: int, last_month: int = 12) -> list[dict[str, Any] | None]:
    start = dt.date(year, 1, 1)
    end = dt.date(year, last_month, calendar.monthrange(year, last_month)[1])
    rows = _codis_rows(start, end)
    series: list[dict[str, Any] | None] = []
    for month in range(1, 13):
        if month > last_month:
            series.append(None)
            continue
        month_start, month_end = _month_bounds(year, month)
        series.append(_summarize_rows(rows, month_start, month_end))
    return series


def get_normals(month: int) -> dict[str, Any]:
    if not CWA_API_KEY:
        raise ClimateError("CWA_API_KEY is not configured")
    response = requests.get(
        f"{CWA_BASE}/{CLIMATE_NORMALS_DATASET}",
        params={"Authorization": CWA_API_KEY, "format": "JSON"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    records = payload.get("records") or {}
    data = records.get("data") or {}
    surface_obs = _ci_get(data, "surfaceObs") or {}
    locations = _ci_get(surface_obs, "location") or []
    if isinstance(locations, dict):
        locations = [locations]
    for location in locations:
        station = _ci_get(location, "station") or {}
        if str(_ci_get(station, "StationID", "")) != CLIMATE_STATION_ID:
            continue
        statistics = _ci_get(location, "stationObsStatistics") or {}
        temperature_block = _ci_get(statistics, "AirTemperature") or {}
        rainfall_block = _ci_get(statistics, "Precipitation") or {}
        temperature_rows = _ci_get(temperature_block, "monthly") or []
        rainfall_rows = _ci_get(rainfall_block, "monthly") or []
        if isinstance(temperature_rows, dict):
            temperature_rows = [temperature_rows]
        if isinstance(rainfall_rows, dict):
            rainfall_rows = [rainfall_rows]
        temperature_row = next((row for row in temperature_rows if str(_ci_get(row, "Month")) == str(month)), {})
        rainfall_row = next((row for row in rainfall_rows if str(_ci_get(row, "Month")) == str(month)), {})
        return {
            "station_name": _ci_get(station, "StationName", CLIMATE_STATION_NAME),
            "period_start": _ci_get(temperature_block, "StationStartYear"),
            "period_end": _ci_get(temperature_block, "StationEndYear"),
            "month": month,
            "mean_t": _to_float(_ci_get(temperature_row, "Mean")),
            "rainfall": _to_float(_ci_get(rainfall_row, "Accumulation")),
        }
    raise ClimateError(f"station {CLIMATE_STATION_ID} not found in climate normals")


def _delta(current: dict[str, Any] | None, baseline: dict[str, Any] | None, key: str, value_key: str | None = None) -> float | None:
    if not current or not baseline:
        return None
    current_value = _to_float(current.get(key))
    baseline_value = _to_float(baseline.get(value_key or key))
    if current_value is None or baseline_value is None:
        return None
    return round(current_value - baseline_value, 1)


def build_climate_snapshot() -> dict[str, Any]:
    errors: list[str] = []

    def safe(function: Any, default: Any) -> Any:
        try:
            return function()
        except Exception as exc:
            errors.append(f"{getattr(function, '__name__', 'task')}: {exc}")
            return default

    today = dt.datetime.now(TAIPEI).date()
    previous_year, previous_month = _shift_month(today.year, today.month, -1)
    last_year = today.year - 1
    previous_start, previous_end = _month_bounds(previous_year, previous_month)
    last_start, last_end = _month_bounds(last_year, previous_month)
    mtd_start = dt.date(today.year, today.month, 1)
    mtd_end = today - dt.timedelta(days=1)
    last_mtd_start = dt.date(last_year, today.month, 1)
    last_mtd_day = min(mtd_end.day, calendar.monthrange(last_year, today.month)[1]) if mtd_end >= mtd_start else 0
    last_mtd_end = dt.date(last_year, today.month, max(last_mtd_day, 1))

    current_year_series = safe(lambda: _yearly_series(today.year, today.month), [None] * 12)
    previous_year_series = safe(lambda: _yearly_series(last_year), [None] * 12)
    yearly_series = [
        {"month": month, "current": current_year_series[month - 1], "previous": previous_year_series[month - 1]}
        for month in range(1, 13)
    ]
    current_as_of = next((item["as_of"] for item in reversed(current_year_series) if item), None)

    previous_rows = safe(lambda: _codis_rows(previous_start, previous_end), [])
    last_rows = safe(lambda: _codis_rows(last_start, last_end), [])
    mtd_rows = safe(lambda: _codis_rows(mtd_start, mtd_end), [])
    last_mtd_rows = safe(lambda: _codis_rows(last_mtd_start, last_mtd_end), [])

    previous = _summarize_rows(previous_rows, previous_start, previous_end)
    last = _summarize_rows(last_rows, last_start, last_end)
    mtd = _summarize_rows(mtd_rows, mtd_start, mtd_end)
    last_mtd = _summarize_rows(last_mtd_rows, last_mtd_start, last_mtd_end)

    normal = safe(lambda: get_normals(today.month), None)
    if normal:
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        observed_days = int((mtd or {}).get("days") or 0)
        rainfall = _to_float(normal.get("rainfall"))
        normal["rainfall_full"] = rainfall
        normal["rainfall_prorated"] = round(rainfall * observed_days / days_in_month, 1) if rainfall is not None else None

    return {
        "generated_at": dt.datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "station": {"id": CLIMATE_STATION_ID, "name": CLIMATE_STATION_NAME},
        "periods": {
            "monthly": {
                "label": "上月",
                "current": f"{previous_year}-{previous_month:02d}",
                "previous_year": f"{last_year}-{previous_month:02d}",
            },
            "mtd": {
                "label": "本月至今",
                "current": mtd_start.isoformat(),
                "as_of": mtd.get("as_of") if mtd else None,
            },
            "normals": {
                "month": today.month,
                "period": (
                    f"{normal.get('period_start')}-{normal.get('period_end')}"
                    if normal and normal.get("period_start") and normal.get("period_end")
                    else None
                ),
            },
            "yearly": {
                "current_year": today.year,
                "previous_year": last_year,
                "as_of": current_as_of,
            },
        },
        "modes": {
            "monthly": {
                "current": previous,
                "previous_year": last,
                "delta_mean_t": _delta(previous, last, "mean_t"),
                "delta_rainfall": _delta(previous, last, "rainfall"),
            },
            "mtd": {
                "current": mtd,
                "previous_year": last_mtd,
                "delta_mean_t": _delta(mtd, last_mtd, "mean_t"),
                "delta_rainfall": _delta(mtd, last_mtd, "rainfall"),
            },
            "normals": {
                "current": mtd,
                "normal": normal,
                "delta_mean_t": _delta(mtd, normal, "mean_t"),
                "delta_rainfall": _delta(mtd, normal, "rainfall", "rainfall_prorated"),
            },
            "yearly": {
                "series": yearly_series,
            },
        },
        "sources": {
            "observation": "中央氣象署 CODiS 氣候觀測資料查詢服務（日報表）",
            "normals": "中央氣象署 Open Data C-B0027-001（1991–2020 月平均）",
        },
        "errors": errors,
    }


def _year_month_summary(year: int) -> dict[int, dict[str, float | None]]:
    rows = _codis_rows(dt.date(year, 1, 1), dt.date(year, 12, 31))
    result: dict[int, dict[str, float | None]] = {}
    for month in range(1, 13):
        month_start, month_end = _month_bounds(year, month)
        summary = _summarize_rows(rows, month_start, month_end)
        result[month] = {
            "mean_t": summary.get("mean_t") if summary else None,
            "rainfall": summary.get("rainfall") if summary else None,
        }
    return result


def _empty_month_summary() -> dict[int, dict[str, float | None]]:
    return {month: {"mean_t": None, "rainfall": None} for month in range(1, 13)}


def _average(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return round(sum(valid) / len(valid), 1) if valid else None


def build_baseline_snapshot(current_year: int | None = None) -> dict[str, Any]:
    if current_year is None:
        current_year = dt.datetime.now(TAIPEI).year
    errors: list[str] = []
    yearly: dict[int, dict[int, dict[str, float | None]]] = {}
    for year in range(current_year - max(count for _, count, _ in BASELINE_WINDOWS), current_year + 1):
        try:
            yearly[year] = _year_month_summary(year)
        except Exception as exc:
            errors.append(f"{year}: {exc}")
            yearly[year] = _empty_month_summary()

    periods: dict[str, Any] = {}
    for key, count, label in BASELINE_WINDOWS:
        years = [
            year for year in range(current_year - count, current_year)
            if any(item["mean_t"] is not None or item["rainfall"] is not None for item in yearly.get(year, {}).values())
        ]
        periods[key] = {
            "label": label,
            "years": years,
            "count": len(years),
            "period": f"{min(years)}-{max(years)}" if years else None,
        }

    series: list[dict[str, Any]] = []
    for month in range(1, 13):
        baselines: dict[str, dict[str, float | None]] = {}
        for key, _, _ in BASELINE_WINDOWS:
            years = periods[key]["years"]
            baselines[key] = {
                "mean_t": _average([yearly[year][month]["mean_t"] for year in years]),
                "rainfall": _average([yearly[year][month]["rainfall"] for year in years]),
            }
        series.append({
            "month": month,
            "current": yearly.get(current_year, _empty_month_summary())[month],
            "baselines": baselines,
        })

    return {
        "version": 2,
        "generated_at": dt.datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "station": {"id": CLIMATE_STATION_ID, "name": CLIMATE_STATION_NAME},
        "current_year": current_year,
        "periods": periods,
        "series": series,
        "source": "中央氣象署 CODiS 氣候觀測資料查詢服務（日報表）",
        "errors": errors,
    }


def save_baseline_snapshot(snapshot: dict[str, Any]) -> None:
    BASELINES_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    BASELINES_FILE.write_text(payload, encoding="utf-8")


def load_baseline_snapshot() -> dict[str, Any] | None:
    if not BASELINES_FILE.exists():
        return None
    try:
        return json.loads(BASELINES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def get_baseline_snapshot(force: bool = False) -> dict[str, Any]:
    current_year = dt.datetime.now(TAIPEI).year
    cached = load_baseline_snapshot()
    if cached and not force and cached.get("version") == 2 and cached.get("current_year") == current_year:
        return cached
    snapshot = build_baseline_snapshot(current_year)
    save_baseline_snapshot(snapshot)
    return snapshot


def save_snapshot(snapshot: dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    (SNAPSHOT_DIR / "climate_latest.json").write_text(payload, encoding="utf-8")


def load_latest_snapshot() -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / "climate_latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
