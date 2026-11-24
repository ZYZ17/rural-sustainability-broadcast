from __future__ import annotations

import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import requests

from ..config import (
    CWA_API_KEY,
    CWA_BASE,
    HEAVY_RAIN_POP_THRESHOLD,
    LOW_TEMP_THRESHOLD,
    SNAPSHOT_DIR,
    TARGET_COUNTY,
    TARGET_TOWN,
)

TAIPEI = ZoneInfo("Asia/Taipei")
WARNING_KIND_PRIORITY = {
    "typhoon": 0,
    "low_temp": 1,
    "heavy_rain": 2,
    "strong_wind": 3,
    "other": 4,
}


class CwaError(RuntimeError):
    pass


def _norm(value: str | None) -> str:
    return (value or "").replace("台", "臺").strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


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


def parse_dt(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI)
    return parsed


def is_configured() -> bool:
    return bool(CWA_API_KEY)


def _get(dataset: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not CWA_API_KEY:
        raise CwaError("CWA_API_KEY is not configured")
    query = {"Authorization": CWA_API_KEY, "format": "JSON"}
    if params:
        query.update(params)
    response = requests.get(f"{CWA_BASE}/{dataset}", params=query, timeout=60)
    response.raise_for_status()
    response.encoding = "utf-8"
    payload = response.json()
    if not payload.get("success", True):
        raise CwaError(f"CWA request failed for {dataset}")
    return payload


def get_warnings(county: str = TARGET_COUNTY) -> list[dict[str, Any]]:
    payload = _get("W-C0033-001")
    records = payload.get("records") or {}
    locations = _as_list(records.get("location"))
    target = next(
        (loc for loc in locations if _norm(loc.get("locationName")) == _norm(county)),
        None,
    )
    if target is None:
        return []

    now = dt.datetime.now(TAIPEI)
    warnings: list[dict[str, Any]] = []
    hazards = _as_list(_ci_get(_ci_get(target, "hazardConditions") or {}, "hazards"))
    for hazard in hazards:
        info = _ci_get(hazard, "info") or {}
        valid = _ci_get(hazard, "validTime") or {}
        phenomena = _ci_get(info, "phenomena", "")
        start = parse_dt(_ci_get(valid, "startTime"))
        end = parse_dt(_ci_get(valid, "endTime"))
        if end is not None and end < now - dt.timedelta(hours=1):
            continue
        warnings.append(
            {
                "phenomena": phenomena,
                "significance": _ci_get(info, "significance", ""),
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "kind": warning_kind(phenomena),
            }
        )
    return warnings


def warning_kind(phenomena: str) -> str:
    text = phenomena or ""
    if "颱風" in text:
        return "typhoon"
    if any(keyword in text for keyword in ("低溫", "寒流", "冷氣團", "輻射冷卻")):
        return "low_temp"
    if any(keyword in text for keyword in ("豪雨", "大雨")):
        return "heavy_rain"
    if "強風" in text:
        return "strong_wind"
    return "other"


def get_typhoon() -> dict[str, Any] | None:
    payload = _get("W-C0034-001")
    records = payload.get("records") or {}
    infos = _as_list(_ci_get(records, "info"))
    for info in infos:
        headline = info.get("headline") or ""
        if info.get("event") != "颱風":
            continue
        if info.get("urgency") == "Past" or "解除" in headline:
            continue
        areas = [
            _ci_get(area, "areaDesc")
            for area in _as_list(_ci_get(info, "area"))
            if _ci_get(area, "areaDesc")
        ]
        return {
            "headline": headline,
            "severity": info.get("severity"),
            "urgency": info.get("urgency"),
            "effective": info.get("effective"),
            "onset": info.get("onset"),
            "expires": info.get("expires"),
            "areas": areas,
            "affects_target": _norm(TARGET_COUNTY) in {_norm(area) for area in areas},
        }
    return None


def _collect_locations(node: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_locations(item, output)
        return
    if not isinstance(node, dict):
        return
    if _ci_get(node, "locationName"):
        output.append(node)
        return
    for key in ("location", "locations"):
        child = _ci_get(node, key)
        if child:
            _collect_locations(child, output)


def _location_from_payload(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    records = payload.get("records") or {}
    locations: list[dict[str, Any]] = []
    _collect_locations(records, locations)
    return next(
        (loc for loc in locations if _norm(_ci_get(loc, "locationName")) == _norm(name)),
        locations[0] if locations else None,
    )


def _elements(location: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for element in _as_list(_ci_get(location, "weatherElement")):
        result[_ci_get(element, "ElementName")] = element
    return result


def _element_times(element: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not element:
        return []
    return _as_list(_ci_get(element, "Time"))


def _value_of(time_item: dict[str, Any], key: str) -> Any:
    values = _as_list(_ci_get(time_item, "ElementValue"))
    if not values:
        return None
    return _ci_get(values[0], key)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_week(town: str = TARGET_TOWN) -> dict[str, Any]:
    payload = _get("F-D0047-075", {"LocationName": town})
    location = _location_from_payload(payload, town)
    if location is None:
        return {"location": town, "days": []}
    elements = _elements(location)

    days: dict[str, dict[str, Any]] = {}

    def day_for(date_value: str) -> dict[str, Any]:
        return days.setdefault(
            date_value,
            {"date": date_value, "min_t": None, "max_t": None, "pop": None, "wx": set(), "description": ""},
        )

    for time_item in _element_times(elements.get("最低溫度")):
        start = _ci_get(time_item, "StartTime")
        value = _value_of(time_item, "MinTemperature")
        if not start or value is None:
            continue
        temperature = _to_float(value)
        if temperature is None:
            continue
        day = day_for(str(start)[:10])
        day["min_t"] = temperature if day["min_t"] is None else min(day["min_t"], temperature)

    for time_item in _element_times(elements.get("最高溫度")):
        start = _ci_get(time_item, "StartTime")
        value = _value_of(time_item, "MaxTemperature")
        if not start or value is None:
            continue
        temperature = _to_float(value)
        if temperature is None:
            continue
        day = day_for(str(start)[:10])
        day["max_t"] = temperature if day["max_t"] is None else max(day["max_t"], temperature)

    for time_item in _element_times(elements.get("12小時降雨機率")):
        start = _ci_get(time_item, "StartTime")
        value = _value_of(time_item, "ProbabilityOfPrecipitation")
        if not start or value is None:
            continue
        probability = _to_float(value)
        if probability is None:
            continue
        day = day_for(str(start)[:10])
        day["pop"] = probability if day["pop"] is None else max(day["pop"], probability)

    for time_item in _element_times(elements.get("天氣現象")):
        start = _ci_get(time_item, "StartTime")
        value = _value_of(time_item, "Weather")
        if not start or not value:
            continue
        day_for(str(start)[:10])["wx"].add(value)

    for time_item in _element_times(elements.get("天氣預報綜合描述")):
        start = _ci_get(time_item, "StartTime")
        value = _value_of(time_item, "WeatherDescription")
        if not start or not value:
            continue
        day_for(str(start)[:10])["description"] = value

    ordered = []
    for date_value in sorted(days):
        day = days[date_value]
        day["wx"] = sorted(day["wx"])
        ordered.append(day)
    return {"location": _ci_get(location, "locationName", town), "days": ordered}


def get_now36h(county: str = TARGET_COUNTY) -> dict[str, Any]:
    payload = _get("F-C0032-001")
    location = _location_from_payload(payload, county)
    if location is None:
        return {"county": county, "periods": []}
    elements = _elements(location)

    def times(name: str) -> list[dict[str, Any]]:
        element = elements.get(name)
        if not element:
            return []
        return _as_list(_ci_get(element, "Time"))

    def param(time_item: dict[str, Any], key: str) -> Any:
        parameter = _ci_get(time_item, "parameter") or {}
        return _ci_get(parameter, key) if isinstance(parameter, dict) else None

    wx_times = times("Wx")
    pop_times = times("PoP")
    mint_times = times("MinT")
    maxt_times = times("MaxT")
    ci_times = times("CI")

    periods = []
    for index, wx_time in enumerate(wx_times):
        def pick(source: list[dict[str, Any]], key: str) -> Any:
            if index >= len(source):
                return None
            return param(source[index], key)

        periods.append(
            {
                "start": _ci_get(wx_time, "startTime"),
                "end": _ci_get(wx_time, "endTime"),
                "wx": pick(wx_times, "parameterName"),
                "pop": pick(pop_times, "parameterName"),
                "min_t": pick(mint_times, "parameterName"),
                "max_t": pick(maxt_times, "parameterName"),
                "ci": pick(ci_times, "parameterName"),
            }
        )
    return {"county": _ci_get(location, "locationName", county), "periods": periods}


def derive_alerts(
    warnings: list[dict[str, Any]],
    typhoon: dict[str, Any] | None,
    week: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    kinds: set[str] = set()

    for warning in warnings:
        kind = warning.get("kind") or "other"
        if kind == "typhoon":
            continue
        text = f"{warning.get('phenomena', '')}{warning.get('significance', '')}"
        end = parse_dt(warning.get("end"))
        if end:
            text += f"，影響到{end.month}月{end.day}號{end.hour}點"
        alerts.append({"kind": kind, "level": warning.get("significance"), "text": text, "source": "cwa_warning"})
        kinds.add(kind)

    if typhoon:
        text = typhoon.get("headline") or "颱風警報"
        if typhoon.get("affects_target"):
            text += "，臺中市列入警戒區"
        alerts.append({"kind": "typhoon", "level": typhoon.get("severity"), "text": text, "source": "cwa_typhoon"})
        kinds.add("typhoon")

    for day in (week.get("days") or [])[:3]:
        date_value = day.get("date", "")
        month_day = ""
        try:
            parsed = dt.date.fromisoformat(date_value)
            month_day = f"{parsed.month}月{parsed.day}號"
        except ValueError:
            month_day = date_value

        min_t = day.get("min_t")
        if min_t is not None and min_t <= LOW_TEMP_THRESHOLD and "low_temp" not in kinds:
            alerts.append(
                {
                    "kind": "low_temp",
                    "level": "forecast",
                    "text": f"{month_day}低溫{int(min_t)}度，注意寒害",
                    "source": "cwa_forecast",
                }
            )
            kinds.add("low_temp")

        pop = day.get("pop")
        if pop is not None and pop >= HEAVY_RAIN_POP_THRESHOLD and "heavy_rain" not in kinds:
            alerts.append(
                {
                    "kind": "heavy_rain",
                    "level": "forecast",
                    "text": f"{month_day}降雨機率{int(pop)}%，注意排水",
                    "source": "cwa_forecast",
                }
            )
            kinds.add("heavy_rain")

    alerts.sort(key=lambda item: WARNING_KIND_PRIORITY.get(item.get("kind", "other"), 9))
    return alerts


def summarize(week: dict[str, Any], now36h: dict[str, Any]) -> str:
    parts: list[str] = []
    periods = now36h.get("periods") or []
    if periods:
        first = periods[0]
        county = now36h.get("county") or TARGET_COUNTY
        text = f"今天{county}{first.get('wx') or ''}"
        if first.get("min_t") is not None and first.get("max_t") is not None:
            text += f"，氣溫{first['min_t']}到{first['max_t']}度"
        if first.get("pop") is not None:
            text += f"，降雨機率{first['pop']}%"
        parts.append(text + "。")

    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    for day in week.get("days") or []:
        if day.get("date") != tomorrow:
            continue
        text = f"明天{week.get('location') or TARGET_TOWN}{'、'.join(day.get('wx') or [])}"
        if day.get("min_t") is not None and day.get("max_t") is not None:
            text += f"，{int(day['min_t'])}到{int(day['max_t'])}度"
        if day.get("pop") is not None:
            text += f"，降雨機率{int(day['pop'])}%"
        parts.append(text + "。")
        break
    return "".join(parts) or "目前無氣象資料。"


def build_weather_snapshot() -> dict[str, Any]:
    errors: list[str] = []

    def safe(function: Any, default: Any) -> Any:
        try:
            return function()
        except Exception as exc:
            errors.append(f"{getattr(function, '__name__', 'task')}: {exc}")
            return default

    warnings = safe(get_warnings, [])
    typhoon = safe(get_typhoon, None)
    week = safe(get_week, {"location": TARGET_TOWN, "days": []})
    now36h = safe(get_now36h, {"county": TARGET_COUNTY, "periods": []})
    alerts = derive_alerts(warnings, typhoon, week)
    summary = summarize(week, now36h)
    return {
        "generated_at": dt.datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "county": TARGET_COUNTY,
        "town": TARGET_TOWN,
        "warnings": warnings,
        "typhoon": typhoon,
        "week": week,
        "now36h": now36h,
        "alerts": alerts,
        "summary": summary,
        "errors": errors,
    }


def save_snapshot(snapshot: dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    (SNAPSHOT_DIR / "weather_latest.json").write_text(payload, encoding="utf-8")


def load_latest_snapshot() -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / "weather_latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
