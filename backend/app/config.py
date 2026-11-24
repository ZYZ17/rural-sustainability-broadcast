from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
TTS_DIR = DATA_DIR / "tts_samples"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

CWA_API_KEY = os.getenv("CWA_API_KEY", "").strip()
CWA_BASE = os.getenv("CWA_BASE", "https://opendata.cwa.gov.tw/api/v1/rest/datastore").rstrip("/")
TARGET_COUNTY = os.getenv("TARGET_COUNTY", "臺中市")
TARGET_TOWN = os.getenv("TARGET_TOWN", "東勢區")

PRICE_TTL_SECONDS = int(os.getenv("PRICE_TTL_SECONDS", "600"))
WEATHER_TTL_SECONDS = int(os.getenv("WEATHER_TTL_SECONDS", "1800"))
CLIMATE_TTL_SECONDS = int(os.getenv("CLIMATE_TTL_SECONDS", "21600"))
CLIMATE_STATION_ID = os.getenv("CLIMATE_STATION_ID", "467490").strip()
CLIMATE_STATION_NAME = os.getenv("CLIMATE_STATION_NAME", "臺中").strip()
CLIMATE_NORMALS_DATASET = os.getenv("CLIMATE_NORMALS_DATASET", "C-B0027-001").strip()
CODIS_STATION_URL = os.getenv("CODIS_STATION_URL", "https://codis.cwa.gov.tw/api/station").rstrip("/")
LOW_TEMP_THRESHOLD = float(os.getenv("LOW_TEMP_THRESHOLD", "12"))
HEAVY_RAIN_POP_THRESHOLD = float(os.getenv("HEAVY_RAIN_POP_THRESHOLD", "70"))
PRESET_MARKET_CODES = [c.strip() for c in os.getenv("PRESET_MARKET_CODES", "423,400,420").split(",") if c.strip()]

PREFERENCES_FILE = DATA_DIR / "preferences.json"
PREF_HASH_SALT = os.getenv("PREF_HASH_SALT", "rural-broadcast-dev-salt").strip()
PREF_TRUST_PROXY = os.getenv("PREF_TRUST_PROXY", "0").strip().lower() not in {"0", "false", "no"}

TTS_ENGINE = os.getenv("TTS_ENGINE", "voxhakka_space").strip()
TTS_SPACE = os.getenv("TTS_SPACE", "united-link/taiwanese-hakka-tts").strip()
TTS_MODEL = os.getenv("TTS_MODEL", "yourtts-htia-240704").strip()
TTS_DIALECT = os.getenv("TTS_DIALECT", "dapu").strip()
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "宋涵葳").strip()
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
TTS_TIMEOUT_SECONDS = int(os.getenv("TTS_TIMEOUT_SECONDS", "900"))
TTS_CACHE_ENABLED = os.getenv("TTS_CACHE_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
