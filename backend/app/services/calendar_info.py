from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from typing import Any

from ..config import DATA_DIR

try:
    from lunar_python import Solar
except ImportError:
    Solar = None

_JIEQI_TRADITIONAL = {
    "惊蛰": "驚蟄",
    "谷雨": "穀雨",
    "小满": "小滿",
    "芒种": "芒種",
    "处暑": "處暑",
}
_ZODIAC_TRADITIONAL = {
    "龙": "龍",
    "马": "馬",
    "鸡": "雞",
    "猪": "豬",
}


def _traditional(text: str) -> str:
    result = text
    for simplified, traditional in {**_JIEQI_TRADITIONAL, **_ZODIAC_TRADITIONAL}.items():
        result = result.replace(simplified, traditional)
    return result


@lru_cache(maxsize=1)
def _festival_definitions() -> list[dict[str, Any]]:
    path = DATA_DIR / "festival_greetings.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    festivals = payload.get("festivals")
    return festivals if isinstance(festivals, list) else []


def _lunar_for(day: dt.date):
    return Solar.fromYmd(day.year, day.month, day.day).getLunar()


def _match_festival(day: dt.date, lunar, jieqi: str) -> dict[str, Any] | None:
    month = lunar.getMonth()
    day_of_month = lunar.getDay()
    for festival in _festival_definitions():
        match = festival.get("match") or {}
        lunar_match = match.get("lunar")
        if lunar_match and month > 0:
            try:
                if (
                    int(lunar_match.get("month", 0)) == month
                    and int(lunar_match.get("day", 0)) == day_of_month
                ):
                    return festival
            except (TypeError, ValueError):
                pass
        term = match.get("solar_term")
        if term and jieqi == term:
            return festival
        if match.get("lunar_eve") and month == 12:
            next_lunar = _lunar_for(day + dt.timedelta(days=1))
            if next_lunar.getMonth() == 1 and next_lunar.getDay() == 1:
                return festival
    return None


def _festival_info(day: dt.date, lunar, jieqi: str) -> dict[str, Any] | None:
    festival = _match_festival(day, lunar, jieqi)
    if festival is None:
        return None

    if festival.get("zodiac_source") == "next":
        zodiac_lunar = _lunar_for(day + dt.timedelta(days=1))
    else:
        zodiac_lunar = lunar
    zodiac = _traditional(zodiac_lunar.getYearShengXiao() or "")
    greetings = [
        str(greeting).replace("{zodiac}", zodiac)
        for greeting in (festival.get("greetings") or [])
    ]
    return {
        "key": festival.get("key", ""),
        "name_zh": festival.get("name_zh", ""),
        "greetings": greetings,
        "zodiac": zodiac,
    }


def get_calendar_info(day: dt.date) -> dict[str, Any]:
    empty: dict[str, Any] = {"lunar_text": "", "jieqi_text": "", "jieqi": "", "festival": None}
    if Solar is None:
        return empty
    try:
        lunar = _lunar_for(day)
        month = lunar.getMonthInChinese().replace("闰", "閏")
        lunar_text = f"農曆{month}月{lunar.getDayInChinese()}"
        jieqi = _traditional(lunar.getJieQi() or "")
        jieqi_text = f"今晡日係{jieqi}，這日係節氣。" if jieqi else ""
        return {
            "lunar_text": lunar_text,
            "jieqi_text": jieqi_text,
            "jieqi": jieqi,
            "festival": _festival_info(day, lunar, jieqi),
        }
    except Exception:
        return empty
