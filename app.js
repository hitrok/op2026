/* おおいたペイ 加盟店マップ — アプリ本体
 * データ: 大分市プレミアム付き商品券 加盟店一覧（非公式・個人利用）
 * 地図: Leaflet + CARTO basemap / 位置情報: 国土地理院 住所検索API
 */
'use strict';

// ===== 定数 =====
const SRC = 'https://2026.oita-pay.jp/docs/store_list/store_list.json'; // 最新加盟店データ
const GSI = 'https://msearch.gsi.go.jp/address-search/AddressSearch?q='; // ジオコーダ
const BASELINE = 'data/stores.geo.json'; // 同梱の初期データ
// フリーテキスト→おすすめ条件（Claude Haiku）プロキシ。キーはサーバ側(santaku Edge Function)が保持。
const RECOMMEND_URL = 'https://noarrgikglfcprjiuqtf.supabase.co/functions/v1/oitapay-recommend';
const DATA_VERSION = 2;  // 座標の補正版。上げると保存済みデータの座標をbaselineで再シードする
const OITA_CENTER = [33.2335, 131.6075];

const CATS = {
  '食べる': { color: '#ff9500', emoji: '🍴' },
  '買う':   { color: '#007aff', emoji: '🛍️' },
  '暮らす': { color: '#34c759', emoji: '🏠' },
  '遊ぶ':   { color: '#af52de', emoji: '🎡' },
  '泊まる': { color: '#ff2d55', emoji: '🛏️' },
};
const CAT_ORDER = ['食べる', '買う', '暮らす', '遊ぶ', '泊まる'];
const CAT_FALLBACK = { color: '#8e8e93', emoji: '📍' };
const catOf = (n) => CATS[n] || CAT_FALLBACK;

// ===== 状態 =====
let stores = [];                 // 全店舗（座標付き）
let filtered = [];               // 絞り込み後
let map, cluster, meMarker;
const markersById = new Map();
let userPos = null;              // {lat,lng}
let dataMeta = null;             // {updatedAt,count}（更新後のみ）
let view = 'map';
const filters = { majors: new Set(), minor: '', q: '', digital: false, size: '' };
let aiActive = false;          // 「AIでおすすめ」モード
let aiCriteria = null;         // {categories,genres,keywords,payment,size,reason}
let aiLoading = false;

// 店舗区分（公式表記：大規模店舗 / 中小・小規模店舗）— 商品券の券種に関わる重要な区別
function sizeInfo(s) {
  return s.is_small_store ? { label: '中小・小規模店舗', cls: 'small' } : { label: '大規模店舗', cls: 'large' };
}
let listLimit = 80;

const $ = (s) => document.querySelector(s);

// ===== 文字正規化 / 距離 =====
function z2h(s) {
  return (s || '')
    .replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/　/g, ' ')
    .replace(/[ー－―‐−]/g, '-');
}
const k2h = (s) => (s || '').replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
const norm = (s) => k2h(z2h(s)).toLowerCase();

function distM(a, b) {
  const R = 6371000, t = Math.PI / 180;
  const dLa = (b.lat - a.lat) * t, dLo = (b.lng - a.lng) * t;
  const la1 = a.lat * t, la2 = b.lat * t;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function fmtDist(m) {
  if (m == null) return '';
  return m < 1000 ? `${Math.round(m / 10) * 10}m` : `${(m / 1000).toFixed(m < 10000 ? 1 : 0)}km`;
}

// ===== ジオコーディング（更新時に新規店舗だけ実行） =====
function candidates(a1, a2) {
  a1 = z2h(a1).trim(); a2 = z2h(a2).trim();
  const out = [], seen = new Set();
  const push = (q, acc) => { if (q && !seen.has(q)) { seen.add(q); out.push({ q, acc }); } };
  if (a1 && a2) {
    push(a1 + a2, 'full');
    const m = a2.match(/^[0-9\-\s丁目番地号の]+/);
    const ln = m ? m[0].trim() : '';
    if (ln && ln !== a2) push(a1 + ln, 'number');
  }
  if (a1) push(a1, 'chome');
  return out;
}
async function geocode(a1, a2) {
  for (const { q, acc } of candidates(a1, a2)) {
    try {
      const arr = await fetch(GSI + encodeURIComponent(q)).then((r) => r.json());
      if (Array.isArray(arr) && arr.length) {
        const c = arr[0].geometry.coordinates;
        return { lat: +c[1].toFixed(6), lng: +c[0].toFixed(6), geo: acc };
      }
    } catch (e) { /* 次の候補へ */ }
  }
  return { lat: null, lng: null, geo: 'none' };
}

// ===== IndexedDB（更新後データの保存） =====
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open('oitapay-map', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('kv');
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
async function idbGet(k) {
  try {
    const db = await idb();
    return await new Promise((res) => {
      const t = db.transaction('kv').objectStore('kv').get(k);
      t.onsuccess = () => res(t.result); t.onerror = () => res(undefined);
    });
  } catch { return undefined; }
}
async function idbSet(k, v) {
  try {
    const db = await idb();
    return await new Promise((res, rej) => {
      const t = db.transaction('kv', 'readwrite').objectStore('kv').put(v, k);
      t.onsuccess = () => res(); t.onerror = () => rej(t.error);
    });
  } catch { /* 保存失敗は致命的でない */ }
}

// ===== 地図 =====
function isDark() { return matchMedia('(prefers-color-scheme: dark)').matches; }

function initMap() {
  map = L.map('map', { zoomControl: true, attributionControl: true, tap: true })
    .setView(OITA_CENTER, 13);
  map.zoomControl.setPosition('topleft');
  const url = isDark()
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
  L.tileLayer(url, {
    maxZoom: 19, subdomains: 'abcd',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);

  cluster = L.markerClusterGroup({
    maxClusterRadius: 52,
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
    chunkedLoading: true,
    iconCreateFunction: (c) => {
      const n = c.getChildCount();
      const size = n < 10 ? 38 : n < 50 ? 46 : n < 200 ? 54 : 62;
      const bg = n < 10 ? '#34c759' : n < 50 ? '#007aff' : n < 200 ? '#ff9500' : '#ff3b30';
      return L.divIcon({
        html: `<div class="cluster" style="width:${size}px;height:${size}px;background:${bg}">${n}</div>`,
        className: '', iconSize: [size, size],
      });
    },
  });
  map.addLayer(cluster);
}

function makeMarker(s) {
  const { color, emoji } = catOf(s.store_category_major_name);
  const icon = L.divIcon({
    className: 'mk',
    iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -14],
    html: `<div style="width:26px;height:26px;border-radius:50%;background:${color};border:2px solid #fff;
      box-shadow:0 2px 4px rgba(0,0,0,.35);display:grid;place-items:center;font-size:13px;line-height:1">${emoji}</div>`,
  });
  const m = L.marker([s.lat, s.lng], { icon, title: s.store_name });
  m.on('click', () => openSheet(s));
  return m;
}

function buildMarkers() {
  cluster.clearLayers();
  markersById.clear();
  for (const s of stores) {
    if (s.lat == null || s.lng == null) continue;
    markersById.set(s.store_id, makeMarker(s));
  }
}

// ===== 絞り込み =====
function matchStore(s) {
  if (filters.majors.size && !filters.majors.has(s.store_category_major_name)) return false;
  if (filters.minor && s.store_category_minor_name !== filters.minor) return false;
  if (filters.digital && !s.digital_coupon) return false;
  if (filters.size === 'small' && !s.is_small_store) return false;
  if (filters.size === 'large' && s.is_small_store) return false;
  if (filters.q) {
    const hay = norm(`${s.store_name} ${s.store_name_kana} ${s.address_1} ${s.address_2} ${s.store_category_minor_name} ${s.store_category_major_name}`);
    for (const term of filters.q.split(/\s+/)) if (term && !hay.includes(term)) return false;
  }
  return true;
}

// ===== AIでおすすめ（フリーテキスト→条件） =====
// Claude が返した条件で各店をスコアリング。カテゴリ・業種一致を主、キーワードを従に加点する。
function aiScoreOf(s) {
  const c = aiCriteria;
  let score = 0;
  const catHit = c.categories.length && c.categories.includes(s.store_category_major_name);
  if (catHit) score += 3;
  const minor = norm(s.store_category_minor_name);
  let genreHit = false;
  for (const g of c.genres) {
    const head = norm((g || '').split('・')[0]); // 「和食・すし・割烹」→「和食」で部分一致
    if (head && (minor.includes(head) || head.includes(minor))) { score += 4; genreHit = true; break; }
  }
  let kwHit = false;
  if (c.keywords.length) {
    const hay = norm(`${s.store_name} ${s.store_name_kana} ${s.store_category_minor_name} ${s.address_1} ${s.address_2}`);
    for (const k of c.keywords) {
      const kn = norm(k);
      if (kn && kn.length >= 2 && hay.includes(kn)) { score += 2; kwHit = true; }
    }
  }
  s._catHit = catHit; s._genreHit = genreHit; s._kwHit = kwHit;
  return score;
}
function aiMatch(s, relax) {
  const c = aiCriteria;
  // 対応(デジタル/紙)・規模の絞り込み（AIが明示したときだけ）
  if (c.payment === 'digital' && !s.digital_coupon) return false;
  if (c.payment === 'paper' && !s.paper_coupon) return false;
  if (c.size === 'small' && !s.is_small_store) return false;
  if (c.size === 'large' && s.is_small_store) return false;
  const score = aiScoreOf(s);
  s._ai = score;
  // 通常は「業種/キーワード一致」に絞って“おすすめ感”を出す。relax時はカテゴリ一致まで広げる（0件回避）。
  const hasGK = c.genres.length || c.keywords.length;
  if (relax) return c.categories.length ? s._catHit : score > 0;
  if (hasGK) return s._genreHit || s._kwHit;
  if (c.categories.length) return s._catHit;
  return true;
}

async function aiRecommend() {
  const q = ($('#search').value || '').trim();
  if (!q) { $('#search').focus(); toast('やりたいこと（例：家族でランチ）を入力してください'); return; }
  if (aiLoading) return;
  aiLoading = true;
  const btn = $('#aiBtn'); if (btn) btn.classList.add('loading');
  try {
    const res = await fetch(RECOMMEND_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: q.slice(0, 200) }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.message || json.error || 'おすすめの取得に失敗しました');
    aiCriteria = {
      categories: Array.isArray(json.categories) ? json.categories : [],
      genres: Array.isArray(json.genres) ? json.genres : [],
      keywords: Array.isArray(json.keywords) ? json.keywords : [],
      payment: json.payment || 'any',
      size: json.size || 'any',
      reason: String(json.reason || ''),
      query: q,
    };
    aiActive = true;
    track('ai_recommend', { q });
    applyFilters();
    setView('list');
    $('#listView').scrollTop = 0;
  } catch (e) {
    toast(e instanceof Error ? e.message : 'おすすめの取得に失敗しました');
  } finally {
    aiLoading = false;
    if (btn) btn.classList.remove('loading');
  }
}
function clearAi() {
  aiActive = false; aiCriteria = null;
  applyFilters();
}

// リストの距離は「地図の中心」基準（いま見ている場所から近い順）
function rankByCenter() {
  const c = map.getCenter();
  const ref = { lat: c.lat, lng: c.lng };
  for (const s of filtered) s._d = (s.lat != null) ? distM(ref, s) : Infinity;
  filtered.sort((a, b) => a._d - b._d);
}

function applyFilters() {
  if (aiActive && aiCriteria) {
    filtered = stores.filter((s) => aiMatch(s, false));
    if (!filtered.length) filtered = stores.filter((s) => aiMatch(s, true)); // 0件ならカテゴリまで緩める
    const c = map.getCenter(); const ref = { lat: c.lat, lng: c.lng };
    for (const s of filtered) s._d = (s.lat != null) ? distM(ref, s) : Infinity;
    filtered.sort((a, b) => (b._ai - a._ai) || (a._d - b._d)); // スコア優先、近い順は同点時
  } else {
    filtered = stores.filter(matchStore);
    rankByCenter();
  }
  // 地図のマーカー更新
  const layers = [];
  for (const s of filtered) { const m = markersById.get(s.store_id); if (m) layers.push(m); }
  cluster.clearLayers();
  cluster.addLayers(layers);
  // カウント
  const f = filtered.length, t = stores.length;
  $('#count').textContent = (f === t)
    ? `加盟店マップ・${t.toLocaleString()}件`
    : `該当 ${f.toLocaleString()}件 / 全${t.toLocaleString()}件`;
  // リスト
  listLimit = 80;
  renderList();
}

// ===== リスト描画（スクロールで追加読み込み） =====
const CHEV = '<span class="chev"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg></span>';
// シート上部の固定ヘッダー（ハンドル＋閉じるボタン）
const SHEET_HEAD = '<div class="sheet-head"><div class="grab"></div><button class="sheet-close" aria-label="閉じる"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>';

function renderList() {
  const el = $('#listView');
  if (!filtered.length) {
    el.innerHTML = `<div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
      <p>該当するお店がありません</p></div>`;
    return;
  }
  const hint = aiActive ? `「${esc(aiCriteria.query)}」のおすすめ順` : '地図の中心から近い順';
  const banner = (aiActive && aiCriteria)
    ? `<div class="ai-banner">
        <div class="ai-banner-top"><span class="ai-spark">✨</span><b>AIのおすすめ</b><button class="ai-clear" id="aiClear">解除</button></div>
        ${aiCriteria.reason ? `<p class="ai-reason">${esc(aiCriteria.reason)}</p>` : ''}
        <div class="ai-tags">${[...aiCriteria.categories, ...aiCriteria.genres.map((g) => g.split('・')[0])].slice(0, 8).map((t) => `<span class="ai-tag">${esc(t)}</span>`).join('')}</div>
        <div class="ai-note">該当 ${filtered.length.toLocaleString()}件・最新/正確な情報は<a href="https://2026.oita-pay.jp/" target="_blank" rel="noopener">公式</a>で確認を</div>
      </div>`
    : '';
  const slice = filtered.slice(0, listLimit);
  const rows = slice.map((s) => {
    const { color, emoji } = catOf(s.store_category_major_name);
    const dist = (s._d != null && s._d !== Infinity) ? `<div class="dist">${fmtDist(s._d)}${CHEV}</div>` : `<div class="dist">${CHEV}</div>`;
    const sz = sizeInfo(s);
    return `<div class="row" data-id="${s.store_id}">
      <div class="pin" style="background:${color}">${emoji}</div>
      <div class="info">
        <div class="name">${esc(s.store_name)}</div>
        <div class="meta"><span class="tag ${sz.cls}">${sz.label}</span><span class="cat">${esc(s.store_category_minor_name || s.store_category_major_name)}</span>${s.business_hours ? `<span>${esc(s.business_hours)}</span>` : ''}</div>
        <div class="addr">${esc(s.address_1 + s.address_2)}</div>
      </div>${dist}</div>`;
  }).join('');
  const more = filtered.length > listLimit
    ? `<div class="list-hint" id="moreSentinel">あと ${(filtered.length - listLimit).toLocaleString()} 件…</div>`
    : `<div class="list-foot">大分市プレミアム付き商品券2026 加盟店マップ<br>制作 <a href="https://plan8.jp" target="_blank" rel="noopener">plan8</a> ・ 非公式ツール</div>`;
  el.innerHTML = `${banner}<div class="list-hint">${hint}</div>${rows}${more}`;
}

function esc(s) {
  return (s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function safeUrl(u) {
  try { const x = new URL(u); return (x.protocol === 'http:' || x.protocol === 'https:') ? x.href : ''; }
  catch { return ''; }
}
// Google Analytics イベント（未設定なら何もしない）
function track(name, params) { try { if (window.gtag) window.gtag('event', name, params || {}); } catch (e) { } }

// ===== 詳細シート =====
let sheetStore = null;
function openSheet(s) {
  sheetStore = s;
  const { color } = catOf(s.store_category_major_name);
  const dist = (userPos && s.lat != null) ? `（現在地から ${fmtDist(distM(userPos, s))}）` : '';
  const tel = (s.tel_no || '').replace(/[^\d]/g, '');
  const rows = [];
  rows.push(detailRow(ICON.pin, '住所', esc(s.address_1 + s.address_2) + (dist ? `<span style="color:var(--text-3)"> ${dist}</span>` : '')));
  if (s.business_hours) rows.push(detailRow(ICON.clock, '営業時間', esc(s.business_hours)));
  if (s.closed_day) rows.push(detailRow(ICON.cal, '定休日', esc(s.closed_day)));
  if (tel) rows.push(detailRow(ICON.phone, '電話', `<a class="dl-v" href="tel:${tel}">${esc(s.tel_no)}</a>`));
  const url = safeUrl(s.store_url);
  if (url) rows.push(detailRow(ICON.web, 'サイト', `<a class="dl-v" href="${esc(url)}" target="_blank" rel="noopener">公式サイトを開く</a>`));

  const sz = sizeInfo(s);
  const cats = `<span class="s-cat" style="background:${color}">${esc(s.store_category_major_name)}</span>` +
    `<span class="s-cat" style="background:${sz.cls === 'small' ? '#1494ad' : '#8e8e93'}">${sz.label}</span>` +
    (s.store_category_minor_name ? `<span class="s-cat minor">${esc(s.store_category_minor_name)}</span>` : '') +
    (s.digital_coupon ? `<span class="s-cat" style="background:#5856d6">デジタル対応</span>` : '');
  const sizeNote = `<div class="size-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5h.01"/></svg><span>この店舗は<b>${sz.label}</b>です。利用できる券種は <a href="https://2026.oita-pay.jp/" target="_blank" rel="noopener">公式サイト</a>でご確認ください。</span></div>`;

  const approx = (s.geo && s.geo !== 'full' && s.geo !== 'number')
    ? `<div class="approx-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>地図上の位置はおおよそ（丁目の中心）です</div>` : '';

  const mapsHref = mapsUrl(s.lat, s.lng);
  const actions = `<div class="actions">
    ${s.lat != null ? `<a class="act-btn" href="${mapsHref}" target="_blank" rel="noopener">${ICON.route}ルート案内</a>` : ''}
    ${tel ? `<a class="act-btn sec" href="tel:${tel}">${ICON.phone2}電話する</a>` : ''}
    <button class="act-btn sec" id="showOnMap">${ICON.mapPin}地図で見る</button>
  </div>`;

  $('#sheet').innerHTML = `${SHEET_HEAD}
    <div class="s-cats">${cats}</div>
    <h2>${esc(s.store_name)}</h2>
    ${s.store_name_kana ? `<div class="kana">${esc(s.store_name_kana)}</div>` : ''}
    ${approx}
    ${sizeNote}
    <div class="detail-list">${rows.join('')}</div>
    ${actions}`;
  $('#showOnMap') && $('#showOnMap').addEventListener('click', () => { closeSheet(); focusStore(s); });
  $('#sheet').classList.add('show');
  $('#sheetBackdrop').classList.add('show');
  track('view_store', { store_name: s.store_name, category: s.store_category_major_name });
}
function detailRow(icon, k, v) {
  return `<div class="detail-row"><span class="dl-ic">${icon}</span><div><div class="dl-k">${k}</div><div class="dl-v">${v}</div></div></div>`;
}
function closeSheet() { $('#sheet').classList.remove('show'); $('#sheetBackdrop').classList.remove('show'); }

function openAbout() {
  const upd = (dataMeta && dataMeta.updatedAt)
    ? new Date(dataMeta.updatedAt).toLocaleString('ja-JP', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '初期データ（同梱）';
  const rows = [
    detailRow(ICON.build, '制作', `<a class="dl-v" href="https://plan8.jp" target="_blank" rel="noopener">株式会社plan8</a><div style="font-size:12.5px;color:var(--text-3);margin-top:2px">つながりデザインカンパニー／大分県由布市</div>`),
    detailRow(ICON.data, '加盟店データ', `<a class="dl-v" href="https://2026.oita-pay.jp/" target="_blank" rel="noopener">大分市プレミアム付き商品券事業（公式）</a>`),
    detailRow(ICON.clock, '最終更新', esc(upd) + `<div style="font-size:12.5px;color:var(--text-3);margin-top:2px">右上の ⟳ で最新の加盟店を取得できます</div>`),
    detailRow(ICON.web, '地図・位置情報', 'OpenStreetMap / CARTO / 国土地理院'),
  ];
  $('#sheet').innerHTML = `${SHEET_HEAD}
    <h2>大分市プレミアム付き商品券2026<br><span style="font-size:16px;color:var(--text-2);font-weight:600">加盟店マップ</span></h2>
    <div class="kana">加盟店を地図で探せる非公式マップです。最新・正確な情報は必ず公式サイトでご確認ください。</div>
    <div class="detail-list">${rows.join('')}</div>
    <div class="actions">
      <a class="act-btn" href="https://2026.oita-pay.jp/" target="_blank" rel="noopener">${ICON.web}公式サイト</a>
      <a class="act-btn sec" href="https://plan8.jp" target="_blank" rel="noopener">${ICON.build}plan8を見る</a>
    </div>
    <div class="about-foot">© 2026 plan8 ・ 非公式ツール</div>`;
  $('#sheet').classList.add('show');
  $('#sheetBackdrop').classList.add('show');
  track('about_open');
}

// Google マップの経路案内（現在地 → 店舗の座標）。スマホではGoogle Mapsアプリが開く。
function mapsUrl(lat, lng) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`;
}

function focusStore(s) {
  setView('map');
  map.setView([s.lat, s.lng], 18, { animate: true });
  const m = markersById.get(s.store_id);
  if (m) setTimeout(() => { try { cluster.zoomToShowLayer(m, () => m.fire('click')); } catch { openSheet(s); } }, 350);
}

// 静的な一覧/カテゴリページからの遷移を受ける。
//  - /#store=<store_id> … その店を地図で開く（一覧ページの店名リンク）
//  - /?q=<検索語>        … 検索語で絞り込んで一覧表示（WebSite SearchAction の着地）
function handleDeepLink() {
  try {
    const q = new URLSearchParams(location.search).get('q');
    if (q) {
      $('#search').value = q;
      $('#searchClear').classList.add('show');
      filters.q = norm(q).trim();
      applyFilters();
      setView('list');
    }
    const m = (location.hash || '').match(/store=([^&]+)/);
    if (m) {
      const id = decodeURIComponent(m[1]);
      const s = stores.find((x) => x.store_id === id);
      if (s) { (s.lat != null) ? focusStore(s) : openSheet(s); }
    }
  } catch (e) { /* noop */ }
}

// ===== 現在地 =====
function locate() {
  if (!navigator.geolocation) { toast('この端末では現在地を取得できません'); return; }
  const fab = $('#locFab'); fab.classList.add('locating');
  navigator.geolocation.getCurrentPosition(
    (p) => {
      fab.classList.remove('locating');
      userPos = { lat: p.coords.latitude, lng: p.coords.longitude };
      if (meMarker) map.removeLayer(meMarker);
      meMarker = L.marker([userPos.lat, userPos.lng], {
        icon: L.divIcon({ className: '', html: '<div class="me-dot"></div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
        zIndexOffset: 1000, interactive: false,
      }).addTo(map);
      map.setView([userPos.lat, userPos.lng], 15, { animate: true });
      applyFilters();
      toast('現在地を中心に表示しました');
      track('use_location');
    },
    (err) => {
      fab.classList.remove('locating');
      toast(err.code === 1 ? '位置情報が許可されていません' : '現在地を取得できませんでした');
    },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 }
  );
}

// ===== 更新（最新データ取得 → 新規のみジオコーディング → 保存） =====
async function update() {
  const btn = $('#refreshBtn'); btn.classList.add('spinning');
  showModal('<div class="spinner"></div>', '最新の加盟店データを取得中…', '');
  try {
    const fresh = await fetch(SRC, { cache: 'no-store' }).then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status); return r.json();
    }).then((j) => j.data);

    const cur = new Map(stores.map((s) => [s.store_id, s]));
    const freshIds = new Set(fresh.map((s) => s.store_id));
    const merged = [];
    const todo = []; // 新規 or 住所変更 → 要ジオコーディング
    for (const f of fresh) {
      const c = cur.get(f.store_id);
      if (c && c.lat != null && c.address_1 === f.address_1 && c.address_2 === f.address_2) {
        merged.push(Object.assign({}, f, { lat: c.lat, lng: c.lng, geo: c.geo }));
      } else {
        const rec = Object.assign({}, f, { lat: null, lng: null, geo: 'pending' });
        merged.push(rec); todo.push(rec);
      }
    }
    const removed = stores.filter((s) => !freshIds.has(s.store_id)).length;
    const added = todo.filter((r) => !cur.has(r.store_id)).length;
    const changed = todo.length - added;

    for (let i = 0; i < todo.length; i++) {
      modalProgress(i, todo.length, `新しいお店の位置を取得中… ${i + 1}/${todo.length}`);
      const g = await geocode(todo[i].address_1, todo[i].address_2);
      Object.assign(todo[i], g);
      await new Promise((r) => setTimeout(r, 110)); // 国土地理院への配慮
    }

    stores = merged;
    dataMeta = { updatedAt: Date.now(), count: stores.length, baseVersion: DATA_VERSION };
    await idbSet('dataset', stores);
    await idbSet('meta', dataMeta);
    track('update_data', { added, changed, removed });

    buildMarkers();
    rebuildMinorOptions();
    applyFilters();

    const parts = [];
    if (added) parts.push(`新規 ${added}件`);
    if (changed) parts.push(`移転等 ${changed}件`);
    if (removed) parts.push(`掲載終了 ${removed}件`);
    showDoneModal(parts.length ? parts.join(' ・ ') : '変更はありませんでした', stores.length);
  } catch (e) {
    showDoneModal('更新に失敗しました（通信環境をご確認ください）', null, true);
    console.error(e);
  } finally {
    btn.classList.remove('spinning');
  }
}

// ===== モーダル / トースト =====
function showModal(top, title, sub) {
  $('#modal').innerHTML = `${top}<h3>${title}</h3><p id="modalSub">${sub || ''}</p><div class="progress"><div class="bar" id="modalBar"></div></div>`;
  $('#modalBackdrop').classList.add('show');
}
function modalProgress(i, n, sub) {
  const bar = $('#modalBar'), s = $('#modalSub');
  if (bar) bar.style.width = `${n ? Math.round((i / n) * 100) : 0}%`;
  if (s) s.textContent = sub;
}
function showDoneModal(msg, count, err) {
  const ic = err
    ? `<div class="done-ic" style="color:#ff3b30"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/></svg></div>`
    : `<div class="done-ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg></div>`;
  $('#modal').innerHTML = `${ic}<h3>${err ? 'エラー' : '更新しました'}</h3><p>${msg}${count ? `<br>現在 ${count.toLocaleString()} 件を掲載中` : ''}</p><button class="close" id="modalClose">閉じる</button>`;
  $('#modalClose').addEventListener('click', () => $('#modalBackdrop').classList.remove('show'));
}
let toastT;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 2600);
}

// ===== ビュー切替 =====
function setView(v) {
  view = v;
  $('#listView').classList.toggle('show', v === 'list');
  $('#locFab').style.display = v === 'map' ? 'grid' : 'none';
  $('#seg').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  if (v === 'map') {
    setTimeout(() => map.invalidateSize(), 60);
  } else {
    // リストを開くたびに、その時点の地図中心から並べ直す
    listLimit = 80;
    rankByCenter();
    renderList();
    $('#listView').scrollTop = 0;
  }
}

// ===== カテゴリチップ / 業種セレクト =====
function buildChips() {
  const counts = {};
  for (const s of stores) counts[s.store_category_major_name] = (counts[s.store_category_major_name] || 0) + 1;
  const el = $('#chips');
  let html = `<button class="chip c-all active" data-major="">すべて</button>`;
  for (const name of CAT_ORDER) {
    if (!counts[name]) continue;
    html += `<button class="chip" data-major="${name}" style="--c:${CATS[name].color}">
      <span class="dot" style="background:${CATS[name].color}"></span>${CATS[name].emoji} ${name}</button>`;
  }
  el.innerHTML = html;
  el.querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => onChip(c)));
}
function onChip(c) {
  aiActive = false; aiCriteria = null; // カテゴリ操作＝通常絞り込み
  const major = c.dataset.major;
  if (major === '') { filters.majors.clear(); }
  else {
    filters.majors.has(major) ? filters.majors.delete(major) : filters.majors.add(major);
  }
  // 見た目更新
  $('#chips').querySelectorAll('.chip').forEach((el) => {
    const m = el.dataset.major;
    const on = m === '' ? filters.majors.size === 0 : filters.majors.has(m);
    el.classList.toggle('active', on);
    el.style.background = (on && m) ? CATS[m].color : '';
  });
  filters.minor = ''; rebuildMinorOptions();
  applyFilters();
}
function rebuildMinorOptions() {
  const sel = $('#minorSelect');
  const set = new Map();
  for (const s of stores) {
    if (filters.majors.size && !filters.majors.has(s.store_category_major_name)) continue;
    const k = s.store_category_minor_name; if (k) set.set(k, (set.get(k) || 0) + 1);
  }
  const opts = [...set.entries()].sort((a, b) => b[1] - a[1]);
  sel.innerHTML = `<option value="">すべての業種</option>` +
    opts.map(([k, v]) => `<option value="${esc(k)}">${esc(k)}（${v}）</option>`).join('');
  sel.value = filters.minor;
}

// ===== アイコン =====
const ICON = {
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="2.6"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"/></svg>',
  web: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z"/></svg>',
  route: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l18-8-8 18-2-8-8-2z"/></svg>',
  phone2: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"/></svg>',
  mapPin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="2.6"/></svg>',
  build: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2 4.5L18.5 9 15 12l1 5-4-2.5L8 17l1-5L5.5 9 10 7.5 12 3z"/></svg>',
  data: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
};

// ===== イベント =====
function wire() {
  $('#seg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setView(b.dataset.view); });
  $('#locFab').addEventListener('click', locate);
  $('#refreshBtn').addEventListener('click', update);
  $('#aboutBtn').addEventListener('click', openAbout);
  $('#aiBtn') && $('#aiBtn').addEventListener('click', aiRecommend);
  $('#creditLink').addEventListener('click', () => track('credit_click'));
  $('#sheetBackdrop').addEventListener('click', closeSheet);

  // 閉じる：×ボタン / ハンドルのタップ
  $('#sheet').addEventListener('click', (e) => {
    if (e.target.closest('.sheet-close') || e.target.closest('.grab')) closeSheet();
  });
  // 閉じる：ヘッダーを下にスワイプ
  const sheet = $('#sheet');
  let dy = null, y0 = 0;
  sheet.addEventListener('touchstart', (e) => {
    if (!e.target.closest('.sheet-head')) { dy = null; return; }
    y0 = e.touches[0].clientY; dy = 0; sheet.style.transition = 'none';
  }, { passive: true });
  sheet.addEventListener('touchmove', (e) => {
    if (dy === null) return;
    const d = e.touches[0].clientY - y0;
    if (d > 0) { dy = d; sheet.style.transform = `translateY(${d}px)`; }
  }, { passive: true });
  sheet.addEventListener('touchend', () => {
    if (dy === null) return;
    sheet.style.transition = ''; sheet.style.transform = '';
    if (dy > 90) closeSheet();
    dy = null;
  });

  let qT;
  $('#search').addEventListener('input', (e) => {
    const v = e.target.value;
    $('#searchClear').classList.toggle('show', !!v);
    clearTimeout(qT); qT = setTimeout(() => {
      aiActive = false; aiCriteria = null; // 手入力＝通常検索（AIモードを抜ける）
      filters.q = norm(v).trim(); applyFilters();
    }, 180);
  });
  // Enterキーでも「AIでおすすめ」を実行（入力途中の通常検索は維持）
  $('#search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); aiRecommend(); } });
  $('#searchClear').addEventListener('click', () => {
    $('#search').value = ''; filters.q = ''; aiActive = false; aiCriteria = null;
    $('#searchClear').classList.remove('show'); applyFilters(); $('#search').focus();
  });

  $('#advToggle').addEventListener('click', () => {
    $('#advToggle').classList.toggle('open'); $('#advPanel').classList.toggle('open');
  });
  $('#minorSelect').addEventListener('change', (e) => { aiActive = false; aiCriteria = null; filters.minor = e.target.value; applyFilters(); });
  $('#sizeSelect').addEventListener('change', (e) => { aiActive = false; aiCriteria = null; filters.size = e.target.value; track('filter_size', { size: e.target.value }); applyFilters(); });
  $('#digitalOnly').addEventListener('change', (e) => { aiActive = false; aiCriteria = null; filters.digital = e.target.checked; applyFilters(); });

  // 非公式の注意書き（×で閉じたら記憶）
  try { if (localStorage.getItem('op26_notice_hidden')) $('#notice').style.display = 'none'; } catch (e) { }
  $('#noticeClose').addEventListener('click', () => {
    $('#notice').style.display = 'none';
    try { localStorage.setItem('op26_notice_hidden', '1'); } catch (e) { }
  });

  $('#listView').addEventListener('click', (e) => {
    if (e.target.closest('#aiClear')) { clearAi(); return; }
    const row = e.target.closest('.row'); if (!row) return;
    const s = stores.find((x) => x.store_id === row.dataset.id); if (s) openSheet(s);
  });
  $('#listView').addEventListener('scroll', () => {
    const el = $('#listView');
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 600 && listLimit < filtered.length) {
      listLimit += 80; renderList();
    }
  });
}

// ===== 起動 =====
async function boot() {
  initMap();
  wire();
  try {
    const saved = await idbGet('dataset');
    if (saved && saved.length) {
      dataMeta = await idbGet('meta');
      // 座標補正版が上がっていたら、保存済みデータの座標をbaselineで再シード（新規店は維持）
      if (!dataMeta || (dataMeta.baseVersion || 0) < DATA_VERSION) {
        try {
          const base = await fetch(BASELINE).then((r) => r.json());
          const bc = new Map(base.map((b) => [b.store_id, b]));
          for (const s of saved) { const b = bc.get(s.store_id); if (b) { s.lat = b.lat; s.lng = b.lng; s.geo = b.geo; } }
          dataMeta = Object.assign({}, dataMeta, { baseVersion: DATA_VERSION });
          await idbSet('dataset', saved);
          await idbSet('meta', dataMeta);
        } catch (e) { /* オフライン時はスキップ */ }
      }
      stores = saved;
    } else {
      stores = await fetch(BASELINE).then((r) => r.json());
    }
  } catch (e) {
    try { stores = await fetch(BASELINE).then((r) => r.json()); }
    catch { toast('データの読み込みに失敗しました'); stores = []; }
  }
  buildChips();
  rebuildMinorOptions();
  buildMarkers();
  applyFilters();
  setView('map');
  handleDeepLink();
  $('#boot').classList.add('hide');
}
boot();
