from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import DATA_DIR, PRESET_MARKET_CODES
from backend.app.providers import prices_moa


def main() -> None:
    snapshot = prices_moa.build_snapshot()
    dated_path = prices_moa.save_snapshot(snapshot)
    markets_path = DATA_DIR / "markets.json"
    markets_path.write_text(json.dumps(snapshot["markets"], ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"trade_date={snapshot['trade_date']}")
    print(f"records={snapshot['record_count']} aggregated={len(snapshot['aggregated'])} markets={len(snapshot['markets'])}")
    print(f"snapshot={dated_path}")

    target_codes = set(PRESET_MARKET_CODES)
    unmapped = sorted(
        {
            row["crop_name"]
            for row in snapshot["aggregated"]
            if row["market_code"] in target_codes and not row.get("crop_id")
        }
    )
    print("target_markets_unmapped_crops=" + " / ".join(unmapped))

    print("target_markets_mapped_sample:")
    count = 0
    for row in snapshot["aggregated"]:
        if row["market_code"] not in target_codes or not row.get("crop_id"):
            continue
        print(
            f"  {row['market_display']}({row['market_code']}) {row['crop_name']} "
            f"avg={row['avg']} volume={row['volume']} crop_id={row['crop_id']}"
        )
        count += 1
        if count >= 40:
            break


if __name__ == "__main__":
    main()
