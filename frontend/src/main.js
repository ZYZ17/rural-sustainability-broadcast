const CLIMATE_BASELINE_OPTIONS = [
  { key: 'last30', label: '近30年' },
  { key: 'last10', label: '近10年' },
  { key: 'last5', label: '近5年' },
  { key: 'last_year', label: '去年' },
];
const CLIMATE_BASELINE_KEY = 'climate_baseline';
const PREVIEW_SPEECH_KEY = 'broadcast_preview_speech';
const STATIC_SITE = window.location.hostname.endsWith('github.io') || new URLSearchParams(window.location.search).has('static');
let API_BASE = (document.querySelector('meta[name="api-base"]')?.content || '').replace(/\/$/, '');
let USE_REMOTE = Boolean(API_BASE);
let DEMO_SITE = STATIC_SITE && !USE_REMOTE;
const APP_BASE = new URL('.', window.location.href).pathname;
const WAITING_MUSIC_PATH = '/music/dagpu-moonlight.mp3';
const WAITING_MUSIC_VOLUME = 0.55;
const MUSIC_FADE_IN_MS = 2500;
const MUSIC_FADE_OUT_MS = 5000;
const VOICE_FADE_IN_MS = 1200;

function applyApiBase(value) {
  API_BASE = String(value || '').replace(/\/$/, '');
  USE_REMOTE = Boolean(API_BASE);
  DEMO_SITE = STATIC_SITE && !USE_REMOTE;
}

async function loadRuntimeConfig() {
  try {
    const response = await fetch(`${staticAsset('data/api_config.json')}?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return;
    const config = await response.json();
    if (config?.api_base) applyApiBase(config.api_base);
  } catch (_) {
    // 沒有設定檔時沿用 HTML 的 meta 值。
  }
}

function staticAsset(path) {
  return new URL(path, new URL(APP_BASE, window.location.href)).href;
}

function apiUrl(path) {
  return USE_REMOTE ? `${API_BASE}${path}` : path;
}

function mediaUrl(url) {
  if (!url) return url;
  if (/^https?:\/\//.test(url)) return url;
  if (USE_REMOTE) return `${API_BASE}${url.startsWith('/') ? '' : '/'}${url}`;
  if (STATIC_SITE) return staticAsset(String(url).replace(/^\//, ''));
  return url;
}

function readClimateBaseline() {
  try {
    const key = localStorage.getItem(CLIMATE_BASELINE_KEY);
    return CLIMATE_BASELINE_OPTIONS.some((option) => option.key === key) ? key : CLIMATE_BASELINE_OPTIONS[0].key;
  } catch (_) {
    return CLIMATE_BASELINE_OPTIONS[0].key;
  }
}

function readPreviewSpeech() {
  try {
    return localStorage.getItem(PREVIEW_SPEECH_KEY) === '1';
  } catch (_) {
    return false;
  }
}

function writePreviewSpeech(enabled) {
  try {
    localStorage.setItem(PREVIEW_SPEECH_KEY, enabled ? '1' : '0');
  } catch (_) {}
}

const state = {
  crops: [],
  markets: [],
  presetCodes: [],
  selectedCrops: new Set(),
  selectedMarkets: new Set(),
  broadcastOptions: [],
  clientId: null,
  prefs: null,
  firstVisit: false,
  settingsMode: null,
  settingsDraft: null,
  settingsError: '',
  focusBeforeModal: null,
  weather: null,
  climate: null,
  climateBaseline: readClimateBaseline(),
  climateBaselineData: null,
  priceDate: null,
  marketSearch: '',
  broadcast: null,
  speaking: false,
  loading: false,
  notice: null,
  audio: null,
  music: null,
  musicPausedForVoice: false,
  userPaused: false,
  transitioning: false,
  voiceStarting: false,
  ttsJob: null,
  ttsTimer: null,
  ttsClock: null,
  previewSpeech: readPreviewSpeech(),
  previewSounds: {},
  previewExpected: 0,
  previewProgress: { ready: 0, total: 0, running: false },
  previewAudio: null,
  previewSeq: 0,
  previewPollTimer: null,
};

const LOCAL_PREFS_KEY = 'broadcast_preferences';
const LOCAL_CLIENT_KEY = 'broadcast_client_id';
const LOCAL_SETUP_KEY = 'broadcast_setup_complete';
const BROADCAST_OPTIONS = [
  { key: 'upper', label: '上價' },
  { key: 'middle', label: '中價' },
  { key: 'lower', label: '下價' },
  { key: 'avg', label: '平均價' },
  { key: 'volume', label: '交易量' },
  { key: 'trend', label: '漲跌' },
];
const DEFAULT_BROADCAST_OPTIONS = BROADCAST_OPTIONS.map((option) => option.key);
const app = document.querySelector('#app');

function normalizeBroadcastOptions(value) {
  if (!Array.isArray(value)) return [...DEFAULT_BROADCAST_OPTIONS];
  const valid = new Set(DEFAULT_BROADCAST_OPTIONS);
  return [...new Set(value.filter((item) => valid.has(item)))];
}

function getOrCreateClientId() {
  let id = null;
  try {
    id = localStorage.getItem(LOCAL_CLIENT_KEY);
  } catch (_) {
    id = null;
  }
  if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    id = globalThis.crypto?.randomUUID?.() || `b${Date.now()}${Math.random().toString(36).slice(2)}`;
    try {
      localStorage.setItem(LOCAL_CLIENT_KEY, id);
    } catch (_) {}
  }
  return id;
}

function readLocalPreferences() {
  try {
    const raw = localStorage.getItem(LOCAL_PREFS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function writeLocalPreferences(cropIds, marketCodes, options) {
  try {
    localStorage.setItem(LOCAL_PREFS_KEY, JSON.stringify({
      crop_ids: cropIds,
      market_codes: marketCodes,
      broadcast_options: options,
    }));
    localStorage.setItem(LOCAL_SETUP_KEY, '1');
  } catch (_) {}
}

function hasLocalSetup() {
  const local = readLocalPreferences();
  return Boolean(local?.crop_ids?.length && local?.market_codes?.length);
}

function isSetupComplete() {
  try {
    return localStorage.getItem(LOCAL_SETUP_KEY) === '1';
  } catch (_) {
    return false;
  }
}

function currentSelection() {
  if (!state.settingsDraft) {
    state.settingsDraft = {
      crops: new Set(state.selectedCrops),
      markets: new Set(state.selectedMarkets),
      options: new Set(state.broadcastOptions),
    };
  }
  return state.settingsDraft;
}

function clearSettingsError() {
  if (!state.settingsError) return;
  state.settingsError = '';
  renderSettingsError();
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatDate(iso) {
  if (!iso) return '';
  const [, month, day] = iso.split('-');
  return `${Number(month)}月${Number(day)}日`;
}

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '';
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  const text = number.toFixed(2).replace(/\.?0+$/, '');
  return text === '-0' ? '0' : text;
}

function currentMonth() {
  return new Date().getMonth() + 1;
}

function seasonBadge(crop) {
  const inSeason = (crop.season_months || []).includes(currentMonth());
  return `<span class="badge ${inSeason ? 'badge-season' : 'badge-off'}">${inSeason ? '產季' : '非產季'}</span>`;
}

function alertLabel(kind) {
  return ({
    typhoon: '颱風',
    low_temp: '低溫',
    heavy_rain: '豪雨',
    strong_wind: '強風',
    other: '提醒',
  })[kind] || '提醒';
}

function renderShell() {
  app.innerHTML = `
    <header class="hero">
      <div class="hero-inner">
        <p class="eyebrow">臺中東勢・客語大埔腔</p>
        <h1>大埔好聲</h1>
        <p class="hero-sub">天氣與行情報你知，按一下喇叭就用客語播放。</p>
      </div>
    </header>
    <main class="layout">
      <section id="notice"></section>
      <section id="status" class="status-panel"></section>
      <section id="weather"></section>
      <section id="climate-chart"></section>
      <section class="panel">
        <div class="panel-head">
          <h2>廣播稿</h2>
          <button type="button" class="text-button" id="refresh-button">重新抓資料</button>
        </div>
        <div id="script" class="script"></div>
        <div id="raw-details" class="raw-details"></div>
        <div id="tts-status" class="tts-status"></div>
      </section>
    </main>
    <div class="action-bar">
      <div class="action-summary" id="action-summary"></div>
      <div class="action-controls">
      <button type="button" class="replay-button" id="replay-button" aria-label="重播廣播內容" hidden>
        <svg class="replay-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5V1L7 6l5 5V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z"/>
        </svg>
        <span>重播廣播</span>
      </button>
      <button type="button" class="play-button" id="play-button" aria-label="播放廣播" aria-pressed="false">
        <svg class="play-icon icon-play" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 9v6h4l5 4V5L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4.03v8.06A4.5 4.5 0 0 0 16.5 12zM14 3.23v2.06a7 7 0 0 1 0 13.42v2.06a9 9 0 0 0 0-17.54z"/>
        </svg>
        <svg class="play-icon icon-pause" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 5h4v14H6zM14 5h4v14h-4z"/>
        </svg>
        <span id="play-label">播放廣播</span>
      </button>
      </div>
    </div>
    <button type="button" class="settings-fab" id="settings-fab" aria-label="開啟設定">
      <svg class="settings-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M19.4 13a7.8 7.8 0 0 0 .06-1 7.8 7.8 0 0 0-.06-1l2.1-1.65a.5.5 0 0 0 .12-.64l-2-3.46a.5.5 0 0 0-.61-.22l-2.48 1a7.6 7.6 0 0 0-1.73-1l-.37-2.64a.5.5 0 0 0-.5-.43h-4a.5.5 0 0 0-.5.43l-.37 2.64a7.6 7.6 0 0 0-1.73 1l-2.48-1a.5.5 0 0 0-.61.22l-2 3.46a.5.5 0 0 0 .12.64L4.6 11a7.8 7.8 0 0 0 0 2l-2.1 1.65a.5.5 0 0 0-.12.64l2 3.46a.5.5 0 0 0 .61.22l2.48-1a7.6 7.6 0 0 0 1.73 1l.37 2.64a.5.5 0 0 0 .5.43h4a.5.5 0 0 0 .5-.43l.37-2.64a7.6 7.6 0 0 0 1.73-1l2.48 1a.5.5 0 0 0 .61-.22l2-3.46a.5.5 0 0 0-.12-.64L19.4 13zM12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/>
      </svg>
      <span>設定</span>
    </button>
    <div class="settings-overlay" id="settings-overlay" hidden>
      <div class="settings-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header class="settings-head">
          <div>
            <p class="settings-eyebrow">個人化廣播</p>
            <h2 id="settings-title" tabindex="-1">選擇作物與市場</h2>
          </div>
          <button type="button" class="settings-close" id="settings-cancel" aria-label="關閉設定">×</button>
        </header>
        <div class="settings-body">
          <div class="sound-panel">
            <label class="sound-switch">
              <input type="checkbox" id="preview-speech-toggle" ${state.previewSpeech ? 'checked' : ''} />
              <span class="sound-switch-track"><span class="sound-switch-knob" id="preview-speech-icon">${state.previewSpeech ? '🔊' : '🔇'}</span></span>
              <span class="sound-switch-copy">
                <strong>點選發音</strong>
                <small id="preview-progress">語音準備中…</small>
              </span>
            </label>
          </div>
          <p class="settings-intro" id="settings-intro"></p>
          <section class="panel">
            <div class="panel-head">
              <h3>作物</h3>
              <div class="panel-actions">
                <button type="button" class="text-button" id="select-all-crops">全選</button>
                <button type="button" class="text-button" id="clear-crops">清除</button>
              </div>
            </div>
            <p class="hint">非產季的作物仍會列出，若今日沒有行情會如實告知。</p>
            <div id="crop-grid" class="crop-grid"></div>
          </section>
          <section class="panel">
            <div class="panel-head">
              <h3>市場</h3>
              <div class="panel-actions">
                <button type="button" class="text-button" id="select-preset-markets">東勢／臺中／豐原</button>
                <button type="button" class="text-button" id="clear-markets">清除</button>
              </div>
            </div>
            <div class="market-tools">
              <input id="market-search" type="search" placeholder="搜尋市場名稱" autocomplete="off" aria-label="搜尋市場" />
              <span id="market-count" class="hint"></span>
            </div>
            <div id="market-grid" class="market-grid"></div>
          </section>
          <section class="panel">
            <div class="panel-head">
              <h3>播報內容</h3>
              <div class="panel-actions">
                <button type="button" class="text-button" id="select-price-fields" title="全選或取消所有播報項目">全選</button>
              </div>
            </div>
            <p class="hint">節氣、農曆與天氣固定播報；其餘項目可自行勾選。</p>
            <div class="fixed-options">
              <span class="fixed-badge">節氣（當日）</span>
              <span class="fixed-badge">農曆日期</span>
              <span class="fixed-badge">天氣</span>
            </div>
            <div id="broadcast-options" class="option-grid"></div>
          </section>
        </div>
        <footer class="settings-foot">
          <p class="settings-error" id="settings-error" hidden></p>
          <button type="button" class="settings-save" id="settings-save">開始使用</button>
        </footer>
      </div>
    </div>
  `;
  bindEvents();
}

function bindEvents() {
  document.querySelector('#crop-grid').addEventListener('click', (event) => {
    const card = event.target.closest('[data-crop-id]');
    if (!card) return;
    const wasSelected = currentSelection().crops.has(card.dataset.cropId);
    toggleCrop(card.dataset.cropId);
    if (wasSelected) return;
    const crop = state.crops.find((item) => item.id === card.dataset.cropId);
    if (crop) playPreviewSound(crop.name_hakka || crop.name_zh);
  });
  document.querySelector('#market-grid').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-market-code]');
    if (!chip) return;
    const wasSelected = currentSelection().markets.has(chip.dataset.marketCode);
    toggleMarket(chip.dataset.marketCode);
    if (wasSelected) return;
    const market = state.markets.find((item) => item.code === chip.dataset.marketCode);
    if (market) playPreviewSound(market.name);
  });
  document.querySelector('#market-search').addEventListener('input', (event) => {
    state.marketSearch = event.target.value;
    renderMarkets();
  });
  document.querySelector('#select-all-crops').addEventListener('click', () => {
    const draft = currentSelection();
    state.crops.forEach((crop) => draft.crops.add(crop.id));
    clearSettingsError();
    renderCrops();
  });
  document.querySelector('#clear-crops').addEventListener('click', () => {
    currentSelection().crops.clear();
    clearSettingsError();
    renderCrops();
  });
  document.querySelector('#select-preset-markets').addEventListener('click', () => {
    const draft = currentSelection();
    draft.markets = new Set(state.presetCodes);
    state.settingsDraft = draft;
    clearSettingsError();
    renderMarkets();
  });
  document.querySelector('#clear-markets').addEventListener('click', () => {
    currentSelection().markets.clear();
    clearSettingsError();
    renderMarkets();
  });
  document.querySelector('#broadcast-options').addEventListener('change', (event) => {
    const box = event.target.closest('[data-option-key]');
    if (box) toggleBroadcastOption(box.dataset.optionKey, box.checked);
  });
  document.querySelector('#select-price-fields').addEventListener('click', selectPriceFields);
  document.querySelector('#preview-speech-toggle').addEventListener('change', (event) => {
    state.previewSpeech = event.target.checked;
    writePreviewSpeech(state.previewSpeech);
    const icon = document.querySelector('#preview-speech-icon');
    if (icon) icon.textContent = state.previewSpeech ? '🔊' : '🔇';
    if (!state.previewSpeech) stopPreview();
  });
  document.querySelector('#play-button').addEventListener('click', togglePlayback);
  document.querySelector('#replay-button').addEventListener('click', replayBroadcastOnly);
  document.querySelector('#refresh-button').addEventListener('click', refreshData);
  document.querySelector('#settings-fab').addEventListener('click', () => openSettings('edit'));
  document.querySelector('#settings-cancel').addEventListener('click', () => closeSettings());
  document.querySelector('#settings-save').addEventListener('click', saveSettings);
  document.querySelector('#settings-overlay').addEventListener('click', (event) => {
    if (event.target.id === 'settings-overlay') closeSettings();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.settingsMode === 'edit') closeSettings();
  });
}

function renderSettingsError() {
  const box = document.querySelector('#settings-error');
  if (!box) return;
  box.textContent = state.settingsError || '';
  box.hidden = !state.settingsError;
}

function openSettings(mode) {
  state.settingsMode = mode;
  state.settingsDraft = {
    crops: new Set(state.selectedCrops),
    markets: new Set(state.selectedMarkets),
    options: new Set(state.broadcastOptions),
  };
  state.settingsError = '';
  state.focusBeforeModal = document.activeElement;
  const overlay = document.querySelector('#settings-overlay');
  const title = document.querySelector('#settings-title');
  const intro = document.querySelector('#settings-intro');
  const cancel = document.querySelector('#settings-cancel');
  const save = document.querySelector('#settings-save');
  title.textContent = mode === 'first' ? '歡迎使用，先完成廣播設定' : '設定作物、市場與播報內容';
  intro.textContent = mode === 'first'
    ? '第一次使用請至少選擇一種作物與一個市場，按「開始使用」後即可進入首頁。'
    : '在這裡調整廣播內容；按「儲存設定」後才會生效，取消則保留原有設定。';
  cancel.hidden = mode === 'first';
  save.textContent = mode === 'first' ? '開始使用' : '儲存設定';
  overlay.hidden = false;
  document.body.classList.add('settings-open');
  renderCrops();
  renderMarkets();
  renderBroadcastOptions();
  renderSettingsError();
  title.focus();
}

function closeSettings(force = false) {
  if (state.settingsMode === 'first' && !force) return;
  state.settingsMode = null;
  state.settingsDraft = null;
  state.settingsError = '';
  document.querySelector('#settings-overlay').hidden = true;
  document.body.classList.remove('settings-open');
  renderCrops();
  renderMarkets();
  renderBroadcastOptions();
  if (state.focusBeforeModal?.isConnected) state.focusBeforeModal.focus();
  state.focusBeforeModal = null;
}

async function saveSettings() {
  const draft = currentSelection();
  if (!draft.crops.size || !draft.markets.size) {
    state.settingsError = '請至少選擇一種作物與一個市場。';
    renderSettingsError();
    return;
  }
  if (DEMO_SITE) {
    state.prefs = { configured: true, crop_ids: [...draft.crops], market_codes: [...draft.markets], broadcast_options: [...draft.options], source: 'local' };
    state.firstVisit = false;
    state.selectedCrops = new Set(draft.crops);
    state.selectedMarkets = new Set(draft.markets);
    state.broadcastOptions = normalizeBroadcastOptions([...draft.options]);
    writeLocalPreferences([...state.selectedCrops], [...state.selectedMarkets], [...state.broadcastOptions]);
    state.broadcast = null;
    resetTts();
    closeSettings(true);
    renderStatus();
    renderScript();
    renderActionBar();
    setNotice('設定已儲存（展示版）。', 'info');
    return;
  }
  const save = document.querySelector('#settings-save');
  const originalText = save.textContent;
  save.disabled = true;
  save.textContent = '儲存中…';
  try {
    const response = await fetch(apiUrl('/api/preferences'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: state.clientId,
        crop_ids: [...draft.crops],
        market_codes: [...draft.markets],
        broadcast_options: [...draft.options],
      }),
    });
    if (!response.ok) throw new Error('無法儲存設定，請再試一次。');
    const prefs = await response.json();
    state.prefs = prefs;
    state.firstVisit = false;
    state.selectedCrops = new Set(prefs.crop_ids || []);
    state.selectedMarkets = new Set(prefs.market_codes || []);
    state.broadcastOptions = normalizeBroadcastOptions(prefs.broadcast_options);
    writeLocalPreferences([...state.selectedCrops], [...state.selectedMarkets], [...state.broadcastOptions]);
    state.broadcast = null;
    resetTts();
    closeSettings(true);
    renderStatus();
    renderScript();
    renderActionBar();
    setNotice('設定已儲存。', 'info');
  } catch (error) {
    state.settingsError = error.message;
    renderSettingsError();
  } finally {
    save.disabled = false;
    save.textContent = originalText;
  }
}

function toggleCrop(id) {
  const draft = currentSelection();
  if (draft.crops.has(id)) draft.crops.delete(id);
  else draft.crops.add(id);
  clearSettingsError();
  renderCrops();
}

function toggleMarket(code) {
  const draft = currentSelection();
  if (draft.markets.has(code)) draft.markets.delete(code);
  else draft.markets.add(code);
  clearSettingsError();
  renderMarkets();
}

function toggleBroadcastOption(key, checked) {
  const draft = currentSelection();
  if (checked) draft.options.add(key);
  else draft.options.delete(key);
  clearSettingsError();
  renderBroadcastOptions();
}

function selectPriceFields() {
  const draft = currentSelection();
  const allSelected = BROADCAST_OPTIONS.every((option) => draft.options.has(option.key));
  BROADCAST_OPTIONS.forEach((option) => {
    if (allSelected) draft.options.delete(option.key);
    else draft.options.add(option.key);
  });
  clearSettingsError();
  renderBroadcastOptions();
}

function renderBroadcastOptions() {
  const container = document.querySelector('#broadcast-options');
  if (!container) return;
  const selected = state.settingsDraft?.options || new Set(state.broadcastOptions);
  container.innerHTML = BROADCAST_OPTIONS.map((option) => `
    <label class="option-item">
      <input type="checkbox" data-option-key="${option.key}" ${selected.has(option.key) ? 'checked' : ''} />
      <span>${escapeHtml(option.label)}</span>
    </label>
  `).join('');
}

function renderCrops() {
  const grid = document.querySelector('#crop-grid');
  if (!grid) return;
  const selectedCrops = state.settingsDraft?.crops || state.selectedCrops;
  grid.innerHTML = state.crops.map((crop) => {
    const selected = selectedCrops.has(crop.id);
    return `
      <button type="button" class="crop-card ${selected ? 'is-selected' : ''}" data-crop-id="${escapeHtml(crop.id)}" aria-pressed="${selected}">
        <span class="crop-check" aria-hidden="true">${selected ? '✓' : ''}</span>
        <img src="${escapeHtml(mediaUrl(crop.image))}" alt="${escapeHtml(crop.name_zh)}" loading="lazy" />
        <span class="crop-name">${escapeHtml(crop.name_zh)}</span>
        <span class="crop-hakka">${escapeHtml(crop.name_hakka || '')}</span>
        <span class="crop-meta">${escapeHtml(crop.category || '')} ${seasonBadge(crop)}</span>
      </button>
    `;
  }).join('');
}

function renderMarkets() {
  const grid = document.querySelector('#market-grid');
  if (!grid) return;
  const keyword = state.marketSearch.trim();
  const selectedMarkets = state.settingsDraft?.markets || state.selectedMarkets;
  const markets = state.markets.filter((market) => (
    !keyword || market.name.includes(keyword) || market.code.includes(keyword)
  ));
  grid.innerHTML = markets.map((market) => {
    const selected = selectedMarkets.has(market.code);
    return `
      <button type="button" class="market-chip ${selected ? 'is-selected' : ''}" data-market-code="${escapeHtml(market.code)}" aria-pressed="${selected}">
        <span class="market-name">${escapeHtml(market.name)}</span>
        <span class="market-code">${escapeHtml(market.code)}${market.preset ? '・常用' : ''}</span>
      </button>
    `;
  }).join('') || '<p class="hint">找不到符合的市場。</p>';
  const count = document.querySelector('#market-count');
  if (count) count.textContent = `顯示 ${markets.length} / ${state.markets.length} 個市場`;
}

function renderStatus() {
  const status = document.querySelector('#status');
  if (!status) return;
  const weather = state.weather || {};
  const alerts = weather.alerts || [];
  const alertText = alerts.length ? `氣象提醒 ${alerts.length} 則` : '目前無重大氣象警報';
  status.innerHTML = `
    <div class="status-item">
      <span class="status-label">行情日期</span>
      <strong>${escapeHtml(formatDate(state.priceDate) || '尚未取得')}</strong>
    </div>
    <div class="status-item">
      <span class="status-label">氣象</span>
      <strong>${escapeHtml(alertText)}</strong>
    </div>
    <div class="status-item">
      <span class="status-label">已選</span>
      <strong>${state.selectedCrops.size} 作物・${state.selectedMarkets.size} 市場</strong>
    </div>
  `;
}

function renderWeather() {
  const container = document.querySelector('#weather');
  if (!container) return;
  const weather = state.weather || {};
  const alerts = weather.alerts || [];
  const summary = weather.summary || '';
  if (!alerts.length && !summary) {
    container.innerHTML = '';
    return;
  }
  const alertHtml = alerts.length
    ? `<div class="alert-banner">${alerts.map((alert) => `<p><strong>${escapeHtml(alertLabel(alert.kind))}</strong>${escapeHtml(alert.text)}</p>`).join('')}</div>`
    : '';
  container.innerHTML = `
    ${alertHtml}
    <div class="weather-card">
      <span class="weather-label">東勢天氣</span>
      <p>${escapeHtml(summary)}</p>
    </div>
  `;
}

function climateValue(value, unit = '') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return `${formatNumber(value)}${unit}`;
}

function climateDelta(value, unit = '') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '';
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${formatNumber(number)}${unit}`;
}

function climateLineSvg(title, unit, series, valueKey, colors, labels, options = {}) {
  const { yMin = null, yMax = null, showValues = false } = options;
  const width = 480;
  const height = 220;
  const left = 46;
  const right = 14;
  const top = 28;
  const bottom = 42;
  const baseline = height - bottom;
  const plotHeight = baseline - top;
  const plotWidth = width - left - right;
  const makePoints = (side) => series.map((entry, index) => {
    const raw = (entry[side] || {})[valueKey];
    const value = Number(raw);
    const valid = raw !== null && raw !== undefined && raw !== '' && Number.isFinite(value) && value > -100;
    return {
      month: entry.month,
      value: valid ? value : null,
      x: left + (index / Math.max(series.length - 1, 1)) * plotWidth,
    };
  });
  const currentPoints = makePoints('current');
  const previousPoints = makePoints('previous');
  const values = [...currentPoints, ...previousPoints]
    .map((point) => point.value)
    .filter((value) => value !== null);
  const fixedRange = yMin !== null && yMax !== null && yMax > yMin;
  const min = fixedRange ? yMin : 0;
  const max = fixedRange ? yMax : Math.max(1, ...values) * 1.15;
  const scaleY = (value) => {
    const y = baseline - ((value - min) / (max - min)) * plotHeight;
    return fixedRange ? Math.max(top, Math.min(baseline, y)) : y;
  };
  currentPoints.forEach((point) => { if (point.value !== null) point.y = scaleY(point.value); });
  previousPoints.forEach((point) => { if (point.value !== null) point.y = scaleY(point.value); });
  const grid = [0, 0.5, 1].map((ratio) => {
    const y = baseline - ratio * plotHeight;
    const value = min + (max - min) * ratio;
    return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" class="climate-grid"></line><text x="${left - 8}" y="${y + 4}" class="climate-axis" text-anchor="end">${escapeHtml(formatNumber(value))}</text>`;
  }).join('');
  const months = series.map((point, index) => {
    const x = left + (index / Math.max(series.length - 1, 1)) * plotWidth;
    return `<text x="${x}" y="${baseline + 22}" class="climate-axis" text-anchor="middle">${escapeHtml(point.month)}月</text>`;
  }).join('');
  const linePath = (points) => {
    let started = false;
    return points.map((point) => {
      if (point.value === null) {
        started = false;
        return '';
      }
      const command = started ? 'L' : 'M';
      started = true;
      return `${command}${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    }).join(' ');
  };
  const dots = (points, color, label) => points.map((point) => {
    if (point.value === null) return '';
    return `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.5" fill="${escapeHtml(color)}"><title>${escapeHtml(label)}・${escapeHtml(point.month)}月 ${escapeHtml(formatNumber(point.value))}${escapeHtml(unit)}</title></circle>`;
  }).join('');
  const valueLabels = (points, color, above) => {
    if (!showValues) return '';
    return points.map((point) => {
      if (point.value === null) return '';
      const y = above ? Math.max(top + 10, point.y - 8) : Math.min(height - bottom + 18, point.y + 16);
      return `<text x="${point.x.toFixed(1)}" y="${y.toFixed(1)}" class="climate-point-label" fill="${escapeHtml(color)}" text-anchor="middle">${escapeHtml(formatNumber(point.value))}</text>`;
    }).join('');
  };
  const legend = `
    <div class="climate-legend">
      <span><i style="--swatch:${escapeHtml(colors[0])}"></i>${escapeHtml(labels[0])}</span>
      <span><i style="--swatch:${escapeHtml(colors[1])}"></i>${escapeHtml(labels[1])}</span>
    </div>
  `;
  return `
    <div class="climate-chart">
      <h4>${escapeHtml(title)}（${escapeHtml(unit)}）</h4>
      ${legend}
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}折線圖">
        ${grid}
        <line x1="${left}" y1="${baseline}" x2="${width - right}" y2="${baseline}" class="climate-baseline"></line>
        ${months}
        <path d="${linePath(previousPoints)}" class="climate-line" stroke="${escapeHtml(colors[1])}"></path>
        <path d="${linePath(currentPoints)}" class="climate-line" stroke="${escapeHtml(colors[0])}"></path>
        ${dots(previousPoints, colors[1], labels[1])}
        ${dots(currentPoints, colors[0], labels[0])}
        ${valueLabels(previousPoints, colors[1], false)}
        ${valueLabels(currentPoints, colors[0], true)}
      </svg>
    </div>
  `;
}

function renderClimate() {
  const container = document.querySelector('#climate-chart');
  if (!container) return;
  const snapshot = state.climate || {};
  const baseSeries = (snapshot.modes?.yearly?.series) || [];
  const baselineData = state.climateBaselineData;
  const hasBaselineData = Boolean(baselineData?.series?.length);
  const baselineMeta = (hasBaselineData && baselineData.periods?.[state.climateBaseline]) || {
    label: '去年',
    period: null,
    count: 1,
  };
  const series = hasBaselineData
    ? baselineData.series.map((item) => ({
        month: item.month,
        current: item.current,
        previous: {
          mean_t: item.baselines?.[state.climateBaseline]?.mean_t,
          rainfall: item.baselines?.[state.climateBaseline]?.rainfall,
        },
      }))
    : baseSeries.map((item) => ({
        month: item.month,
        current: item.current,
        previous: item.previous,
      }));
  if (!series.length) {
    container.innerHTML = '<div class="panel climate-panel"><p class="hint">氣候資料尚未取得。</p></div>';
    return;
  }
  const periods = snapshot.periods?.yearly || {};
  const currentYear = baselineData?.current_year || periods.current_year || new Date().getFullYear();
  const asOf = periods.as_of ? `，今年資料至 ${formatDate(periods.as_of)}` : '';
  const hasValue = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
  const latest = [...series].reverse().find((item) => hasValue(item.current?.mean_t)) || null;
  const baselineLabel = baselineMeta.label || '去年';
  const summary = latest ? `
    <div class="climate-summary">
      <div><span>${escapeHtml(latest.month)} 月平均氣溫</span><strong>${escapeHtml(climateValue(latest.current.mean_t, '°C'))} <small>${escapeHtml(baselineLabel)} ${escapeHtml(climateValue(latest.previous?.mean_t, '°C'))}</small></strong></div>
      <div><span>${escapeHtml(latest.month)} 月雨量</span><strong>${escapeHtml(climateValue(latest.current?.rainfall, ' mm'))} <small>${escapeHtml(baselineLabel)} ${escapeHtml(climateValue(latest.previous?.rainfall, ' mm'))}</small></strong></div>
    </div>
  ` : '';
  const temperatureChart = climateLineSvg(
    '每月平均氣溫', '°C', series, 'mean_t', ['#d97706', '#0284c7'],
    [`${currentYear} 年`, baselineLabel], { yMin: 15, yMax: 35, showValues: true },
  );
  const rainfallChart = climateLineSvg(
    '每月累積雨量', 'mm', series, 'rainfall', ['#0f766e', '#7c3aed'],
    [`${currentYear} 年`, baselineLabel], { showValues: true },
  );
  const errors = snapshot.errors || [];
  const errorHtml = errors.length ? `<p class="climate-error">部分資料暫缺（${escapeHtml(errors.length)} 項），其餘數據仍可參考。</p>` : '';
  const selectOptions = CLIMATE_BASELINE_OPTIONS.map((option) => `
    <option value="${escapeHtml(option.key)}" ${option.key === state.climateBaseline ? 'selected' : ''}>${escapeHtml(option.label)}</option>
  `).join('');
  const baselineNote = hasBaselineData
    ? `氣溫與雨量比較基準：${escapeHtml(baselineLabel)}${baselineMeta.period ? `（${escapeHtml(baselineMeta.period)}，${escapeHtml(baselineMeta.count)} 年）` : ''}。`
    : '比較基準資料尚未取得，目前顯示去年同月。';
  container.innerHTML = `
    <div class="panel climate-panel">
      <div class="panel-head">
        <div>
          <h2>氣候變化</h2>
          <p class="climate-sub">${escapeHtml(snapshot.station?.name || '')}氣象站 ${escapeHtml(snapshot.station?.id || '')}・今年與所選基準每月統計${escapeHtml(asOf)}</p>
        </div>
        <label class="climate-select">
          <span>比較基準</span>
          <select id="climate-baseline">${selectOptions}</select>
        </label>
      </div>
      ${summary}
      <div class="climate-charts">${temperatureChart}${rainfallChart}</div>
      <p class="climate-baseline-note">${baselineNote}</p>
      ${errorHtml}
      <p class="climate-source">資料來源：${escapeHtml(snapshot.sources?.observation || baselineData?.source || '')}</p>
    </div>
  `;
  const select = container.querySelector('#climate-baseline');
  if (select) {
    select.addEventListener('change', (event) => {
      state.climateBaseline = event.target.value;
      try {
        localStorage.setItem(CLIMATE_BASELINE_KEY, state.climateBaseline);
      } catch (_) {}
      renderClimate();
    });
  }
}

async function loadClimateBaselines() {
  try {
    const response = await fetch(DEMO_SITE ? staticAsset('data/climate_baselines.json') : apiUrl('/api/climate/baselines'));
    if (!response.ok) throw new Error('無法取得氣候比較基準');
    state.climateBaselineData = await response.json();
    renderClimate();
  } catch (_) {
    // 保留以去年為基準的備用圖表
  }
}

function renderScript() {
  const container = document.querySelector('#script');
  if (!container) return;
  if (state.loading) {
    container.innerHTML = '<p class="hint">正在產生廣播稿…</p>';
    renderRawDetails();
    renderTtsStatus();
    return;
  }
  if (!state.broadcast) {
    container.innerHTML = '<p class="hint">選好作物與市場後，按下方「播放廣播」即可產生客語廣播稿。</p>';
    renderRawDetails();
    renderTtsStatus();
    return;
  }
  container.innerHTML = state.broadcast.segments.map((segment) => `
    <div class="script-line script-${escapeHtml(segment.type)}">
      <span class="script-type">${scriptTypeLabel(segment.type)}</span>
      <p>${escapeHtml(segment.text)}</p>
    </div>
  `).join('');
  renderRawDetails();
  renderTtsStatus();
}

function scriptTypeLabel(type) {
  return ({ intro: '開場', festival: '節慶', trade_date: '行情日', weather: '氣象', price: '行情', outro: '結尾' })[type] || '內容';
}

function renderRawDetails() {
  const container = document.querySelector('#raw-details');
  if (!container) return;
  if (state.loading || !state.broadcast) {
    container.innerHTML = '';
    return;
  }
  const priceSegments = (state.broadcast.segments || []).filter((segment) => (
    segment.type === 'price' && segment.data?.raw_rows?.length
  ));
  if (!priceSegments.length) {
    container.innerHTML = '';
    return;
  }
  const seen = new Set();
  const rows = [];
  priceSegments.forEach((segment) => {
    segment.data.raw_rows.forEach((row) => {
      const key = [row.crop_name, row.market_code, row.crop_code, row.avg, row.volume].join('|');
      if (seen.has(key)) return;
      seen.add(key);
      rows.push(row);
    });
  });
  if (!rows.length) {
    container.innerHTML = '';
    return;
  }
  const body = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.crop_name || '')}</td>
      <td>${escapeHtml(row.market_display || row.market_name || '')}</td>
      <td>${escapeHtml(formatNumber(row.upper))}</td>
      <td>${escapeHtml(formatNumber(row.middle))}</td>
      <td>${escapeHtml(formatNumber(row.lower))}</td>
      <td><strong>${escapeHtml(formatNumber(row.avg))}</strong></td>
      <td>${escapeHtml(formatNumber(row.volume))}</td>
    </tr>
  `).join('');
  container.innerHTML = `
    <details class="raw-details-box" open>
      <summary>原始交易明細（${rows.length} 筆）</summary>
      <div class="raw-table-wrap">
        <table class="raw-table">
          <thead>
            <tr><th>作物</th><th>市場</th><th>上價</th><th>中價</th><th>下價</th><th>平均價</th><th>交易量</th></tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      <p class="raw-note">資料日期：${escapeHtml(formatDate(state.broadcast.trade_date))}。資料來源：農業部農產品批發市場交易行情（FarmTransData）。平均價為交易量加權平均；上方廣播使用加權平均價。</p>
    </details>
  `;
}

function renderActionBar() {
  const summary = document.querySelector('#action-summary');
  const playButton = document.querySelector('#play-button');
  const label = document.querySelector('#play-label');
  const replayButton = document.querySelector('#replay-button');
  if (!summary || !playButton || !label) return;
  if (replayButton) replayButton.hidden = !state.broadcast?.audio_url;
  const ttsRunning = isTtsRunning();
  const audio = state.audio;
  const music = state.music;
  const voicePlaying = Boolean(audio && !audio.paused && !audio.ended);
  const musicPlaying = Boolean(music && !music.paused && !state.musicPausedForVoice);
  const playing = voicePlaying || musicPlaying;
  const paused = !playing && Boolean((audio && audio.paused && !audio.ended) || (music && music.paused));
  summary.innerHTML = `已選 <strong>${state.selectedCrops.size}</strong> 種作物、<strong>${state.selectedMarkets.size}</strong> 個市場`;
  playButton.classList.toggle('is-speaking', playing);
  playButton.classList.toggle('is-paused', paused);
  playButton.disabled = state.loading || state.transitioning;
  playButton.setAttribute('aria-pressed', String(playing));
  const action = paused ? '繼續播放' : (playing ? '暫停播放' : '播放廣播');
  playButton.setAttribute('aria-label', action);
  label.textContent = state.transitioning
    ? '準備播放…'
    : (ttsRunning && !musicPlaying && !voicePlaying ? '合成中…' : (state.loading ? '產生中…' : action));
}

function renderNotice() {
  const container = document.querySelector('#notice');
  if (!container) return;
  if (!state.notice) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `<div class="notice notice-${escapeHtml(state.notice.type)}"><span>${escapeHtml(state.notice.message)}</span><button type="button" class="notice-close" aria-label="關閉">×</button></div>`;
  container.querySelector('.notice-close').addEventListener('click', () => {
    state.notice = null;
    renderNotice();
  });
}

function setNotice(message, type = 'info') {
  state.notice = { message, type };
  renderNotice();
}

async function loadPreferences() {
  const local = readLocalPreferences();
  const localReady = hasLocalSetup();
  let prefs = null;
  try {
    if (DEMO_SITE) throw new Error('static');
    const response = await fetch(apiUrl(`/api/preferences?client_id=${encodeURIComponent(state.clientId || '')}`));
    if (!response.ok) throw new Error('無法讀取偏好設定');
    prefs = await response.json();
  } catch (_) {
    prefs = null;
  }

  const serverReady = Boolean(
    prefs?.configured
    && prefs?.source === 'client'
    && prefs?.crop_ids?.length
    && prefs?.market_codes?.length,
  );
  const chosen = localReady
    ? { ...prefs, configured: true, crop_ids: local.crop_ids, market_codes: local.market_codes, broadcast_options: local.broadcast_options, source: 'local' }
    : (serverReady ? prefs : null);

  state.prefs = chosen || { configured: false, crop_ids: [], market_codes: [], source: null };
  state.selectedCrops = new Set((state.prefs.crop_ids || []).filter((id) => state.crops.some((crop) => crop.id === id)));
  state.selectedMarkets = new Set((state.prefs.market_codes || []).filter((code) => state.markets.some((market) => market.code === code)));
  state.broadcastOptions = normalizeBroadcastOptions(state.prefs.broadcast_options);
  state.firstVisit = !isSetupComplete();
  if (!state.firstVisit) {
    writeLocalPreferences([...state.selectedCrops], [...state.selectedMarkets], [...state.broadcastOptions]);
  }
}

async function loadBootstrap() {
  resetTts();
  let response;
  try {
    response = await fetch(DEMO_SITE ? staticAsset('data/bootstrap.json') : apiUrl('/api/bootstrap'));
  } catch (_) {
    throw new Error(USE_REMOTE ? '無法連線到遠端 API' : '無法連線到後端');
  }
  if (!response.ok) throw new Error(`無法取得初始資料（HTTP ${response.status}）`);
  const data = await response.json();
  state.crops = data.crops || [];
  state.markets = data.markets || [];
  state.presetCodes = data.preset_market_codes || [];
  state.weather = data.weather || null;
  state.climate = data.climate || null;
  state.priceDate = data.price_date;
  await loadPreferences();
  renderCrops();
  renderMarkets();
  renderStatus();
  renderWeather();
  renderClimate();
  renderScript();
  renderActionBar();
  if (state.firstVisit) openSettings('first');
}

function waitingMusicUrl() {
  return mediaUrl(WAITING_MUSIC_PATH);
}

function cancelVolumeFade(audio) {
  if (!audio) return;
  if (audio.__fadeFrame) cancelAnimationFrame(audio.__fadeFrame);
  audio.__fadeFrame = null;
  audio.__fadeToken = (audio.__fadeToken || 0) + 1;
}

function fadeVolume(audio, to, duration) {
  if (!audio) return Promise.resolve(false);
  const token = (audio.__fadeToken || 0) + 1;
  audio.__fadeToken = token;
  const from = Number.isFinite(audio.volume) ? audio.volume : 0;
  const started = performance.now();
  return new Promise((resolve) => {
    const step = (now) => {
      if (audio.__fadeToken !== token) {
        resolve(false);
        return;
      }
      const progress = Math.min(1, Math.max(0, (now - started) / duration));
      audio.volume = Math.max(0, Math.min(1, from + (to - from) * progress));
      if (progress < 1) {
        audio.__fadeFrame = requestAnimationFrame(step);
      } else {
        audio.__fadeFrame = null;
        resolve(true);
      }
    };
    audio.__fadeFrame = requestAnimationFrame(step);
  });
}

function startWaitingMusic() {
  stopWaitingMusic();
  const audio = new Audio(waitingMusicUrl());
  audio.loop = false;
  audio.volume = 0;
  state.music = audio;
  audio.addEventListener('ended', () => {
    if (state.music !== audio) return;
    state.music = null;
    state.musicPausedForVoice = false;
    renderActionBar();
  });
  audio.addEventListener('error', () => {
    if (state.music === audio) {
      stopWaitingMusic();
      setNotice('背景音樂載入失敗，語音合成仍會繼續。', 'info');
    }
  });
  audio.play().then(() => {
    if (state.music !== audio) return;
    fadeVolume(audio, WAITING_MUSIC_VOLUME, MUSIC_FADE_IN_MS);
  }).catch(() => {
    if (state.music !== audio) return;
    stopWaitingMusic();
    setNotice('瀏覽器阻擋了背景音樂，語音合成仍會繼續。', 'info');
  });
}

async function fadeOutWaitingMusic() {
  const audio = state.music;
  if (!audio) return;
  await fadeVolume(audio, 0, MUSIC_FADE_OUT_MS);
  if (state.music !== audio) return;
  audio.pause();
  state.musicPausedForVoice = true;
}

function resumeWaitingMusic() {
  const audio = state.music;
  if (!audio || !state.musicPausedForVoice) return;
  if (state.userPaused) return; // 使用者按過暫停，不要自動接著播歌曲
  state.musicPausedForVoice = false;
  audio.volume = 0;
  audio.play().then(() => {
    if (state.music !== audio) return;
    fadeVolume(audio, WAITING_MUSIC_VOLUME, MUSIC_FADE_IN_MS);
  }).catch(() => {
    if (state.music !== audio) return;
    stopWaitingMusic();
  });
}

function stopWaitingMusic() {
  const audio = state.music;
  state.music = null;
  state.musicPausedForVoice = false;
  state.userPaused = false;
  if (!audio) return;
  cancelVolumeFade(audio);
  audio.pause();
  audio.currentTime = 0;
  audio.volume = WAITING_MUSIC_VOLUME;
}

function isTtsRunning() {
  return state.ttsJob?.status === 'queued' || state.ttsJob?.status === 'running';
}

function stopTtsPolling() {
  if (state.ttsTimer) clearTimeout(state.ttsTimer);
  state.ttsTimer = null;
}

function stopTtsClock() {
  if (state.ttsClock) clearInterval(state.ttsClock);
  state.ttsClock = null;
}

function startTtsClock() {
  stopTtsClock();
  state.ttsClock = setInterval(() => {
    if (isTtsRunning()) renderTtsStatus();
    else stopTtsClock();
  }, 1000);
}

function formatElapsed(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function resetTts() {
  stopTtsPolling();
  stopTtsClock();
  stopWaitingMusic();
  if (state.audio) {
    state.audio.pause();
    state.audio = null;
  }
  state.speaking = false;
  state.ttsJob = null;
  if (state.broadcast) state.broadcast.audio_url = null;
  renderTtsStatus();
}

function renderTtsStatus() {
  const container = document.querySelector('#tts-status');
  if (!container) return;
  if (!state.broadcast) {
    container.innerHTML = '';
    return;
  }
  const attribution = '<p class="attribution">語音引擎：VoxHakka 大埔腔（宋涵葳，東勢）・CC BY-NC 4.0・僅供非商業使用<br>等待音樂：〈月光光、吊四方〉・臺中市政府客家事務委員會製作・政府網站資料開放宣告（須註明出處）</p>';
  const job = state.ttsJob;
  let body = '';
  if (job && (job.status === 'queued' || job.status === 'running')) {
    const elapsed = job.startedAt ? formatElapsed(Date.now() - job.startedAt) : '00:00';
    body = `
      <div class="tts-progress">
        <span class="tts-spinner" aria-hidden="true"></span>
        <span>${job.status === 'queued' ? '排隊中' : '大埔腔語音合成中'}… ${elapsed}</span>
        <button type="button" class="text-button" id="tts-cancel">停止等待</button>
      </div>
      <p class="hint">等待期間會播放大埔腔童謠〈月光光、吊四方〉；合成完成後音樂會在 5 秒內漸弱，再播出行情。</p>
    `;
  } else if (job && job.status === 'error') {
    const words = job.unknown_words?.length
      ? `<p class="tts-error-detail">尚未支援的詞彙：${escapeHtml(job.unknown_words.join('、'))}</p>`
      : '';
    body = `
      <div class="tts-error">
        <p>${escapeHtml(job.error || '語音合成失敗')}</p>
        ${words}
        <button type="button" class="text-button" id="tts-retry">重新合成</button>
      </div>
    `;
  } else if (state.broadcast.audio_url) {
    const elapsed = job?.elapsed_seconds ? `（${job.elapsed_seconds} 秒）` : '';
    body = `<div class="tts-ready"><span>大埔腔語音已就緒${elapsed}${state.transitioning ? '（音樂漸弱後播放）' : ''}</span>${job?.cached ? '<span class="badge">快取</span>' : ''}</div>`;
  } else {
    body = '<p class="hint">按「播放廣播」後會開始合成大埔腔語音。</p>';
  }
  container.innerHTML = `${body}${attribution}`;
  const cancel = container.querySelector('#tts-cancel');
  if (cancel) {
    cancel.addEventListener('click', () => {
      stopTtsPolling();
      stopTtsClock();
      stopWaitingMusic();
      state.ttsJob = null;
      setNotice('已停止等待語音合成；背景工作可能仍會完成。', 'info');
      renderTtsStatus();
      renderActionBar();
    });
  }
  const retry = container.querySelector('#tts-retry');
  if (retry) {
    retry.addEventListener('click', () => {
      if (DEMO_SITE) {
        if (state.broadcast?.audio_url) playAudio(state.broadcast.audio_url);
        else setNotice('展示版無法重新合成語音。', 'info');
        return;
      }
      if (state.broadcast?.tts_text) startTtsJob(state.broadcast.tts_text);
    });
  }
}

async function startTtsJob(text, musicStarted = false) {
  stopTtsPolling();
  stopTtsClock();
  if (!text) {
    setNotice('沒有可合成的廣播文字。', 'error');
    return;
  }
  if (state.audio) {
    state.audio.pause();
    state.audio = null;
  }
  state.speaking = false;
  state.broadcast.audio_url = null;
  state.ttsJob = { status: 'queued', startedAt: Date.now() };
  renderTtsStatus();
  renderActionBar();
  if (!musicStarted || !state.music) startWaitingMusic();
  startTtsClock();
  try {
    const response = await fetch(apiUrl('/api/tts/jobs'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error('無法建立語音合成工作');
    const job = await response.json();
    state.ttsJob = { ...job, startedAt: Date.now() };
    renderTtsStatus();
    renderActionBar();
    pollTtsJob(job.id);
  } catch (error) {
    stopTtsClock();
    stopWaitingMusic();
    state.ttsJob = { status: 'error', error: error.message };
    renderTtsStatus();
    renderActionBar();
  }
}

async function pollTtsJob(jobId) {
  stopTtsPolling();
  const tick = async () => {
    if (!state.ttsJob || state.ttsJob.id !== jobId) return;
    try {
      const response = await fetch(apiUrl(`/api/tts/jobs/${jobId}`));
      if (!response.ok) throw new Error('無法取得語音合成狀態');
      const job = await response.json();
      const startedAt = state.ttsJob.startedAt;
      if (!state.ttsJob || state.ttsJob.id !== jobId) return;
      state.ttsJob = { ...job, startedAt };
      if (job.status === 'done') {
        stopTtsClock();
        if (state.broadcast) state.broadcast.audio_url = mediaUrl(job.audio_url);
        state.transitioning = true;
        renderTtsStatus();
        renderActionBar();
        await fadeOutWaitingMusic();
        state.transitioning = false;
        if (!state.ttsJob || state.ttsJob.id !== jobId) return;
        if (job.audio_url) playAudio(mediaUrl(job.audio_url));
        return;
      }
      if (job.status === 'error') {
        stopTtsClock();
        stopWaitingMusic();
        renderTtsStatus();
        renderActionBar();
        setNotice(job.error || '語音合成失敗', 'error');
        return;
      }
      renderTtsStatus();
      renderActionBar();
      state.ttsTimer = setTimeout(tick, 2000);
    } catch (error) {
      stopTtsClock();
      stopWaitingMusic();
      if (!state.ttsJob || state.ttsJob.id !== jobId) return;
      state.ttsJob = { ...state.ttsJob, status: 'error', error: error.message };
      renderTtsStatus();
      renderActionBar();
    }
  };
  tick();
}

async function playBroadcast() {
  if (DEMO_SITE) {
    if (!state.selectedCrops.size || !state.selectedMarkets.size) {
      setNotice('請先選擇作物與市場。', 'warn');
      return;
    }
    if (state.broadcast?.audio_url) {
      playAudio(state.broadcast.audio_url);
      return;
    }
    state.loading = true;
    renderActionBar();
    renderScript();
    try {
      const response = await fetch(staticAsset('data/broadcast.json'));
      if (!response.ok) throw new Error('無法載入展示廣播稿');
      state.broadcast = await response.json();
      if (state.broadcast.audio_url && !/^https?:\/\//.test(state.broadcast.audio_url)) {
        state.broadcast.audio_url = staticAsset(state.broadcast.audio_url);
      }
      state.loading = false;
      renderScript();
      renderActionBar();
      setNotice('展示版：廣播稿與語音為預先產生的範例檔。', 'info');
      if (state.broadcast.audio_url) playAudio(state.broadcast.audio_url);
    } catch (error) {
      state.loading = false;
      renderActionBar();
      setNotice(error.message, 'error');
    }
    return;
  }
  if (!state.selectedCrops.size) {
    setNotice('請先至少選一種作物。', 'warn');
    return;
  }
  if (!state.selectedMarkets.size) {
    setNotice('請先至少選一個市場。', 'warn');
    return;
  }
  if (state.broadcast?.audio_url) {
    playAudio(state.broadcast.audio_url);
    return;
  }
  // 在按下的瞬間（使用者手勢內）就開始播音樂，避免非同步請求完成後
  // 再呼叫 play() 被瀏覽器自動播放政策擋住，讓使用者必須按第二次。
  startWaitingMusic();
  state.loading = true;
  renderActionBar();
  renderScript();
  try {
    const response = await fetch(apiUrl('/api/broadcast'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        crop_ids: [...state.selectedCrops],
        market_codes: [...state.selectedMarkets],
        include_weather: true,
        options: [...state.broadcastOptions],
      }),
    });
    if (!response.ok) throw new Error('廣播稿產生失敗');
    state.broadcast = await response.json();
    state.loading = false;
    renderScript();
    renderActionBar();
    startTtsJob(state.broadcast.tts_text || state.broadcast.full_text, true);
  } catch (error) {
    state.loading = false;
    stopWaitingMusic();
    renderActionBar();
    setNotice(error.message, 'error');
  }
}

function replayBroadcastOnly() {
  if (state.loading || state.transitioning || state.voiceStarting || isTtsRunning()) return;
  const url = state.broadcast?.audio_url;
  if (!url) {
    setNotice('尚無可重播的廣播語音。', 'info');
    return;
  }
  // 重播只要廣播內容：停掉背景音樂，並避免語音結束後又自動接歌。
  stopWaitingMusic();
  playAudio(url);
}

function togglePlayback() {
  if (state.loading || state.transitioning || state.voiceStarting) return;
  const audio = state.audio;
  const music = state.music;
  const voicePlaying = Boolean(audio && !audio.paused && !audio.ended);
  const musicPlaying = Boolean(music && !music.paused && !state.musicPausedForVoice);

  if (!voicePlaying && !musicPlaying) {
    if (audio && audio.paused && !audio.ended) {
      // 語音暫停中：續播語音；musicPausedForVoice 保持不變，語音結束再續歌曲。
      state.userPaused = false;
      audio.play().then(() => {
        renderActionBar();
      }).catch(() => {
        renderActionBar();
        setNotice('瀏覽器阻擋了播放，請再按一次播放。', 'warn');
      });
      return;
    }
    if (music && music.paused) {
      state.userPaused = false;
      state.musicPausedForVoice = false;
      music.play().then(() => {
        if (state.music === music) fadeVolume(music, WAITING_MUSIC_VOLUME, 1000);
        renderActionBar();
      }).catch(() => renderActionBar());
      return;
    }
    playBroadcast();
    return;
  }

  // 暫停：語音與歌曲都壓住，且標記為使用者暫停，語音結束後不自動續歌曲。
  state.userPaused = true;
  if (voicePlaying) audio.pause();
  if (musicPlaying) {
    cancelVolumeFade(music);
    music.pause();
  }
  renderActionBar();
}

async function playAudio(url) {
  if (state.voiceStarting) return;
  const src = mediaUrl(url);
  if (!src) return;
  state.voiceStarting = true;
  if (state.audio) state.audio.pause();
  const music = state.music;
  try {
    // 語音播出前，先讓還在播放的背景音樂退場；合成完成流程已先漸弱過，
    // 這裡只處理「重聽」等音樂已恢復播放的情況。
    if (music && !state.musicPausedForVoice && !music.paused) {
      state.transitioning = true;
      renderActionBar();
      await fadeOutWaitingMusic();
      if (state.music !== music) return; // 等待期間已被取消或重新設定
    }
    startVoiceAudio(src);
  } finally {
    state.transitioning = false;
    state.voiceStarting = false;
  }
}

function startVoiceAudio(url) {
  const audio = new Audio(url);
  audio.volume = 0;
  state.audio = audio;
  state.speaking = true;
  renderActionBar();
  audio.addEventListener('ended', () => {
    if (state.audio !== audio) return;
    state.speaking = false;
    state.audio = null;
    resumeWaitingMusic();
    renderActionBar();
  });
  audio.addEventListener('error', () => {
    if (state.audio !== audio) return;
    state.speaking = false;
    state.audio = null;
    resumeWaitingMusic();
    renderActionBar();
    setNotice('音檔播放失敗。', 'error');
  });
  audio.play().then(() => {
    fadeVolume(audio, 1, VOICE_FADE_IN_MS);
    renderActionBar();
  }).catch(() => {
    if (state.audio !== audio) return;
    state.speaking = false;
    state.audio = null;
    resumeWaitingMusic();
    renderActionBar();
    setNotice('瀏覽器阻擋了自動播放，請再按一次播放。', 'warn');
  });
}

function stopPreview() {
  if (state.previewAudio) {
    state.previewAudio.pause();
    state.previewAudio = null;
  }
}

function playPreviewAudio(url) {
  if (state.previewAudio) state.previewAudio.pause();
  const audio = new Audio(url);
  state.previewAudio = audio;
  audio.addEventListener('ended', () => {
    if (state.previewAudio === audio) state.previewAudio = null;
  });
  audio.addEventListener('error', () => {
    if (state.previewAudio !== audio) return;
    state.previewAudio = null;
    setNotice('發音音檔播放失敗。', 'error');
  });
  audio.play().catch(() => {
    if (state.previewAudio !== audio) return;
    state.previewAudio = null;
    setNotice('瀏覽器阻擋了自動播放，請再按一次該項目。', 'warn');
  });
}

function playPreviewSound(text) {
  if (!state.previewSpeech || !text) return;
  const entry = state.previewSounds[text];
  if (!entry?.audio_url) {
    setNotice(state.previewProgress.running ? '語音還在預錄中，請稍後再試。' : '此項目尚未有預錄語音。', 'info');
    return;
  }
  playPreviewAudio(entry.audio_url);
}

function renderPreviewProgress() {
  const box = document.querySelector('#preview-progress');
  if (!box) return;
  const { ready, total, running } = state.previewProgress;
  if (!total) {
    box.textContent = '語音準備中…';
  } else if (running) {
    box.textContent = `語音預錄 ${ready} / ${total}`;
  } else if (ready < total) {
    box.textContent = `語音預錄 ${ready} / ${total}（部分失敗）`;
  } else {
    box.textContent = `語音已就緒 ${ready} / ${total}`;
  }
}

async function pollPreviewStatus() {
  try {
    const response = await fetch(DEMO_SITE ? staticAsset('data/preview_items.json') : apiUrl('/api/tts/preview'));
    if (!response.ok) throw new Error('無法取得語音狀態');
    const data = await response.json();
    state.previewSounds = data.items || {};
    Object.values(state.previewSounds).forEach((entry) => {
      if (entry?.audio_url) entry.audio_url = mediaUrl(entry.audio_url);
    });
    state.previewProgress = {
      ready: data.ready || 0,
      total: data.total || 0,
      running: Boolean(data.running),
    };
    renderPreviewProgress();
  } catch (_) {
    // 保持上次狀態，不打斷瀏覽。
  }
  if (DEMO_SITE) {
    state.previewPollTimer = null;
    return;
  }
  if (state.previewProgress.running) {
    state.previewPollTimer = setTimeout(pollPreviewStatus, 3000);
  } else {
    state.previewPollTimer = null;
    if (state.previewProgress.total < state.previewExpected) {
      setTimeout(prewarmPreviewSounds, 1000);
    }
  }
}

async function prewarmPreviewSounds() {
  const texts = [
    ...state.crops.map((crop) => crop.name_hakka || crop.name_zh),
    ...state.markets.map((market) => market.name),
  ].filter(Boolean);
  if (!texts.length) return;
  state.previewExpected = texts.length;
  if (DEMO_SITE) {
    await pollPreviewStatus();
    return;
  }
  try {
    const response = await fetch(apiUrl('/api/tts/preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texts }),
    });
    if (!response.ok) throw new Error('無法啟動語音預錄');
    const data = await response.json();
    state.previewSounds = data.items || {};
    Object.values(state.previewSounds).forEach((entry) => {
      if (entry?.audio_url) entry.audio_url = mediaUrl(entry.audio_url);
    });
    state.previewProgress = {
      ready: data.ready || 0,
      total: data.total || 0,
      running: Boolean(data.running),
    };
    renderPreviewProgress();
    if (state.previewProgress.running) pollPreviewStatus();
  } catch (_) {
    renderPreviewProgress();
  }
}

async function refreshData() {
  if (DEMO_SITE) {
    setNotice('展示版不支援重新抓取資料。', 'info');
    return;
  }
  state.loading = true;
  renderActionBar();
  try {
    const response = await fetch(apiUrl('/api/refresh'), { method: 'POST' });
    if (!response.ok) throw new Error('重新整理失敗');
    state.notice = null;
    await loadBootstrap();
    setNotice('已重新抓取行情、氣象與氣候資料。', 'info');
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    state.loading = false;
    renderActionBar();
  }
}

async function boot() {
  state.clientId = getOrCreateClientId();
  renderShell();
  renderStatus();
  renderActionBar();
  renderNotice();
  try {
    await loadRuntimeConfig();
    await loadBootstrap();
    loadClimateBaselines();
    prewarmPreviewSounds();
    if (DEMO_SITE) setNotice('這是靜態展示版：資料為快照，廣播稿與語音為範例檔。', 'info');
  } catch (error) {
    const hint = DEMO_SITE
      ? ''
      : USE_REMOTE
        ? '。請稍後再試，或確認本機公開伺服器仍在執行。'
        : '。請確認後端已在 http://127.0.0.1:8000 啟動。';
    setNotice(`${error.message}${hint}`, 'error');
  }
}

boot();
