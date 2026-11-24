from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi, get_token

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ID = os.getenv("HF_SPACE_ID", "CYC1245556/rural-sustainability-broadcast-api")
SPACE_URL = f"https://huggingface.co/spaces/{REPO_ID}"
API_URL = f"https://cyc1245556-rural-sustainability-broadcast-api.hf.space"


def load_cwa_key() -> str:
    env_key = os.getenv("CWA_API_KEY", "").strip()
    if env_key:
        return env_key
    values = dotenv_values(PROJECT_ROOT / "backend" / ".env")
    return str(values.get("CWA_API_KEY") or "").strip()


def copy_tree(src: Path, dst: Path, include: set[str] | None = None) -> None:
    if not dst.exists():
        dst.mkdir(parents=True)
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        if "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        if include is not None and item.name not in include:
            continue
        relative = item.relative_to(src)
        target = dst / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def build_context() -> Path:
    temp = Path(tempfile.mkdtemp(prefix="rural-broadcast-hf-space-"))
    space_files = PROJECT_ROOT / "hf_space"
    shutil.copy2(space_files / "README.md", temp / "README.md")
    shutil.copy2(space_files / "app.py", temp / "app.py")
    shutil.copy2(space_files / "requirements.txt", temp / "requirements.txt")

    copy_tree(PROJECT_ROOT / "backend" / "app", temp / "backend" / "app")
    copy_tree(PROJECT_ROOT / "data", temp / "data", include={
        "broadcast_templates.json",
        "crops.json",
        "festival_greetings.json",
        "hakka_lexicon.json",
        "markets.json",
    })
    copy_tree(PROJECT_ROOT / "frontend" / "src", temp / "frontend" / "src")
    copy_tree(PROJECT_ROOT / "frontend" / "public" / "crops", temp / "frontend" / "public" / "crops")
    shutil.copy2(PROJECT_ROOT / "frontend" / "index.html", temp / "frontend" / "index.html")
    return temp


def main() -> None:
    api = HfApi()
    token = os.getenv("HF_TOKEN") or get_token() or api.token
    if not token:
        raise SystemExit("請先執行 `hf auth login`，或設定 HF_TOKEN 環境變數。")

    cwa_key = load_cwa_key()
    if not cwa_key:
        raise SystemExit("找不到 CWA_API_KEY，請確認 backend/.env。")

    pref_salt = hashlib.sha256(f"rural-broadcast-hf:{cwa_key}".encode("utf-8")).hexdigest()[:32]

    print(f"建立或更新 Space：{SPACE_URL}")
    api.create_repo(
        repo_id=REPO_ID,
        repo_type="space",
        space_sdk="gradio",
        space_hardware="cpu-basic",
        private=False,
        exist_ok=True,
        token=token,
    )
    api.add_space_secret(REPO_ID, "CWA_API_KEY", cwa_key, token=token)
    api.add_space_secret(REPO_ID, "PREF_HASH_SALT", pref_salt, token=token)
    api.add_space_variable(REPO_ID, "PREF_TRUST_PROXY", "1", token=token)

    context = build_context()
    try:
        print("上傳 Space 檔案…")
        api.upload_folder(
            repo_id=REPO_ID,
            repo_type="space",
            folder_path=context,
            commit_message="部署即時行情、氣象與大埔腔語音後端",
            token=token,
        )
    finally:
        shutil.rmtree(context, ignore_errors=True)

    print(f"完成：{SPACE_URL}")
    print(f"API：{API_URL}")
    print("若首頁還沒更新，請在 GitHub 設定 repo variable：API_BASE = " + API_URL)


if __name__ == "__main__":
    main()
