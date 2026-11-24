from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import DATA_DIR

PALETTES = [
    ("#f59e0b", "#b45309"),
    ("#f97316", "#c2410c"),
    ("#84cc16", "#3f6212"),
    ("#22c55e", "#166534"),
    ("#14b8a6", "#115e59"),
    ("#ef4444", "#991b1b"),
    ("#a855f7", "#6b21a8"),
    ("#eab308", "#854d0e"),
    ("#06b6d4", "#155e75"),
    ("#8b5cf6", "#5b21b6"),
]

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300" role="img" aria-label="{name}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect width="400" height="300" rx="28" fill="url(#g)"/>
  <circle cx="200" cy="122" r="72" fill="#ffffff" fill-opacity="0.93"/>
  <text x="200" y="150" text-anchor="middle" font-family="'Noto Sans TC','Microsoft JhengHei',sans-serif" font-size="70" font-weight="700" fill="{c2}">{initial}</text>
  <text x="200" y="248" text-anchor="middle" font-family="'Noto Sans TC','Microsoft JhengHei',sans-serif" font-size="30" font-weight="700" fill="#ffffff">{name}</text>
</svg>
"""


def main() -> None:
    crops = json.loads((DATA_DIR / "crops.json").read_text(encoding="utf-8"))
    output_dir = ROOT / "frontend" / "public" / "crops"
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, crop in enumerate(crops):
        c1, c2 = PALETTES[index % len(PALETTES)]
        name = crop["name_zh"]
        svg = TEMPLATE.format(
            name=html.escape(name),
            initial=html.escape(name[0]),
            c1=c1,
            c2=c2,
        )
        filename = Path(crop["image"]).name
        (output_dir / filename).write_text(svg, encoding="utf-8")
        print(f"wrote {filename}")


if __name__ == "__main__":
    main()
