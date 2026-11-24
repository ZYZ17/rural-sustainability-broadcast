from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..providers import tts_voxhakka

TAIPEI = dt.timezone(dt.timedelta(hours=8))
MAX_JOBS = 50

_jobs: dict[str, "TtsJob"] = {}
_lock = threading.Lock()


def _now_iso() -> str:
    return dt.datetime.now(TAIPEI).isoformat(timespec="seconds")


@dataclass
class TtsJob:
    id: str
    text: str
    status: str = "queued"
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    audio_url: str | None = None
    audio_filename: str | None = None
    pinyin: str | None = None
    words: str | None = None
    cached: bool | None = None
    elapsed_seconds: float | None = None
    error: str | None = None
    unknown_words: list[str] = field(default_factory=list)
    attribution: str = tts_voxhakka.ATTRIBUTION
    license: str = tts_voxhakka.LICENSE

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "audio_url": self.audio_url,
            "audio_filename": self.audio_filename,
            "pinyin": self.pinyin,
            "words": self.words,
            "cached": self.cached,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
            "unknown_words": self.unknown_words,
            "attribution": self.attribution,
            "license": self.license,
        }


def _prune() -> None:
    if len(_jobs) <= MAX_JOBS:
        return
    removable = [job_id for job_id, job in _jobs.items() if job.status in {"done", "error"}]
    for job_id in removable[: len(_jobs) - MAX_JOBS]:
        _jobs.pop(job_id, None)


def _run(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = _now_iso()

    try:
        result = tts_voxhakka.synthesize(job.text)
    except tts_voxhakka.TtsError as exc:
        with _lock:
            job.status = "error"
            job.error = str(exc)
            job.unknown_words = exc.unknown_words
            job.finished_at = _now_iso()
        return
    except Exception as exc:
        with _lock:
            job.status = "error"
            job.error = f"語音合成失敗：{exc}"
            job.finished_at = _now_iso()
        return

    with _lock:
        job.status = "done"
        job.audio_url = f"/audio/{result.audio_filename}"
        job.audio_filename = result.audio_filename
        job.pinyin = result.pinyin
        job.words = result.words
        job.cached = result.cached
        job.elapsed_seconds = result.metadata.get("elapsed_seconds")
        job.finished_at = _now_iso()


def create_job(text: str) -> dict[str, Any]:
    job = TtsJob(id=uuid.uuid4().hex, text=text)
    with _lock:
        _jobs[job.id] = job
        _prune()
    threading.Thread(target=_run, args=(job.id,), daemon=True).start()
    return job.to_dict()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.to_dict() if job else None
