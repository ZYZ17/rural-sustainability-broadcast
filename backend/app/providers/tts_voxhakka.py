from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import (
    TTS_CACHE_ENABLED,
    TTS_DIALECT,
    TTS_DIR,
    TTS_MODEL,
    TTS_SPACE,
    TTS_SPEAKER,
    TTS_SPEED,
    TTS_TIMEOUT_SECONDS,
)
from ..services.textnorm import normalize_tts_text

ATTRIBUTION = "VoxHakka／FormoSpeech yourtts-htia-240704（宋涵葳，東勢大埔腔）"
LICENSE = "CC BY-NC 4.0"

_client: Any = None
_client_lock = threading.Lock()
_synthesis_lock = threading.Lock()


class TtsError(RuntimeError):
    def __init__(self, message: str, unknown_words: list[str] | None = None) -> None:
        super().__init__(message)
        self.unknown_words = unknown_words or []


class TtsTimeoutError(TtsError):
    pass


@dataclass
class TtsResult:
    audio_path: Path
    audio_filename: str
    text: str
    words: str
    pinyin: str
    cached: bool
    metadata: dict[str, Any]


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def _cache_key(text: str) -> str:
    material = "|".join(
        [
            TTS_SPACE,
            TTS_MODEL,
            TTS_DIALECT,
            TTS_SPEAKER,
            f"{TTS_SPEED:.3f}",
            text,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def audio_url_for(text: str) -> str | None:
    normalized = normalize_tts_text(text)
    if not normalized:
        return None
    audio_path = TTS_DIR / f"{_cache_key(normalized)}.wav"
    return f"/audio/{audio_path.name}" if audio_path.exists() else None


def _get_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            try:
                from gradio_client import Client
            except ImportError as exc:
                raise TtsError("缺少 gradio_client，請先安裝 backend/requirements.txt") from exc
            try:
                _client = Client(TTS_SPACE, verbose=False)
            except Exception as exc:
                raise TtsError(f"無法連線 VoxHakka Space：{exc}") from exc
        return _client


def _unknown_words(message: str) -> list[str]:
    match = re.search(r"\[(.*?)\]", message)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _call_space(text: str) -> tuple[str, str, str]:
    try:
        from gradio_client.exceptions import AppError
    except ImportError as exc:
        raise TtsError("缺少 gradio_client，請先安裝 backend/requirements.txt") from exc

    client = _get_client()
    try:
        job = client.submit(
            TTS_MODEL,
            "預設語者",
            None,
            TTS_SPEAKER,
            TTS_DIALECT,
            TTS_SPEED,
            text,
            api_name="/text_to_speech",
        )
        result = job.result(timeout=TTS_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise TtsTimeoutError(
            f"語音合成逾時（{TTS_TIMEOUT_SECONDS} 秒），VoxHakka Space 可能忙碌或休眠中，請稍後重試。"
        ) from exc
    except AppError as exc:
        message = str(exc)
        if "無法轉成 ipa" in message:
            words = _unknown_words(message)
            detail = "、".join(words) if words else "部分詞彙"
            raise TtsError(f"客語轉音失敗，尚未支援：{detail}", unknown_words=words) from exc
        raise TtsError(f"VoxHakka 合成失敗：{message}") from exc

    if not isinstance(result, (tuple, list)) or len(result) < 3:
        raise TtsError(f"VoxHakka 回傳格式異常：{result!r}")
    return str(result[0]), str(result[1]), str(result[2])


def _call_with_retry(text: str) -> tuple[str, str, str]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return _call_space(text)
        except TtsError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise TtsError(f"VoxHakka 連線失敗：{last_error}")


def synthesize(text: str) -> TtsResult:
    normalized = normalize_tts_text(text)
    if not normalized:
        raise TtsError("語音文字為空。")

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(normalized)
    audio_path = TTS_DIR / f"{key}.wav"
    metadata_path = TTS_DIR / f"{key}.json"

    if TTS_CACHE_ENABLED and audio_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return TtsResult(
            audio_path=audio_path,
            audio_filename=audio_path.name,
            text=metadata.get("text", normalized),
            words=metadata.get("words", ""),
            pinyin=metadata.get("pinyin", ""),
            cached=True,
            metadata=metadata,
        )

    started = time.time()
    with _synthesis_lock:
        if TTS_CACHE_ENABLED and audio_path.exists() and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return TtsResult(
                audio_path=audio_path,
                audio_filename=audio_path.name,
                text=metadata.get("text", normalized),
                words=metadata.get("words", ""),
                pinyin=metadata.get("pinyin", ""),
                cached=True,
                metadata=metadata,
            )

        words, pinyin, generated_path = _call_with_retry(normalized)
        if not Path(generated_path).exists():
            raise TtsError("VoxHakka 未回傳音檔。")
        shutil.copyfile(generated_path, audio_path)

    metadata = {
        "id": key,
        "engine": "voxhakka_space",
        "space": TTS_SPACE,
        "model": TTS_MODEL,
        "dialect": TTS_DIALECT,
        "dialect_label": "大埔腔",
        "speaker": TTS_SPEAKER,
        "speed": TTS_SPEED,
        "text": normalized,
        "words": words,
        "pinyin": pinyin,
        "audio_filename": audio_path.name,
        "created_at": _now_iso(),
        "elapsed_seconds": round(time.time() - started, 1),
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "commercial_use": False,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return TtsResult(
        audio_path=audio_path,
        audio_filename=audio_path.name,
        text=normalized,
        words=words,
        pinyin=pinyin,
        cached=False,
        metadata=metadata,
    )
