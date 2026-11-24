from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request

from ..config import DATA_DIR, PREF_HASH_SALT, PREF_TRUST_PROXY, PREFERENCES_FILE
from .broadcast_options import normalize_options

_LOCK = threading.Lock()
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_MAX_IDENTIFIERS = 20


def normalize_client_id(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text if _CLIENT_ID_RE.fullmatch(text) else None


def client_ip_hash(request: Request) -> str:
    ip = ""
    if PREF_TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() if forwarded else ""
    if not ip and request.client:
        ip = request.client.host or ""
    if not ip:
        return ""
    return hashlib.sha256(f"{PREF_HASH_SALT}:{ip}".encode("utf-8")).hexdigest()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "profiles": []}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_store() -> dict[str, Any]:
    if not PREFERENCES_FILE.exists():
        return _empty_store()
    try:
        store = json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(store, dict) or not isinstance(store.get("profiles"), list):
        return _empty_store()
    store["version"] = 1
    store["profiles"] = [p for p in store["profiles"] if isinstance(p, dict)]
    return store


def _write_store(store: dict[str, Any]) -> None:
    PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(PREFERENCES_FILE) + ".tmp")
    temp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, PREFERENCES_FILE)


def _valid_ids(name: str, key: str) -> set[str]:
    path = DATA_DIR / name
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(item[key]) for item in items if isinstance(item, dict) and key in item}


def _normalize_selection(crop_ids: Any, market_codes: Any) -> tuple[list[str], list[str]]:
    valid_crops = _valid_ids("crops.json", "id")
    valid_markets = _valid_ids("markets.json", "code")
    crops = list(dict.fromkeys(str(c) for c in _as_list(crop_ids) if str(c) in valid_crops))
    markets = list(dict.fromkeys(str(m) for m in _as_list(market_codes) if str(m) in valid_markets))
    return crops, markets


def _find_profile(store: dict[str, Any], client_id: str | None, ip_hash: str) -> dict[str, Any] | None:
    if client_id:
        for profile in store["profiles"]:
            if client_id in _as_list(profile.get("client_ids")):
                return profile
    if ip_hash:
        for profile in store["profiles"]:
            if ip_hash in _as_list(profile.get("ip_hashes")):
                return profile
    return None


def _source(profile: dict[str, Any], client_id: str | None, ip_hash: str) -> str:
    if client_id and client_id in _as_list(profile.get("client_ids")):
        return "client"
    if ip_hash and ip_hash in _as_list(profile.get("ip_hashes")):
        return "ip"
    return "none"


def get_preferences(client_id: str | None, ip_hash: str) -> dict[str, Any]:
    with _LOCK:
        store = _load_store()
        profile = _find_profile(store, client_id, ip_hash)
        if profile is None:
            return {
                "configured": False,
                "crop_ids": [],
                "market_codes": [],
                "broadcast_options": normalize_options(None),
                "source": None,
            }
        crops, markets = _normalize_selection(profile.get("crop_ids"), profile.get("market_codes"))
        return {
            "configured": True,
            "crop_ids": crops,
            "market_codes": markets,
            "broadcast_options": normalize_options(profile.get("broadcast_options")),
            "source": _source(profile, client_id, ip_hash),
        }


def save_preferences(
    client_id: str | None,
    ip_hash: str,
    crop_ids: Any,
    market_codes: Any,
    broadcast_options: Any = None,
) -> dict[str, Any]:
    crops, markets = _normalize_selection(crop_ids, market_codes)
    options = normalize_options(broadcast_options)
    if not crops or not markets:
        raise ValueError("作物與市場都至少要選擇一項")

    with _LOCK:
        store = _load_store()
        by_client = None
        by_ip = None
        if client_id:
            by_client = next(
                (p for p in store["profiles"] if client_id in _as_list(p.get("client_ids"))),
                None,
            )
        if ip_hash:
            by_ip = next(
                (p for p in store["profiles"] if ip_hash in _as_list(p.get("ip_hashes"))),
                None,
            )

        profile = by_client or by_ip
        if by_client is not None and by_ip is not None and by_client is not by_ip:
            for key in ("client_ids", "ip_hashes"):
                merged = _as_list(by_client.get(key)) + [
                    item for item in _as_list(by_ip.get(key)) if item not in _as_list(by_client.get(key))
                ]
                by_client[key] = list(dict.fromkeys(merged))[-_MAX_IDENTIFIERS:]
            store["profiles"].remove(by_ip)

        if profile is None:
            profile = {}
            store["profiles"].append(profile)

        for key, value in (("client_ids", client_id), ("ip_hashes", ip_hash)):
            current = list(dict.fromkeys(str(item) for item in _as_list(profile.get(key))))
            if value and value not in current:
                current.append(value)
            profile[key] = current[-_MAX_IDENTIFIERS:]

        profile["crop_ids"] = crops
        profile["market_codes"] = markets
        profile["broadcast_options"] = options
        profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_store(store)

    return {
        "configured": True,
        "crop_ids": crops,
        "market_codes": markets,
        "broadcast_options": options,
        "source": "client" if client_id else ("ip" if ip_hash else "none"),
    }
