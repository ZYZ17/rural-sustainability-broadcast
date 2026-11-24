from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from ..providers import tts_voxhakka

TAIPEI = dt.timezone(dt.timedelta(hours=8))

_lock = threading.Lock()
_state: dict[str, Any] = {
    "texts": [],
    "running": False,
    "errors": [],
    "started_at": None,
    "finished_at": None,
}


def _now() -> str:
    return dt.datetime.now(TAIPEI).isoformat(timespec="seconds")


def _unique(texts: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in texts:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def snapshot() -> dict[str, Any]:
    with _lock:
        texts = list(_state["texts"])
        running = bool(_state["running"])
        errors = list(_state["errors"])
        started_at = _state["started_at"]
        finished_at = _state["finished_at"]

    items: dict[str, dict[str, Any]] = {}
    ready = 0
    for text in texts:
        audio_url = tts_voxhakka.audio_url_for(text)
        items[text] = {"ready": audio_url is not None, "audio_url": audio_url}
        if audio_url:
            ready += 1

    return {
        "items": items,
        "ready": ready,
        "total": len(texts),
        "running": running,
        "errors": errors,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def _worker(texts: list[str]) -> None:
    for text in texts:
        if tts_voxhakka.audio_url_for(text):
            continue
        try:
            tts_voxhakka.synthesize(text)
        except Exception as exc:
            with _lock:
                _state["errors"].append({"text": text, "error": str(exc)})
    with _lock:
        _state["running"] = False
        _state["finished_at"] = _now()


def start(texts: list[str]) -> dict[str, Any]:
    unique: list[str] = []
    with _lock:
        already_running = bool(_state["running"])
        if not already_running:
            unique = _unique(texts)
            _state["texts"] = unique
            _state["errors"] = []
            _state["running"] = bool(unique)
            _state["started_at"] = _now() if unique else None
            _state["finished_at"] = None

    if already_running:
        return snapshot()
    if unique:
        threading.Thread(target=_worker, args=(unique,), daemon=True).start()
    return snapshot()
