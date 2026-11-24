from __future__ import annotations

from typing import Any

BROADCAST_OPTION_KEYS = ("upper", "middle", "lower", "avg", "volume", "trend")


def normalize_options(value: Any) -> list[str]:
    if value is None or not isinstance(value, list):
        return list(BROADCAST_OPTION_KEYS)
    return list(dict.fromkeys(str(item) for item in value if str(item) in BROADCAST_OPTION_KEYS))
