/* ═══════════════════════════════════════════════════════════════════
   Orbs — logique de l'interface
   ═══════════════════════════════════════════════════════════════════ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const PAGE_SIZE = 60;

/* Journalisation des erreurs JS (fichier debug.log côté Python). */
function reportJsError(message) {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.debug_log) {
      window.pywebview.api.debug_log(String(message));
    }
  } catch (_) { /* ignore */ }
}
window.addEventListener("error", (e) => reportJsError(`JS ERROR: ${e.message} @${e.filename}:${e.lineno}`));
window.addEventListener("unhandledrejection", (e) => reportJsError(`JS REJECT: ${e.reason}`));
document.addEventListener("mousedown", (e) => {
  const el = e.target && e.target.closest ? e.target.closest("[data-nav],[data-tab],.game-card,button") : null;
  reportJsError(`MD ${Math.round(e.clientX)},${Math.round(e.clientY)} dpr=${window.devicePixelRatio} iw=${window.innerWidth} -> ${el ? (el.dataset.nav || "") + "|" + (el.dataset.tab || "") + "|" + el.className : e.target.tagName}`);
}, true);

const state = {
  ready: false,
  settings: {},
  counts: { games: 0, favorites: 0, recents: 0, presets: 0 },
  favorites: new Set(),
  recents: [],
  presets: [],
  discord: { running: false, ipc: false, pipes: [] },
  library: { state: "loading", count: 0, progress: 0 },
  running: null,
  runningGames: [],
  view: "home",
  tab: "all",
  query: "",
  offset: 0,
  items: [],
  hasMore: false,
  loading: false,
  seq: 0,
  selected: null,
  previewTimer: null,
  previewIcon: null,
  previewName: null,
  dataDir: "",
  _countsSig: "",
  tick: 0,
};

/* ─────────────────────────── Utilitaires ─────────────────────────── */
function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function icon(name, cls = "") {
  return `<svg class="ico ${cls}"><use href="#i-${name}"/></svg>`;
}

function fmtNum(n) {
  try { return Number(n || 0).toLocaleString(state.settings.lang === "en" ? "en-US" : "fr-FR"); }
  catch (_) { return String(n || 0); }
}

function fmtTime(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function initials(name) {
  const words = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").trim().split(/\s+/);
  if (!words[0]) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function hashHue(name) {
  let h = 0;
  for (const ch of String(name || "")) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

function api(name, ...args) {
  return new Promise((resolve) => {
    const bridge = window.pywebview && window.pywebview.api;
    if (!bridge || typeof bridge[name] !== "function") {
      resolve({ ok: false, code: "no_api" });
      return;
    }
    try {
      Promise.resolve(bridge[name](...args)).then(resolve).catch((err) => {
        resolve({ ok: false, code: "js_error", message: String(err) });
      });
    } catch (err) {
      resolve({ ok: false, code: "js_error", message: String(err) });
    }
  });
}

/* ─────────────────────────── Toasts ─────────────────────────── */
function toast(title, message = "", kind = "info") {
  const root = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  const ico = kind === "ok" ? "check" : kind === "err" ? "close" : "zap";
  el.innerHTML = `
    <div class="toast-icon">${icon(ico)}</div>
    <div>
      <div class="toast-title">${esc(title)}</div>
      ${message ? `<div class="toast-msg">${esc(message)}</div>` : ""}
    </div>`;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 260);
  }, 4200);
}

/* ─────────────────────────── Navigation ─────────────────────────── */
function navActive(btn) {
  const nav = btn.dataset.nav;
  const tab = btn.dataset.tab || "all";
  if (nav === "favorites") return state.view === "library" && state.tab === "favorites";
  if (nav === "library") return state.view === "library" && state.tab === tab;
  if (nav === "home") return state.view === "home";
  return state.view === nav;
}

function refreshNav() {
  $$("#mainNav .nav-item, .sidebar .nav .nav-item").forEach((btn) => {
    btn.classList.toggle("active", navActive(btn));
  });
  const crumbKey = state.view === "library"
    ? (state.tab === "favorites" ? "favorites" : state.tab === "recents" ? "recents" : "library")
    : state.view;
  $("#crumb").textContent = t("crumb." + crumbKey);
}

function go(view, tab) {
  if (view === "favorites") { view = "library"; tab = "favorites"; }
  if (view === "library" && !tab) tab = "all";

  const changed = state.view !== view || (view === "library" && state.tab !== tab);
  state.view = view;
  if (view === "library") state.tab = tab;

  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === view));
  refreshNav();
  $("#main").scrollTop = 0;

  if (view === "library" && changed) openLibrary(tab);
  if (view === "custom") { renderPresets(); updatePreview(); }
  if (view === "diagnostics") loadDiagnostics();
  if (view === "quests") loadDiscordQuests();
  if (view === "settings") syncSettingsUI();
}

/* ─────────────────────────── Discord / badges ─────────────────────────── */
function renderDiscord() {
  const d = state.discord || {};
  const ok = !!d.ipc;
  const pill = $("#connPill");
  pill.classList.toggle("ok", ok);
  pill.classList.toggle("warn", !ok);
  $("#connText").textContent = ok
    ? (state.settings.lang === "en" ? "Discord connected" : "Discord connecté")
    : (state.settings.lang === "en" ? "Discord offline" : "Discord hors ligne");

  const chip = $("#discordChip");
  chip.classList.toggle("ok", ok);
  chip.classList.toggle("warn", !ok);
  $("#discordChipTitle").textContent = "Discord";
  $("#discordChipSub").textContent = ok
    ? `${t("diag.on")}${d.pipes && d.pipes.length ? " · " + d.pipes[0] : ""}`
    : t("diag.stopped");
}

function updateCounts() {
  const signature = [state.counts.games, state.counts.favorites, state.counts.recents, state.counts.presets,
    state.discord && state.discord.ipc ? 1 : 0].join(":");
  if (signature === state._countsSig) return;
  state._countsSig = signature;
  $("#badgeLibrary").textContent = fmtNum(state.counts.games);
  $("#badgeFavorites").textContent = fmtNum(state.counts.favorites);
  $("#badgeRecents").textContent = fmtNum(state.counts.recents);
  $("#badgePresets").textContent = fmtNum(state.counts.presets);
  $("#tabCountAll").textContent = fmtNum(state.counts.games);
  $("#tabCountFav").textContent = fmtNum(state.counts.favorites);
  $("#tabCountRecent").textContent = fmtNum(state.counts.recents);
  renderHeroPills();
}

function renderHeroPills() {
  const root = $("#heroPills");
  if (!root) return;
  const ok = state.discord && state.discord.ipc;
  root.innerHTML = `
    <span class="pill ${ok ? "ok" : "warn"}"><span class="dot"></span>${
      ok ? (state.settings.lang === "en" ? "Discord connected" : "Discord connecté")
         : (state.settings.lang === "en" ? "Discord offline" : "Discord hors ligne")}</span>
    <span class="pill">${fmtNum(state.counts.games)} ${state.settings.lang === "en" ? "games" : "jeux"}</span>
    <span class="pill">${icon("shield")}${state.settings.lang === "en" ? "100% local" : "100 % local"}</span>`;
}

/* ─────────────────────────── En cours ─────────────────────────── */
function artHTML(item, cls = "") {
  if (!item) return `<div class="${cls}">${icon("grid")}</div>`;
  if (item.banner && item.kind !== "icon") return `<div class="${cls}"><img src="${esc(item.banner)}" alt=""></div>`;
  if (item.icon) return `<div class="${cls}"><img src="${esc(item.icon)}" alt=""></div>`;
  return `<div class="${cls}">${icon("grid")}</div>`;
}

function renderNowPlaying() {
  const root = $("#nowPlaying");
  const games = Array.isArray(state.runningGames) ? state.runningGames.slice() : [];
  if (state.running && state.running.kind === "rpc") games.unshift(state.running);
  else if (!games.length && state.running) games.push(state.running);
  if (!games.length) { root.innerHTML = ""; return; }

  root.innerHTML = games.map((r) => {
    const elapsed = Math.max(0, Math.floor(Date.now() / 1000) - (r.started || 0));
    const art = r.icon
      ? `<img src="${esc(r.icon)}" alt="">`
      : r.banner ? `<img src="${esc(r.banner)}" alt="">` : icon("zap");
    const detail = [r.details, r.state].filter(Boolean).join(" · ");
    const isProcess = r.kind === "process";
    const stop = isProcess
      ? `<button class="btn btn--danger" data-stop-game="${esc(r.gameId)}">${icon("stop")}<span>${t("now.stop")}</span></button>`
      : `<button class="btn btn--danger" data-stop-presence="1">${icon("stop")}<span>${t("now.stop")}</span></button>`;
    return `
      <div class="now">
        <div class="now-art">${art}</div>
        <div class="now-body">
          <div class="now-kicker"><span class="pulse-dot"></span>${t("now.playing")} · ${isProcess ? t("now.method.process") : t("now.method.rpc")}</div>
          <div class="now-name">${esc(r.name || "—")}</div>
          <div class="now-meta">${esc(detail || (r.appId ? "App ID " + r.appId : (r.exe || "")))}</div>
        </div>
        <div class="now-timer" data-now-timer data-started="${Number(r.started) || 0}">${fmtTime(elapsed)}</div>
        ${stop}
      </div>`;
  }).join("");

  $$("[data-stop-game]", root).forEach((button) => {
    button.onclick = () => stopGame(button.dataset.stopGame);
  });
  $$("[data-stop-presence]", root).forEach((button) => {
    button.onclick = stopPresence;
  });
}

function tickTimer() {
  state.tick++;
  $$("[data-now-timer]").forEach((timer) => {
    const started = Number(timer.dataset.started) || 0;
    timer.textContent = fmtTime(Math.max(0, Math.floor(Date.now() / 1000) - started));
  });
  const pv = $("#pvTime");
  if (pv) {
    const hours = Math.max(0, Math.min(87600, Number(state.settings.playtime_hours) || 0));
    pv.textContent = fmtTime(hours * 3600 + state.tick);
  }
}

/* ─────────────────────────── Récents ─────────────────────────── */
function renderRecents() {
  const root = $("#recentRow");
  if (!root) return;
  if (!state.recents.length) {
    root.innerHTML = `<div class="empty-inline">${t("empty.recent")}</div>`;
    return;
  }
  root.innerHTML = state.recents.slice(0, 12).map((r) => {
    const art = r.icon
      ? `<img src="${esc(r.icon)}" alt="">`
      : r.banner ? `<img src="${esc(r.banner)}" alt="">` : icon("grid");
    return `<div class="recent-card" data-recent="${esc(r.id)}">
      <div class="recent-art">${art}</div>
      <div style="min-width:0">
        <div class="recent-name">${esc(r.name || "?")}</div>
        <div class="recent-sub">${esc(r.exe || "App ID " + (r.id || "").slice(-6))}</div>
      </div>
    </div>`;
  }).join("");

  $$("[data-recent]", root).forEach((card) => {
    card.onclick = async () => {
      const id = card.dataset.recent;
      const game = state.recents.find((r) => String(r.id) === String(id));
      if (game && game.appId) { openCustomWith(game); return; }
      const res = await api("get_game", id);
      if (res && res.ok) openGame(res);
      else if (game) openCustomWith({ id: game.id, name: game.name, icon: game.icon, appId: game.id });
    };
  });
}

/* ─────────────────────────── Bibliothèque ─────────────────────────── */
function skeletonGrid(count = 12) {
  $("#grid").innerHTML = Array.from({ length: count }, () => `<div class="skeleton"></div>`).join("");
  $("#gridEmpty").classList.add("hidden");
}

function cardHTML(g) {
  const hue = hashHue(g.name);
  const hasArt = !!g.steam && !!g.portrait;
  const fav = state.favorites.has(String(g.id)) || g.fav;
  const isRunning = state.runningGames.some((item) => String(item.gameId) === String(g.id));
  const exe = g.exe || "";
  const coverInner = hasArt
    ? `<img class="art" loading="lazy" decoding="async" src="${esc(g.portrait)}" alt="" onerror="cardImgError(this)">
       <img class="icon" src="${esc(g.icon || "")}" alt="" style="display:none" onerror="this.remove()">`
    : (g.icon
        ? `<img class="icon" loading="lazy" decoding="async" src="${esc(g.icon)}" alt="" onerror="this.remove()">`
        : `<div class="card-init" style="--hue:${hue}">${esc(initials(g.name))}</div>`);

  return `<article class="game-card" data-id="${esc(g.id)}">
    <div class="card-cover ${hasArt ? "" : "card-cover--icon"}" style="--hue:${hue}">
      <div class="cover-fb" style="--hue:${hue}"><span class="card-init" style="--hue:${hue}">${esc(initials(g.name))}</span></div>
      ${coverInner}
      <div class="card-veil"></div>
      <button class="card-fav ${fav ? "is-fav" : ""}" data-fav="${esc(g.id)}" title="${t("detail.fav")}">${icon("star")}</button>
      <button class="card-play ${isRunning ? "is-running" : ""}" data-play="${esc(g.id)}" title="${t(isRunning ? "common.stop" : "common.launch")}">${icon(isRunning ? "stop" : "play")}</button>
      <span class="card-exe ${exe ? "" : "none"}">${esc(exe || t("card.noExe"))}</span>
    </div>
    <div class="card-info">
      <div class="card-name">${esc(g.name)}</div>
      <div class="card-sub">${g.steam ? "Steam · " + esc(g.steam) : "App ID · " + esc((g.id || "").slice(-6))}</div>
    </div>
  </article>`;
}

function cardImgError(img) {
  const cover = img.closest(".card-cover");
  if (!cover) return;
  img.remove();
  cover.classList.add("card-cover--icon");
  const ic = cover.querySelector("img.icon");
  if (ic) ic.style.display = "block";
  else {
    const fb = cover.querySelector(".cover-fb");
    if (fb) fb.style.display = "grid";
  }
}

async function openLibrary(tab) {
  state.tab = tab || "all";
  state.query = "";
  state.offset = 0;
  state.items = [];
  const input = $("#searchInput");
  input.value = "";
  $(".search-field").classList.remove("has-value");
  $$("#tabs .tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  refreshNav();
  skeletonGrid();
  await fetchPage(true);
}

async function fetchPage(reset) {
  if (state.loading) return;
  state.loading = true;
  if (reset) state.offset = 0;
  const seq = ++state.seq;

  const res = await api("search_games", state.query, state.tab, state.offset, PAGE_SIZE);
  if (seq !== state.seq) { state.loading = false; return; }

  if (!res || !res.items) {
    state.loading = false;
    if (state.library.state === "loading") { skeletonGrid(); return; }
    $("#grid").innerHTML = "";
    $("#gridEmpty").classList.remove("hidden");
    $("#loadMore").classList.add("hidden");
    return;
  }

  const items = res.items;
  if (reset) {
    state.items = items;
    $("#grid").innerHTML = items.map(cardHTML).join("");
  } else {
    state.items = state.items.concat(items);
    $("#grid").insertAdjacentHTML("beforeend", items.map(cardHTML).join(""));
  }
  state.offset = state.items.length;
  state.hasMore = !!res.hasMore;

  if (!state.items.length) {
    const title = state.tab === "favorites" ? t("empty.favorites")
      : state.tab === "recents" ? t("empty.recent")
      : state.query ? t("library.emptyTitle") : t("empty.library");
    $("#gridEmpty h3").textContent = title;
    $("#gridEmpty p").textContent = state.tab === "all" && state.query ? t("library.emptySub") : "";
  }
  $("#gridEmpty").classList.toggle("hidden", state.items.length > 0);
  $("#loadMore").classList.toggle("hidden", !state.hasMore);
  state.loading = false;
}

function bindGrid() {
  const grid = $("#grid");
  grid.addEventListener("click", async (event) => {
    const favBtn = event.target.closest("[data-fav]");
    if (favBtn) {
      event.stopPropagation();
      await toggleFavorite(favBtn.dataset.fav);
      return;
    }
    const playBtn = event.target.closest("[data-play]");
    if (playBtn) {
      event.stopPropagation();
      await quickLaunch(playBtn.dataset.play);
      return;
    }
    const card = event.target.closest(".game-card");
    if (card) openGameById(card.dataset.id);
  });
}

async function toggleFavorite(id) {
  const res = await api("toggle_favorite", String(id));
  if (!res || !res.ok) return;
  if (res.fav) state.favorites.add(String(id)); else state.favorites.delete(String(id));
  state.counts.favorites = res.count;
  $$(`[data-fav="${CSS.escape(String(id))}"]`).forEach((btn) => {
    btn.classList.toggle("is-fav", !!res.fav);
  });
  updateCounts();
  if (state.view === "library" && state.tab === "favorites") fetchPage(true);
  toast(res.fav ? t("toast.fav") : t("toast.unfav"), "", "ok");
}

/* ─────────────────────────── Détail d'un jeu ─────────────────────────── */
async function openGameById(id) {
  const res = await api("get_game", id);
  if (res && res.ok) openGame(res);
}

function openGame(g) {
  state.selected = g;
  const hue = hashHue(g.name);
  const fav = state.favorites.has(String(g.id)) || g.fav;
  const heroArt = g.banner && g.steam;
  const isRunning = state.runningGames.some((item) => String(item.gameId) === String(g.id));
  const root = $("#modalRoot");
  root.innerHTML = `
    <div class="modal-backdrop" data-close="1">
      <div class="modal" role="dialog" aria-modal="true">
        <button class="modal-close" data-close="1" aria-label="${t("common.close")}">${icon("close")}</button>
        <div class="detail-hero ${heroArt ? "" : "no-art"}" ${heroArt ? `style="background-image:url('${esc(g.banner)}')"` : ""}>
          <div class="detail-id">
            <div class="detail-icon">${g.icon ? `<img src="${esc(g.icon)}" alt="">` : `<span class="card-init" style="--hue:${hue}">${esc(initials(g.name))}</span>`}</div>
            <div class="detail-titles">
              <div class="detail-name">${esc(g.name)}</div>
              <div class="detail-badges">
                <span class="chip accent">${t("detail.rpc")}</span>
                <span class="chip">${esc(g.id)}</span>
                ${g.steam ? `<span class="chip">Steam ${esc(g.steam)}</span>` : ""}
              </div>
            </div>
          </div>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="field">
              <span class="field-label">${t("custom.details")}</span>
              <input id="mDetails" maxlength="128" placeholder="${t("detail.detailsPh")}" value="${esc(g.details || "")}">
            </label>
            <label class="field">
              <span class="field-label">${t("custom.state")}</span>
              <input id="mState" maxlength="128" placeholder="${t("detail.statePh")}" value="">
            </label>
          </div>
          <div class="detail-actions">
            ${g.exe ? `<button class="btn btn--primary" id="mLaunch">${icon("cpu")}<span>${isRunning ? t("common.stop") : t("detail.process")}</span></button>` : ""}
            <button class="btn ${g.exe ? "btn--ghost" : "btn--primary"}" id="mPresence">${icon("play")}<span>${t("detail.launch")}</span></button>
            <button class="iconbtn ${fav ? "is-fav" : ""}" id="mFav" title="${t("detail.fav")}" style="${fav ? "color:#ffd36b;border-color:rgba(255,211,107,.35)" : ""}">${icon("star")}</button>
          </div>
          <p class="detail-hint">${g.exe ? `${t("detail.exe")} : <b>${esc(g.exe)}</b> — ` : ""}${g.exe ? t("detail.hint") : t("detail.noExe")}</p>
        </div>
      </div>
    </div>`;

  const backdrop = $("#modalRoot .modal-backdrop");
  backdrop.addEventListener("click", (e) => {
    const closeTarget = e.target.closest("[data-close]");
    if (closeTarget && (closeTarget.classList.contains("modal-close") || e.target === backdrop)) closeModal();
  });
  $("#mFav").onclick = async () => {
    await toggleFavorite(g.id);
    const nowFav = state.favorites.has(String(g.id));
    $("#mFav").style.color = nowFav ? "#ffd36b" : "";
    $("#mFav").style.borderColor = nowFav ? "rgba(255,211,107,.35)" : "";
  };
  const processButton = $("#mLaunch");
  if (processButton) processButton.onclick = () => launch({
    method: "process", gameId: g.id, name: g.name, exe: g.exe,
    icon: g.icon, banner: g.banner,
  });
  $("#mPresence").onclick = () => launch({
    method: "rpc", gameId: g.id, appId: g.id, name: g.name,
    details: $("#mDetails").value.trim(), state: $("#mState").value.trim(),
    icon: g.icon, banner: g.banner,
  });
}

function closeModal() {
  $("#modalRoot").innerHTML = "";
  state.selected = null;
}

/* ─────────────────────────── Lancement ─────────────────────────── */
async function ensureDiscord() {
  const res = await api("status");
  if (res && res.discord) { state.discord = res.discord; renderDiscord(); renderHeroPills(); }
  if (!state.discord.ipc) {
    toast(t("toast.nodiscord"), t("toast.nodiscordMsg"), "err");
    return false;
  }
  return true;
}

async function launch(payload) {
  if (payload.method !== "process" && !(await ensureDiscord())) return;
  const res = await api("launch", payload);
  if (!res || !res.ok) {
    const code = res && res.code;
    if (code === "invalid_id") toast(t("toast.invalidId"), t("toast.invalidIdMsg"), "err");
    else toast(t("toast.launchFailed"), (res && res.message) || t("toast.error"), "err");
    return;
  }
  state.running = res.running || null;
  state.runningGames = res.runningGames || state.runningGames;
  renderNowPlaying();
  closeModal();
  const label = payload.name || "—";
  toast(res.code === "stopped" ? t("toast.stopped") : t("toast.started"), label, "ok");
  await refreshRecents();
}

async function quickLaunch(id) {
  const g = state.items.find((x) => String(x.id) === String(id));
  if (!g) return;
  if (state.runningGames.some((item) => String(item.gameId) === String(g.id))) {
    await stopGame(g.id);
    return;
  }
  if (g.exe) {
    await launch({ method: "process", gameId: g.id, name: g.name, exe: g.exe, icon: g.icon, banner: g.banner });
  } else {
    await launch({ method: "rpc", gameId: g.id, appId: g.id, name: g.name,
      details: "", state: "", icon: g.icon, banner: g.banner });
  }
}

async function stopGame(gameId) {
  const res = await api("stop_game", String(gameId));
  if (!res || !res.ok) return;
  state.running = res.running || null;
  state.runningGames = res.runningGames || [];
  renderNowPlaying();
  if (state.selected && String(state.selected.id) === String(gameId)) closeModal();
  toast(t("toast.stopped"), res.message || "", "ok");
}

async function stopPresence() {
  const res = await api("stop_presence");
  state.running = res && res.running || null;
  state.runningGames = res && res.runningGames || state.runningGames;
  renderNowPlaying();
  toast(t("toast.stopped"), res && res.message ? res.message : "", "ok");
}

async function refreshRecents() {
  const res = await api("status");
  if (!res) return;
  state.running = res.running;
  state.runningGames = res.runningGames || [];
  renderNowPlaying();
  state.counts.recents = (res.counts && res.counts.recents) || state.counts.recents;
  updateCounts();
  const boot = await api("bootstrap");
  if (boot && boot.recents) { state.recents = boot.recents; renderRecents(); }
}

/* ─────────────────────────── Personnalisé ─────────────────────────── */
function openCustomWith(item) {
  go("custom");
  $("#cAppId").value = item.appId || item.id || "";
  $("#cName").value = item.name || "";
  $("#cDetails").value = "";
  $("#cState").value = "";
  $("#cImage").value = "";
  $("#cImageText").value = "";
  resolvePreview();
}

function updatePreview(name, iconUrl) {
  const appId = ($("#cAppId").value || "").trim();
  const label = ($("#cName").value || "").trim();
  const art = $("#pvArt");
  if (iconUrl !== undefined) {
    state.previewIcon = iconUrl || null;
    state.previewName = name || state.previewName;
  }
  if (state.previewIcon) {
    art.innerHTML = `<img src="${esc(state.previewIcon)}" alt="" onerror="this.remove()">`;
  } else {
    art.innerHTML = `<div class="pv-fallback">${appId ? esc(initials($("#cName").value || "?")) : icon("sparkles")}</div>`;
  }
  $("#pvName").textContent = label || state.previewName || t("custom.unknownApp");
  const details = ($("#cDetails").value || "").trim();
  $("#pvDetails").textContent = details || t("detail.detailsPh");
  const st = ($("#cState").value || "").trim();
  $("#pvState").textContent = st;
  $("#pvState").style.display = st ? "block" : "none";
}

let previewSeq = 0;
async function resolvePreview() {
  const appId = ($("#cAppId").value || "").trim();
  const seq = ++previewSeq;
  state.previewIcon = null;
  state.previewName = null;
  if (!/^\d{10,}$/.test(appId)) { updatePreview(null, null); return; }
  const res = await api("resolve_app", appId);
  if (seq !== previewSeq) return;
  if (res && res.found) {
    const nameInput = $("#cName");
    if (!nameInput.value.trim() && res.name) nameInput.value = res.name;
    updatePreview(res.name, res.icon || null);
  } else {
    updatePreview(null, null);
  }
}

function bindCustomForm() {
  const form = $("#customForm");
  const ids = ["cAppId", "cName", "cDetails", "cState", "cImage", "cImageText"];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener("input", () => {
      updatePreview();
      if (id === "cAppId") {
        clearTimeout(state.previewTimer);
        state.previewTimer = setTimeout(resolvePreview, 600);
      }
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const appId = $("#cAppId").value.trim();
    if (!/^\d{10,}$/.test(appId)) { toast(t("toast.invalidId"), t("toast.invalidIdMsg"), "err"); return; }
    if (!(await ensureDiscord())) return;
    const res = await api("launch", {
      method: "rpc", appId, gameId: null,
      name: $("#cName").value.trim() || t("custom.unknownApp"),
      details: $("#cDetails").value.trim(),
      state: $("#cState").value.trim(),
      largeImage: $("#cImage").value.trim(),
      largeText: $("#cImageText").value.trim(),
      icon: null,
    });
    if (!res || !res.ok) { toast(t("toast.launchFailed"), (res && res.message) || "", "err"); return; }
    state.running = res.running;
    renderNowPlaying();
    toast(t("toast.started"), $("#cName").value.trim(), "ok");
    await refreshRecents();
  });

  $("#savePreset").onclick = async () => {
    const payload = {
      name: $("#cName").value.trim(),
      appId: $("#cAppId").value.trim(),
      details: $("#cDetails").value.trim(),
      state: $("#cState").value.trim(),
      largeImage: $("#cImage").value.trim(),
      largeText: $("#cImageText").value.trim(),
    };
    if (!payload.name) { toast(t("toast.error"), t("custom.label"), "err"); return; }
    const res = await api("save_preset", payload);
    if (!res || !res.ok) { toast(t("toast.error"), (res && res.code) || "", "err"); return; }
    state.presets = res.presets;
    state.counts.presets = state.presets.length;
    updateCounts();
    renderPresets();
    toast(t("toast.presetSaved"), payload.name, "ok");
  };
}

function renderPresets() {
  const root = $("#presetGrid");
  if (!root) return;
  if (!state.presets.length) {
    root.innerHTML = `<div class="empty-inline">${t("custom.emptyPresets")}</div>`;
    return;
  }
  root.innerHTML = state.presets.map((p) => `
    <div class="preset-card" data-preset="${esc(p.id)}">
      <div class="preset-art">${p.icon ? `<img src="${esc(p.icon)}" alt="">` : icon("sparkles")}</div>
      <div style="min-width:0">
        <div class="preset-name">${esc(p.name)}</div>
        <div class="preset-sub">${esc(p.details || "App ID " + p.appId)}</div>
      </div>
      <div class="preset-actions">
        <button class="iconbtn" data-preset-play="${esc(p.id)}" title="${t("common.launch")}">${icon("play")}</button>
        <button class="iconbtn" data-preset-del="${esc(p.id)}" title="${t("common.delete")}">${icon("trash")}</button>
      </div>
    </div>`).join("");

  $$("[data-preset-play]", root).forEach((btn) => {
    btn.onclick = async () => {
      const preset = state.presets.find((p) => p.id === btn.dataset.presetPlay);
      if (!preset) return;
      if (!(await ensureDiscord())) return;
      const res = await api("launch", {
        method: "rpc", appId: preset.appId, name: preset.name,
        details: preset.details, state: preset.state,
        largeImage: preset.largeImage, largeText: preset.largeText,
        icon: preset.icon,
      });
      if (!res || !res.ok) { toast(t("toast.launchFailed"), (res && res.message) || "", "err"); return; }
      state.running = res.running;
      renderNowPlaying();
      toast(t("toast.started"), preset.name, "ok");
      await refreshRecents();
    };
  });

  $$("[data-preset-del]", root).forEach((btn) => {
    btn.onclick = async () => {
      const res = await api("delete_preset", btn.dataset.presetDel);
      if (res && res.ok) {
        state.presets = res.presets;
        state.counts.presets = state.presets.length;
        updateCounts();
        renderPresets();
        toast(t("toast.presetDeleted"), "", "ok");
      }
    };
  });
}

/* ─────────────────────────── Diagnostic ─────────────────────────── */
async function loadDiscordQuests() {
  const status = $("#questsStatus");
  const stats = $("#questsStats");
  const list = $("#questsList");
  status.textContent = t("quests.reading");
  stats.innerHTML = "";
  list.innerHTML = "";
  const res = await api("discord_quest_snapshot");
  if (!res || !res.ok) {
    status.textContent = t(res && res.code === "discord_window_not_found" ? "quests.discordMissing" : "quests.prompt");
    return;
  }
  status.textContent = t("quests.updated");
  const cards = [[t("quests.balance"), res.balance == null ? "—" : res.balance, "Orbs"], [t("quests.completed"), fmtNum(res.completed), ""], [t("quests.pending"), fmtNum(res.pending), ""]];
  stats.innerHTML = cards.map(([label, value, sub]) => `<div class="stat"><div class="stat-label">${esc(label)}</div><div class="stat-value">${esc(value)}</div>${sub ? `<div class="stat-sub">${esc(sub)}</div>` : ""}</div>`).join("");
  if (!res.quests || !res.quests.length) { list.innerHTML = `<div class="detect-empty">${esc(t("quests.noDetails"))}</div>`; return; }
  list.innerHTML = res.quests.map((quest) => `<div class="detect-item"><span class="quest-state ${quest.status === "completed" ? "done" : "pending"}">${esc(t(quest.status === "completed" ? "quests.done" : "quests.todo"))}</span><div><div class="detect-game">${esc(quest.title)}</div><div class="stat-sub">${esc(quest.detail)}</div></div></div>`).join("");
}

async function loadDiagnostics() {
  const res = await api("diagnostics");
  if (!res || !res.ok) return;
  const d = res.discord || {};
  const lib = res.library || {};
  const stats = [
    {
      label: t("diag.client"), value: d.running ? t("diag.running") : t("diag.stopped"),
      cls: d.running ? "ok" : "warn", sub: d.version ? "v" + d.version : "—",
    },
    {
      label: t("diag.ipc"), value: (res.pipes && res.pipes.length) ? res.pipes.join(" · ") : (state.settings.lang === "en" ? "None" : "Aucun"),
      cls: (res.pipes && res.pipes.length) ? "ok" : "err", sub: "discord-ipc",
    },
    {
      label: t("diag.rpc"), value: res.rpc && res.rpc.connecte ? t("diag.on") : t("diag.off"),
      cls: res.rpc && res.rpc.connecte ? "ok" : "warn", sub: (res.rpc && res.rpc.client_id) || "—",
    },
    {
      label: t("diag.catalog"), value: lib.state === "ready" ? t("diag.ready") : lib.state === "loading" ? t("diag.loading") : t("diag.error"),
      cls: lib.state === "ready" ? "ok" : lib.state === "loading" ? "warn" : "err",
      sub: fmtNum(lib.count) + (state.settings.lang === "en" ? " games" : " jeux"),
    },
  ];
  $("#statGrid").innerHTML = stats.map((s) => `
    <div class="stat">
      <div class="stat-label">${esc(s.label)}</div>
      <div class="stat-value"><span class="status-dot ${s.cls}"></span>${esc(s.value)}</div>
      <div class="stat-sub">${esc(s.sub || "")}</div>
    </div>`).join("");

  $("#diagEvents").textContent = `${res.events || 0} ${t("diag.changes")}`;
  const list = $("#detectList");
  if (res.detections && res.detections.length) {
    list.innerHTML = res.detections.slice().reverse().map((x) => `
      <div class="detect-item">
        <span class="detect-time">${esc(x.time)}</span>
        <span class="detect-game">${esc(x.game)}</span>
      </div>`).join("");
  } else {
    list.innerHTML = `<div class="detect-empty">${t("diag.noDetection")}</div>`;
  }
  $("#diagReport").textContent = res.text || "";

  $("#diagCopy").onclick = async () => {
    await copyText(res.text || "");
    toast(t("toast.copied"), "", "ok");
  };
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

/* ─────────────────────────── Réglages ─────────────────────────── */
function applyTheme() {
  const accent = state.settings.accent || "blurple";
  document.body.className = `accent-${accent}` + (state.settings.reduced_motion ? " reduced-motion" : "");
  window.ORBS_LANG = state.settings.lang === "en" ? "en" : "fr";
  document.documentElement.lang = window.ORBS_LANG;
}

function syncSettingsUI() {
  const s = state.settings;
  $$("#langSeg button").forEach((b) => b.classList.toggle("active", b.dataset.lang === (s.lang || "fr")));
  $$("#swatches .swatch").forEach((b) => b.classList.toggle("active", b.dataset.accent === (s.accent || "blurple")));
  const set = (id, value) => { const el = document.getElementById(id); if (el) el.checked = !!value; };
  set("optMotion", s.reduced_motion);
  set("optStartup", s.start_with_windows);
  set("optAutoRefresh", s.auto_refresh);
  set("optFakeWindow", s.show_fake_window);
  const playtime = document.getElementById("optPlaytimeHours");
  if (playtime) playtime.value = String(Math.max(0, Math.min(87600, Number(s.playtime_hours) || 0)));
  const path = $("#dataPath");
  if (path && state.dataDir) path.textContent = state.dataDir;
}

async function saveSettings(patch, silent = true) {
  state.settings = Object.assign({}, state.settings, patch);
  applyTheme();
  syncSettingsUI();
  const res = await api("save_settings", patch);
  if (res && res.settings) state.settings = res.settings;
  if (!silent) toast(t("settings.saved"), "", "ok");
  return res;
}

function bindSettings() {
  $$("#langSeg button").forEach((btn) => {
    btn.onclick = async () => {
      await saveSettings({ lang: btn.dataset.lang });
      state._countsSig = "";
      applyI18n(document);
      refreshNav();
      updateCounts();
      renderDiscord();
      renderNowPlaying();
      renderRecents();
      renderPresets();
      syncSettingsUI();
      if (state.view === "library") fetchPage(true);
      if (state.view === "diagnostics") loadDiagnostics();
    };
  });

  $$("#swatches .swatch").forEach((btn) => {
    btn.onclick = () => saveSettings({ accent: btn.dataset.accent });
  });

  const toggles = {
    optMotion: "reduced_motion",
    optStartup: "start_with_windows",
    optAutoRefresh: "auto_refresh",
    optFakeWindow: "show_fake_window",
  };
  Object.entries(toggles).forEach(([id, key]) => {
    const el = document.getElementById(id);
    el.onchange = async () => {
      const res = await saveSettings({ [key]: el.checked }, false);
      if (id === "optStartup" && res && res.startup !== undefined) {
        state.settings.start_with_windows = res.startup;
        syncSettingsUI();
      }
    };
  });

  const playtimeInput = $("#optPlaytimeHours");
  playtimeInput.onchange = async () => {
    const requested = Number(playtimeInput.value);
    const hours = Number.isFinite(requested) ? Math.max(0, Math.min(87600, Math.floor(requested))) : 0;
    await saveSettings({ playtime_hours: hours }, false);
  };

  $("#openFolder").onclick = () => api("open_data_folder");
  $("#clearHistory").onclick = async () => {
    const res = await api("clear_history");
    if (res && res.ok) {
      state.recents = [];
      state.counts.recents = 0;
      renderRecents();
      updateCounts();
      toast(t("toast.historyCleared"), "", "ok");
    }
  };
}

/* ─────────────────────────── Boot / init ─────────────────────────── */
function setBootProgress(value, label) {
  const fill = $("#bootFill");
  if (fill) fill.style.width = `${Math.max(6, Math.min(100, value))}%`;
  if (label) $("#bootStatus").textContent = label;
}

function finishBoot() {
  setBootProgress(100);
  const boot = $("#boot");
  const shell = $("#shell");
  shell.classList.remove("hidden");
  boot.classList.add("done");
  setTimeout(() => boot.remove(), 500);
  state.ready = true;
}

async function waitLibrary() {
  const started = Date.now();
  while (!state.ready && Date.now() - started < 30000) {
    await new Promise((r) => setTimeout(r, 350));
    const res = await api("status");
    if (!res || !res.library) continue;
    state.library = res.library;
    const pct = Math.round(8 + (res.library.progress || 0) * 88);
    setBootProgress(pct, res.library.state === "loading"
      ? `${t("library.loading")} ${res.library.progress ? Math.round(res.library.progress * 100) + "%" : ""}`
      : "");
    if (res.library.state !== "loading") {
      state.counts.games = res.library.count || 0;
      updateCounts();
      finishBoot();
      if (res.library.state === "error") {
        toast(t("error.library"), res.library.error || "", "err");
      }
      if (state.view === "library") fetchPage(true);
      return;
    }
  }
  finishBoot();
  toast(t("error.library"), t("library.loading"), "err");
}

async function fitWindow() {
  try {
    const dpr = window.devicePixelRatio || 1;
    const availW = (window.screen.availWidth || 1280) / dpr;
    const availH = (window.screen.availHeight || 800) / dpr;
    const width = Math.min(1240, Math.max(980, availW - 22));
    const height = Math.min(820, Math.max(600, availH - 42));
    await api("fit_window", width, height);
  } catch (_) { /* ignore */ }
}

async function boot() {
  if (state.booted) return;
  state.booted = true;

  const res = await api("bootstrap");
  if (!res || !res.ok) {
    setBootProgress(100, t("toast.noApiMsg"));
    setTimeout(() => {
      finishBoot();
      toast(t("toast.noApi"), t("toast.noApiMsg"), "err");
    }, 1200);
    return;
  }

  state.settings = res.settings || {};
  state.favorites = new Set((res.favorites || []).map(String));
  state.recents = res.recents || [];
  state.presets = res.presets || [];
  state.counts = res.counts || state.counts;
  state.discord = res.discord || state.discord;
  state.library = res.library || state.library;
  state.running = res.running || null;
  state.runningGames = res.runningGames || [];
  state.dataDir = res.dataDir || "";
  $("#versionTag").textContent = "v" + String(res.version || "2.0").split(".").slice(0, 2).join(".");
  $("#aboutVersion").textContent = "v" + (res.version || "2.0.0");

  applyTheme();
  applyI18n(document);
  syncSettingsUI();
  renderDiscord();
  updateCounts();
  renderRecents();
  renderPresets();
  renderNowPlaying();
  fitWindow();

  if (res.library && res.library.state === "ready") {
    setBootProgress(100);
    finishBoot();
    if (state.view === "library") fetchPage(true);
  } else {
    waitLibrary();
  }
}

/* ─────────────────────────── Événements globaux ─────────────────────────── */
function bindStatic() {
  // Navigation (sidebar + boutons data-nav)
  document.addEventListener("click", (event) => {
    const nav = event.target.closest("[data-nav]");
    if (nav) {
      event.preventDefault();
      if (nav.dataset.nav === "library" && nav.dataset.tab) go("library", nav.dataset.tab);
      else if (nav.dataset.nav === "favorites") go("favorites");
      else go(nav.dataset.nav);
      return;
    }
    const url = event.target.closest("[data-url]");
    if (url) { api("open_url", url.dataset.url); return; }
  });

  // Fenêtre
  $$("[data-win]").forEach((btn) => {
    btn.onclick = async () => {
      const action = btn.dataset.win;
      if (action === "close") { await api("quit"); return; }
      const res = await api("window_action", action);
      if (action === "maximize" && res) {
        const use = btn.querySelector("use");
        if (use) use.setAttribute("href", res.maximized ? "#i-restore" : "#i-max");
      }
    };
  });

  $("#connPill").onclick = () => go("diagnostics");
  $("#discordChip").onclick = () => go("diagnostics");
  $("#searchTrigger").onclick = () => { go("library"); setTimeout(() => $("#searchInput").focus(), 120); };
  $("#addCustom").onclick = () => go("custom");
  $("#quickRefresh").onclick = refreshLibrary;
  $("#refreshBtn").onclick = refreshLibrary;

  // Recherche
  const input = $("#searchInput");
  const field = $(".search-field");
  let debounce = null;
  input.addEventListener("input", () => {
    field.classList.toggle("has-value", !!input.value);
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.query = input.value.trim();
      skeletonGrid(6);
      fetchPage(true);
    }, 240);
  });
  $("#searchClear").onclick = () => {
    input.value = "";
    field.classList.remove("has-value");
    state.query = "";
    fetchPage(true);
    input.focus();
  };

  // Onglets
  $$("#tabs .tab").forEach((tab) => {
    tab.onclick = () => {
      $$("#tabs .tab").forEach((b) => b.classList.remove("active"));
      tab.classList.add("active");
      state.tab = tab.dataset.tab;
      state.query = "";
      input.value = "";
      field.classList.remove("has-value");
      skeletonGrid();
      fetchPage(true);
      refreshNav();
    };
  });

  // Scroll infini
  $("#main").addEventListener("scroll", () => {
    const el = $("#main");
    if (state.view !== "library" || !state.hasMore || state.loading) return;
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 600) fetchPage(false);
  });

  bindGrid();
  bindCustomForm();
  bindSettings();

  $("#diagRefresh").onclick = loadDiagnostics;
  $("#questsRefresh").onclick = loadDiscordQuests;

  // Modal / clavier
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if ($("#modalRoot").innerHTML) closeModal();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      go("library");
      setTimeout(() => $("#searchInput").focus(), 120);
    }
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (state.running) stopPresence();
    }
  });

  setInterval(tickTimer, 1000);
  setInterval(pollStatus, 1600);
}

async function refreshLibrary() {
  toast(t("toast.refreshing"), "", "info");
  await api("refresh_library");
  const started = Date.now();
  while (Date.now() - started < 120000) {
    await new Promise((r) => setTimeout(r, 1200));
    const res = await api("status");
    if (!res || !res.library) continue;
    state.library = res.library;
    if (res.library.state === "ready") {
      state.counts.games = res.library.count;
      updateCounts();
      toast(t("toast.refreshed"), `${fmtNum(res.library.count)} ${t("nav.library").toLowerCase()}`, "ok");
      if (state.view === "library") fetchPage(true);
      return;
    }
  }
}

let polling = false;
async function pollStatus() {
  if (!state.ready || polling) return;
  polling = true;
  try {
    const res = await api("status");
    if (!res) return;
    if (res.discord) { state.discord = res.discord; renderDiscord(); }
    if (res.counts) state.counts = Object.assign(state.counts, res.counts);
    if (res.library) {
      const wasLoading = state.library.state === "loading";
      state.library = res.library;
      if (wasLoading && res.library.state !== "loading") {
        state.counts.games = res.library.count || 0;
        updateCounts();
        if (state.view === "library") fetchPage(true);
      }
    }
    const same = state.running && res.running &&
      state.running.started === res.running.started &&
      state.running.kind === res.running.kind &&
      state.running.name === res.running.name;
    const oldGames = JSON.stringify(state.runningGames);
    state.running = res.running;
    state.runningGames = res.runningGames || [];
    if (!same || oldGames !== JSON.stringify(state.runningGames)) renderNowPlaying();
    updateCounts();
  } finally {
    polling = false;
  }
}

/* ─────────────────────────── Démarrage ─────────────────────────── */
function start() {
  bindStatic();
  applyI18n(document);
  syncSettingsUI();
  setBootProgress(8, t("library.loading"));

  if (window.pywebview && window.pywebview.api) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot);
    setTimeout(() => { if (!state.booted) boot(); }, 1500);
  }
}

document.addEventListener("DOMContentLoaded", start);
