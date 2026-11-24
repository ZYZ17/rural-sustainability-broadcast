from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.providers import climate_cwa


def print_period(name: str, period: dict | None) -> None:
    if not period:
        print(f"{name}: no data")
        return
    print(
        f"{name}: {period.get('start')} ~ {period.get('end')} "
        f"days={period.get('days')} mean_t={period.get('mean_t')} rainfall={period.get('rainfall')}"
    )


def main() -> None:
    snapshot = climate_cwa.build_climate_snapshot()
    climate_cwa.save_snapshot(snapshot)

    print(f"generated_at={snapshot['generated_at']}")
    print(f"station={snapshot['station']['name']}({snapshot['station']['id']})")
    modes = snapshot["modes"]
    print_period("monthly.current", modes["monthly"].get("current"))
    print_period("monthly.previous_year", modes["monthly"].get("previous_year"))
    print_period("mtd.current", modes["mtd"].get("current"))
    print_period("mtd.previous_year", modes["mtd"].get("previous_year"))
    print_period("normals.current", modes["normals"].get("current"))
    print(f"normals={modes['normals'].get('normal')}")
    if snapshot.get("errors"):
        print("errors=" + " | ".join(snapshot["errors"]))


if __name__ == "__main__":
    main()
