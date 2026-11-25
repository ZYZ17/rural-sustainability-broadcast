from __future__ import annotations

import datetime as dt
import json
from typing import Any

from ..config import DATA_DIR
from ..providers import prices_moa, weather_cwa
from .broadcast_options import normalize_options
from .calendar_info import get_calendar_info
from .textnorm import date_to_zh, field_to_zh, normalize_tts_text, trend_to_zh

TAIPEI = dt.timezone(dt.timedelta(hours=8))


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _now_iso() -> str:
    return dt.datetime.now(TAIPEI).isoformat(timespec="seconds")


def _get_prices_snapshot() -> dict[str, Any]:
    snapshot = prices_moa.load_latest_snapshot()
    if snapshot is None:
        snapshot = prices_moa.build_snapshot()
        prices_moa.save_snapshot(snapshot)
    return snapshot


def _get_weather_snapshot() -> dict[str, Any]:
    snapshot = weather_cwa.load_latest_snapshot()
    if snapshot is None:
        snapshot = weather_cwa.build_weather_snapshot()
        weather_cwa.save_snapshot(snapshot)
    return snapshot


def build_broadcast(
    crop_ids: list[str],
    market_codes: list[str],
    include_weather: bool = True,
    options: list[str] | None = None,
) -> dict[str, Any]:
    crops = {crop["id"]: crop for crop in _load("crops.json")}
    templates = _load("broadcast_templates.json")
    price_snapshot = _get_prices_snapshot()
    weather_snapshot = _get_weather_snapshot()
    enabled_options = normalize_options(options)
    today = dt.datetime.now(TAIPEI).date()
    calendar_info = get_calendar_info(today)

    segments: list[dict[str, Any]] = []
    trade_date = price_snapshot.get("trade_date") or today.isoformat()
    intro_text = templates["intro"].format(date=date_to_zh(today.isoformat()))
    if calendar_info["lunar_text"]:
        intro_text += calendar_info["lunar_text"] + "。"
    if calendar_info["jieqi_text"]:
        intro_text += calendar_info["jieqi_text"]
    segments.append({"type": "intro", "text": intro_text})

    festival = calendar_info.get("festival")
    if festival and festival.get("greetings"):
        segments.append({
            "type": "festival",
            "text": f"{festival['name_zh']}：{' '.join(festival['greetings'])}",
            "data": {
                "key": festival.get("key"),
                "name_zh": festival.get("name_zh"),
                "greetings": festival["greetings"],
            },
        })

    if trade_date != today.isoformat():
        segments.append(
            {
                "type": "trade_date",
                "text": templates["trade_date"].format(date=date_to_zh(trade_date)),
            }
        )

    if include_weather:
        alerts = weather_snapshot.get("alerts") or []
        if alerts:
            for alert in alerts[:2]:
                segments.append(
                    {
                        "type": "weather",
                        "kind": alert.get("kind"),
                        "level": alert.get("level"),
                        "text": templates["weather_alert"].format(text=alert.get("text", "")),
                    }
                )
        else:
            summary = weather_snapshot.get("summary") or "目前無氣象資料。"
            segments.append(
                {
                    "type": "weather",
                    "text": templates["weather_summary"].format(text=summary),
                }
            )

    prices = prices_moa.get_prices_for(crop_ids, market_codes, price_snapshot)
    for crop_id in crop_ids:
        crop = crops.get(crop_id)
        if crop is None:
            continue
        rows = [row for row in prices if row.get("crop_id") == crop_id]
        if not rows:
            segments.append(
                {
                    "type": "price",
                    "text": templates["no_price"].format(crop=crop.get("name_hakka") or crop["name_zh"]),
                    "data": {"crop_id": crop_id, "name_zh": crop["name_zh"]},
                }
            )
            continue
        for row in rows:
            details = []
            if "upper" in enabled_options:
                details.append(f"上價{field_to_zh(row.get('upper'))}元")
            if "middle" in enabled_options:
                details.append(f"中價{field_to_zh(row.get('middle'))}元")
            if "lower" in enabled_options:
                details.append(f"下價{field_to_zh(row.get('lower'))}元")
            if "avg" in enabled_options:
                details.append(f"平均價{field_to_zh(row.get('avg'))}元")
            if "volume" in enabled_options:
                details.append(f"交易量{field_to_zh(row.get('volume'))}公斤")
            trend_text = ""
            if "trend" in enabled_options and row.get("change") is not None:
                trend_text = "，比昨晡日" + trend_to_zh(row.get("change"))
            segments.append(
                {
                    "type": "price",
                    "text": templates["price"].format(
                        crop=crop.get("name_hakka") or crop["name_zh"],
                        market=row["market_display"] or row["market_name"],
                        details="，" + "，".join(details) if details else "",
                        trend=trend_text,
                    ),
                    "data": row,
                }
            )

    segments.append({"type": "outro", "text": templates["outro"]})
    # VoxHakka 的 G2P 會把全形逗號轉成獨立的停頓 token；
    # 在每段之間放三個逗號，讓「氣象→行情」「行情→行情」約停一秒，
    # 避免整段廣播聽起來太急促。停頓只進 tts_text，不進頁面顯示的 segments。
    paused_parts: list[str] = []
    for index, segment in enumerate(segments):
        text = segment["text"].strip()
        if index < len(segments) - 1:
            if not text.endswith(("。", "！", "？")):
                text += "。"
            text += "，，，"
        paused_parts.append(text)
    full_text = "".join(paused_parts)

    return {
        "segments": segments,
        "full_text": full_text,
        "tts_text": normalize_tts_text(full_text),
        "trade_date": trade_date,
        "options": enabled_options,
        "lunar_date": calendar_info["lunar_text"],
        "solar_term": calendar_info["jieqi"],
        "festival": festival,
        "generated_at": _now_iso(),
        "audio_url": None,
        "weather_generated_at": weather_snapshot.get("generated_at"),
        "weather_errors": weather_snapshot.get("errors") or [],
    }
