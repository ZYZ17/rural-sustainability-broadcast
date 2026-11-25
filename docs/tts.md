# 大埔腔客語 TTS

本專案的廣播語音使用 VoxHakka 的 Hugging Face Space 合成，不再使用瀏覽器內建的華語 `speechSynthesis`。

## 引擎與授權

- Space：`united-link/taiwanese-hakka-tts`
- 模型：`formospeech/yourtts-htia-240704`
- 腔調：`dapu`（大埔腔，對應 `hak_dp`）
- 預設語者：宋涵葳（東勢）
- 授權：`CC BY-NC 4.0`，僅供非商業使用
- 出處標註：VoxHakka／FormoSpeech yourtts-htia-240704（宋涵葳，東勢大埔腔）

## 設定

在 `backend/.env` 可覆寫以下變數（範例見 `backend/.env.example`）：

```dotenv
TTS_ENGINE=voxhakka_space
TTS_SPACE=united-link/taiwanese-hakka-tts
TTS_MODEL=yourtts-htia-240704
TTS_DIALECT=dapu
TTS_SPEAKER=宋涵葳
TTS_SPEED=1.15
TTS_TIMEOUT_SECONDS=900
TTS_CACHE_ENABLED=1
```

## API

### 建立合成工作

```http
POST /api/tts/jobs
Content-Type: application/json

{"text": "今晡日東勢市場，甜柿平均價一百零四元。"}
```

回應：

```json
{
  "id": "…",
  "status": "queued",
  "audio_url": null,
  "attribution": "VoxHakka／FormoSpeech yourtts-htia-240704（宋涵葳，東勢大埔腔）",
  "license": "CC BY-NC 4.0"
}
```

### 查詢工作狀態

```http
GET /api/tts/jobs/{id}
```

狀態依序為 `queued`、`running`、`done` 或 `error`。完成後 `audio_url` 為 `/audio/{hash}.wav`。

## 文字正規化

`backend/app/services/textnorm.py` 會在送出前處理：

- 阿拉伯數字轉中文數字（含小數、日期、價格、氣溫）
- `%` 轉「百分之」
- `、`、`；`、`：` 轉「，」
- 移除 `「」（）` 等 G2P 不支援的符號

若 G2P 仍回報不支援的詞彙，API 會回傳 `unknown_words`，前端會提示並提供「重新合成」。

## 快取

- 音檔與中繼資料存放於 `data/tts_samples/`
- 檔名為 `space + model + dialect + speaker + speed + text` 的 SHA-256 前 24 碼
- 相同文字會直接命中快取，不再呼叫 Space
- `TTS_CACHE_ENABLED=0` 可停用快取

## 播放節奏

- `TTS_SPEED` 在 VoxHakka 上是 `length_scale`，**數值越大越慢**；目前設為 `1.15`，讓行情播報不那麼急促。
- `backend/app/services/broadcast.py` 會在每個廣播段落之間插入三個全形逗號。G2P 會把逗號轉成獨立的停頓 token，因此「氣象→行情」「行情→行情」之間約有一秒停頓；這些逗號只進 `tts_text`，不會顯示在頁面的廣播稿上。

## 限制

- VoxHakka Space 目前跑在 CPU 上，首次合成約 30–60 秒；休眠後可能更久。
- 未經東勢大埔腔母語者校稿，`data/broadcast_templates.json` 與 `data/hakka_lexicon.json` 仍為草稿。
- 氣象摘要目前沿用氣象署的華語用詞（例如「今天」、「明天」），TTS 會以客語讀音朗讀；後續可改寫為更道地的客語說法。
- 僅供非商業使用，請保留授權與出處標註。

## 手動測試

```powershell
$env:PYTHONPATH='backend'
python -X utf8 -c "from app.providers import tts_voxhakka; r=tts_voxhakka.synthesize('今晡日東勢市場，甜柿平均價一百零四元。'); print(r.audio_path, r.pinyin, r.cached)"
```
