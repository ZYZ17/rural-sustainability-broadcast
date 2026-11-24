from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (
    CLIMATE_TTL_SECONDS,
    CWA_API_KEY,
    DATA_DIR,
    FRONTEND_DIR,
    PRESET_MARKET_CODES,
    PRICE_TTL_SECONDS,
    TTS_DIR,
    WEATHER_TTL_SECONDS,
)
from .providers import climate_cwa, prices_moa, weather_cwa
from .services import broadcast, preferences, tts_jobs, tts_preview

app = FastAPI(title="鄉村永續廣播 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
TTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(TTS_DIR)), name="audio")

_cache: dict[str, tuple[float, dict[str, Any] | None]] = {
    "prices": (0.0, None),
    "weather": (0.0, None),
    "climate": (0.0, None),
}


class BroadcastRequest(BaseModel):
    crop_ids: list[str] = Field(default_factory=list)
    market_codes: list[str] = Field(default_factory=list)
    include_weather: bool = True
    options: list[str] | None = None


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TtsPreviewRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)


class PreferencesRequest(BaseModel):
    client_id: str | None = None
    crop_ids: list[str] = Field(default_factory=list)
    market_codes: list[str] = Field(default_factory=list)
    broadcast_options: list[str] | None = None


def _load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def get_prices_snapshot(force: bool = False) -> dict[str, Any]:
    now = time.time()
    timestamp, snapshot = _cache["prices"]
    if snapshot is not None and not force and now - timestamp < PRICE_TTL_SECONDS:
        return snapshot
    snapshot = prices_moa.load_latest_snapshot()
    if snapshot is None or force or now - timestamp >= PRICE_TTL_SECONDS:
        snapshot = prices_moa.build_snapshot()
        prices_moa.save_snapshot(snapshot)
    _cache["prices"] = (now, snapshot)
    return snapshot


def get_weather_snapshot(force: bool = False) -> dict[str, Any]:
    now = time.time()
    timestamp, snapshot = _cache["weather"]
    if snapshot is not None and not force and now - timestamp < WEATHER_TTL_SECONDS:
        return snapshot
    snapshot = weather_cwa.load_latest_snapshot()
    if snapshot is None or force or now - timestamp >= WEATHER_TTL_SECONDS:
        snapshot = weather_cwa.build_weather_snapshot()
        weather_cwa.save_snapshot(snapshot)
    _cache["weather"] = (now, snapshot)
    return snapshot


def get_climate_snapshot(force: bool = False) -> dict[str, Any]:
    now = time.time()
    timestamp, snapshot = _cache["climate"]
    if snapshot is not None and not force and now - timestamp < CLIMATE_TTL_SECONDS:
        return snapshot
    snapshot = climate_cwa.load_latest_snapshot()
    if snapshot is None or force or now - timestamp >= CLIMATE_TTL_SECONDS:
        snapshot = climate_cwa.build_climate_snapshot()
        climate_cwa.save_snapshot(snapshot)
    _cache["climate"] = (now, snapshot)
    return snapshot


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "cwa_configured": bool(CWA_API_KEY),
        "server_time": broadcast._now_iso(),
    }


@app.get("/api/preferences")
def get_preferences(request: Request, client_id: str | None = None) -> dict[str, Any]:
    return preferences.get_preferences(
        preferences.normalize_client_id(client_id),
        preferences.client_ip_hash(request),
    )


@app.post("/api/preferences")
def save_preferences(request: Request, payload: PreferencesRequest) -> dict[str, Any]:
    try:
        return preferences.save_preferences(
            preferences.normalize_client_id(payload.client_id),
            preferences.client_ip_hash(request),
            payload.crop_ids,
            payload.market_codes,
            payload.broadcast_options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    price_snapshot = get_prices_snapshot()
    weather_snapshot = get_weather_snapshot()
    climate_snapshot = get_climate_snapshot()
    crops = _load_json("crops.json")
    markets = _load_json("markets.json") if (DATA_DIR / "markets.json").exists() else price_snapshot.get("markets", [])
    for market in markets:
        market["preset"] = market.get("code") in PRESET_MARKET_CODES
    return {
        "crops": crops,
        "markets": markets,
        "preset_market_codes": PRESET_MARKET_CODES,
        "price_date": price_snapshot.get("trade_date"),
        "price_generated_at": price_snapshot.get("generated_at"),
        "market_count": len(markets),
        "weather": weather_snapshot,
        "climate": climate_snapshot,
        "server_time": broadcast._now_iso(),
    }


@app.get("/api/prices")
def prices(markets: str = "", crops: str = "") -> dict[str, Any]:
    market_codes = [code for code in markets.split(",") if code]
    crop_ids = [crop for crop in crops.split(",") if crop]
    snapshot = get_prices_snapshot()
    return {
        "trade_date": snapshot.get("trade_date"),
        "generated_at": snapshot.get("generated_at"),
        "prices": prices_moa.get_prices_for(crop_ids or None, market_codes or None, snapshot),
    }


@app.get("/api/weather")
def weather(force: bool = False) -> dict[str, Any]:
    return get_weather_snapshot(force=force)


@app.get("/api/climate")
def climate(force: bool = False) -> dict[str, Any]:
    return get_climate_snapshot(force=force)


@app.get("/api/climate/baselines")
def climate_baselines(force: bool = False) -> dict[str, Any]:
    return climate_cwa.get_baseline_snapshot(force=force)


@app.post("/api/broadcast")
def create_broadcast(request: BroadcastRequest) -> dict[str, Any]:
    return broadcast.build_broadcast(
        crop_ids=request.crop_ids,
        market_codes=request.market_codes,
        include_weather=request.include_weather,
        options=request.options,
    )


@app.post("/api/tts/jobs")
def create_tts_job(request: TtsRequest) -> dict[str, Any]:
    return tts_jobs.create_job(request.text)


@app.get("/api/tts/jobs/{job_id}")
def get_tts_job(job_id: str) -> dict[str, Any]:
    job = tts_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="TTS job not found")
    return job


@app.post("/api/tts/preview")
def create_tts_preview(request: TtsPreviewRequest) -> dict[str, Any]:
    return tts_preview.start(request.texts)


@app.get("/api/tts/preview")
def get_tts_preview() -> dict[str, Any]:
    return tts_preview.snapshot()


@app.post("/api/refresh")
def refresh() -> dict[str, Any]:
    price_snapshot = get_prices_snapshot(force=True)
    weather_snapshot = get_weather_snapshot(force=True)
    climate_snapshot = get_climate_snapshot(force=True)
    return {
        "price_date": price_snapshot.get("trade_date"),
        "price_generated_at": price_snapshot.get("generated_at"),
        "weather_generated_at": weather_snapshot.get("generated_at"),
        "weather_errors": weather_snapshot.get("errors") or [],
        "climate_generated_at": climate_snapshot.get("generated_at"),
        "climate_errors": climate_snapshot.get("errors") or [],
    }


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__API_BASE__", "")
    return HTMLResponse(html)


app.mount("/src", StaticFiles(directory=str(FRONTEND_DIR / "src")), name="frontend-src")
app.mount(
    "/crops",
    StaticFiles(directory=str(FRONTEND_DIR / "public" / "crops")),
    name="crop-images",
)
