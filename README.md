# 鄉村永續廣播

以臺中市東勢區為主的農產品行情與氣象廣播網頁。可選擇作物與市場、調整播報項目、比較氣候基準，並使用 VoxHakka **大埔腔**合成廣播語音。

## 功能

- 作物／市場多重選擇，設定會記憶於瀏覽器本機
- 播報項目全選／全取消（上價、中價、下價、平均價、交易量、漲跌）
- 氣溫與雨量依比較基準同步切換（近 30 年／近 10 年／近 5 年／去年）
- 11 個客家人節慶祝語，依農曆自動插入，生肖使用新年生肖
- 設定內「點選發音」滑軌：先預錄 39 個作物與市場名稱，點選即播放大埔腔；取消選取不發音

## 本機啟動

需要 Python 3.11+。

```powershell
cd backend
pip install -r requirements.txt
cp .env.example .env
# 在 .env 填入你的 CWA_API_KEY
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

開啟 <http://127.0.0.1:8000/>。後端同時提供前端靜態檔案與 API，不需另外啟動 Vite。

`.env` 含 API 金鑰，已加入 `.gitignore`，不會上傳。

## 專案結構

- `backend/app/`：FastAPI 後端、氣象／行情／氣候提供者、廣播稿與 TTS 服務
- `frontend/`：單頁前端（`src/main.js`、`src/style.css`、`public/crops/`）
- `data/`：作物、市場、節慶祝語、客語詞彙等設定；快取與產生檔不進版本控制
- `scripts/`：抓取與產生資料的小工具
- `docs/tts.md`：語音合成說明

## 語音

語音由 [VoxHakka](https://huggingface.co/spaces/united-link/taiwanese-hakka-tts) 提供，設定為大埔腔、 speaker `宋涵葳`。首次合成較慢，之後會快取於 `data/tts_samples/`。
