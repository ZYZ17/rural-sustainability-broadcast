from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.providers import weather_cwa


def main() -> None:
    snapshot = weather_cwa.build_weather_snapshot()
    weather_cwa.save_snapshot(snapshot)

    print(f"generated_at={snapshot['generated_at']}")
    print(f"summary={snapshot['summary']}")
    print(f"alerts={len(snapshot['alerts'])}")
    for alert in snapshot["alerts"]:
        print(f"  [{alert['kind']}] {alert['text']} ({alert['source']})")
    print(f"warnings={len(snapshot['warnings'])}")
    for warning in snapshot["warnings"]:
        print(f"  {warning['phenomena']}{warning['significance']} kind={warning['kind']} end={warning.get('end')}")
    print(f"typhoon={snapshot['typhoon']}")
    print(f"week_days={len(snapshot['week'].get('days', []))}")
    for day in snapshot["week"].get("days", [])[:7]:
        print(
            f"  {day['date']} min={day.get('min_t')} max={day.get('max_t')} "
            f"pop={day.get('pop')} wx={'/'.join(day.get('wx') or [])}"
        )
    print(f"now36h_periods={len(snapshot['now36h'].get('periods', []))}")
    for period in snapshot["now36h"].get("periods", [])[:3]:
        print(f"  {period.get('start')} ~ {period.get('end')} {period.get('wx')} {period.get('min_t')}-{period.get('max_t')} pop={period.get('pop')}")
    if snapshot.get("errors"):
        print("errors=" + " | ".join(snapshot["errors"]))


if __name__ == "__main__":
    main()
