from __future__ import annotations

import os
import sys
from pathlib import Path

import gradio as gr
import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app as backend_app  # noqa: E402


def _home(_text: str) -> str:
    return "請使用 GitHub Pages 前端，或呼叫本 Space 的 /api/* 端點。"


demo = gr.Interface(
    fn=_home,
    inputs=gr.Textbox(label="訊息"),
    outputs=gr.Textbox(label="回覆"),
    title="鄉村永續廣播 API",
    description="即時行情、氣象與大埔腔語音合成後端。",
)

app = gr.mount_gradio_app(backend_app, demo, path="/gradio")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
