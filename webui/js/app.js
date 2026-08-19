/* ======================================================
   MusicTools — Frontend (vanilla JS)
   ====================================================== */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  config: {},
  license: { licensed: false },
  purchaseUrl: "https://musictools.djluza.com",
  loaded: null,  // { kind: "urls"|"tracks", urls?, tracks?, count }
  dlOutputDir: "",
  upDir: "",
  upArchiveDir: "",
  upPicker: { file: "", candidates: [], selectedIdx: -1 },
  videoOutputDir: "",
  showSecret: false,
  downloading: false,
  upgrading: false,
  videoDownloading: false,
  meta: { path: "", newCoverPath: "", removeCover: false },
  rec: { devices: [], outputDir: "", recording: false, seconds: 0 },
};

// Wait for pywebview ready
function waitApi() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", resolve, { once: true });
  });
}

// Riconosce se una stringa e un URL (incluso schema spotify:)
function looksLikeUrl(s) {
  if (!s) return false;
  if (/^(https?|spotify):/i.test(s)) return true;
  if (s.includes("://")) return true;
  // Domini comuni anche senza http (es. "youtube.com/...")
  return /^(www\.)?(youtube\.com|youtu\.be|spotify\.com|soundcloud\.com|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)\//i.test(s);
}

// Trasforma una query libera in {name, artist}.
// Formati riconosciuti: "Artista - Titolo" (anche con – o —) oppure solo "Titolo".
function parseQueryToTrack(q) {
  const s = (q || "").trim();
  const m = s.match(/^(.+?)\s+[-–—]\s+(.+)$/);
  if (m) return { artist: m[1].trim(), name: m[2].trim() };
  return { artist: "", name: s };
}

// ============================================================
// Licenza: gating della UI principale
// ============================================================
function applyLicenseGate() {
  const lic = state.license || { licensed: false };
  const screen = $("#activateScreen");
  const appEl = document.querySelector(".app");
  if (!lic.licensed) {
    if (screen) screen.hidden = false;
    if (appEl) appEl.style.display = "none";
  } else {
    if (screen) screen.hidden = true;
    if (appEl) appEl.style.display = "";
  }
}

function fmtDate(epoch) {
  if (!epoch) return "—";
  try {
    return new Date(epoch * 1000).toLocaleDateString("it-IT", {
      day: "2-digit", month: "short", year: "numeric"
    });
  } catch (_e) { return "—"; }
}

function renderLicenseStatus() {
  const lic = state.license || {};
  const box = $("#licenseStatusBox");
  if (!box) return;  // panel non ancora montato
  if (!lic.licensed) {
    box.innerHTML = `<div class="lic-warn">Licenza non attiva</div>`;
    return;
  }
  const plan = lic.plan || {};
  const planLine = plan.code
    ? `<div class="lic-row"><span>Piano</span><strong>${plan.name || plan.code}</strong></div>`
    : "";
  const limitLine = plan.daily_limit
    ? `<div class="lic-row"><span>Limite giornaliero</span><strong>${plan.daily_limit}</strong></div>`
    : (plan.code === "annual"
        ? `<div class="lic-row"><span>Limite giornaliero</span><strong>Illimitato</strong></div>`
        : "");
  const expiryLine = plan.expires_at
    ? `<div class="lic-row"><span>Scade il</span><strong>${fmtDate(plan.expires_at)}</strong></div>`
    : (plan.period_end
        ? `<div class="lic-row"><span>Prossimo rinnovo</span><strong>${fmtDate(plan.period_end)}</strong></div>`
        : "");
  box.innerHTML = `
    ${planLine}
    ${limitLine}
    ${expiryLine}
    <div class="lic-row"><span>Email</span><strong>${lic.email || "—"}</strong></div>
    <div class="lic-row"><span>Chiave</span><strong>${lic.key || "—"}</strong></div>
    <div class="lic-row"><span>Attivata il</span><strong>${fmtDate(lic.activated_at)}</strong></div>
    <div class="lic-row"><span>Ultima verifica</span><strong>${fmtDate(lic.last_validated_at)}</strong></div>
  `;
}

// ============================================================
// Piano e quota giornaliera
// ============================================================
function applyPlanGate() {
  // Nasconde le tab non incluse nel piano corrente.
  const lic = state.license || {};
  const features = (lic.plan && lic.plan.features) || [];
  $$(".nav-item[data-feature]").forEach((btn) => {
    const f = btn.dataset.feature;
    const allowed = features.includes(f);
    btn.hidden = !allowed;
    if (!allowed && btn.classList.contains("active")) {
      // Fallback alla prima tab disponibile (audio o settings)
      const fallback = $$(".nav-item[data-feature]:not([hidden])")[0]
        || $(".nav-item[data-view='settings']");
      if (fallback) showView(fallback.dataset.view);
    }
  });
}

function renderQuotaBox(q) {
  const box = $("#quotaBox");
  if (!box) return;
  const lic = state.license || {};
  const plan = (q && q.plan) || lic.plan || {};
  if (!plan.code || plan.code === "annual" || plan.daily_limit == null) {
    // Annual / unlimited -> niente contatore
    box.hidden = true;
    return;
  }
  box.hidden = false;
  $("#quotaUsed").textContent = String((q && q.used) ?? 0);
  $("#quotaLimit").textContent = String(plan.daily_limit);
  $("#quotaPlanName").textContent = plan.name || plan.code;
  const upBtn = $("#quotaUpgradeBtn");
  if (upBtn) upBtn.hidden = plan.code === "premium";
}

async function refreshQuota() {
  const lic = state.license || {};
  const plan = lic.plan || {};
  if (!lic.licensed || !plan.code || plan.daily_limit == null) {
    renderQuotaBox(null);
    return;
  }
  try {
    const res = await window.pywebview.api.get_quota_status();
    if (res && res.ok) {
      renderQuotaBox(res.quota);
    }
  } catch (_e) { /* offline: lascia stato precedente */ }
}

function showUpgradeModal(reason, payload) {
  const modal = $("#upgradeModal");
  if (!modal) return;
  const title = $("#upgradeModalTitle");
  const body = $("#upgradeModalBody");
  if (reason === "feature_not_in_plan") {
    title.textContent = "Funzione non inclusa nel piano";
    body.innerHTML = `
      <p>${payload.error || "Questa funzione non e' inclusa nel tuo piano."}</p>
      <p class="modal-hint">Passa a un piano superiore per sbloccarla.</p>
    `;
  } else if (reason === "quota_exceeded") {
    const q = payload.quota || {};
    title.textContent = "Limite giornaliero raggiunto";
    body.innerHTML = `
      <p>${payload.error || "Hai raggiunto il limite giornaliero del tuo piano."}</p>
      <p class="modal-hint">Usati oggi: <strong>${q.used ?? "?"} / ${q.limit ?? "?"}</strong>. Il contatore si resetta a mezzanotte (ora di Roma).</p>
    `;
  } else if (reason === "license_invalid") {
    title.textContent = "Licenza non valida";
    body.innerHTML = `<p>${payload.error || "La tua licenza non e' piu' valida."}</p>`;
  } else if (reason === "offline") {
    title.textContent = "Connessione assente";
    body.innerHTML = `<p>${payload.error || "Impossibile contattare il server."}</p>`;
  } else {
    title.textContent = "Operazione bloccata";
    body.innerHTML = `<p>${payload.error || "L'operazione non e' stata avviata."}</p>`;
  }
  modal.hidden = false;
}

function hideUpgradeModal() {
  const modal = $("#upgradeModal");
  if (modal) modal.hidden = true;
}

/** Gestisce il dict di errore restituito dai metodi start_*: se e' un
 *  gate failure (feature/quota/license/offline), mostra il modal e
 *  ritorna true (= caller deve interrompere il flow). */
function handleGateBlock(res) {
  if (!res || res.ok !== false) return false;
  const r = res.reason;
  if (r === "feature_not_in_plan" || r === "quota_exceeded"
      || r === "license_invalid" || r === "offline") {
    showUpgradeModal(r, res);
    return true;
  }
  return false;
}

async function activateLicense() {
  const email = $("#actEmail").value.trim();
  const key = $("#actKey").value.trim();
  const err = $("#actError");
  err.hidden = true;
  err.textContent = "";
  if (!email || !key) {
    err.textContent = "Inserisci email e chiave di licenza.";
    err.hidden = false;
    return;
  }
  const btn = $("#actActivateBtn");
  btn.disabled = true;
  const oldText = btn.innerHTML;
  btn.innerHTML = "Attivazione in corso…";
  try {
    const res = await window.pywebview.api.activate_license({ email, key });
    if (res.ok) {
      state.license = res.license;
      applyLicenseGate();
      renderLicenseStatus();
      applyPlanGate();
      refreshQuota();
      toast("Licenza attivata. Benvenuto!", "success");
    } else {
      err.textContent = res.error || "Errore di attivazione.";
      err.hidden = false;
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = oldText;
  }
}

async function deactivateLicense() {
  if (!confirm("Disattivare la licenza su questo dispositivo?")) return;
  const res = await window.pywebview.api.deactivate_license();
  if (res.ok) {
    state.license = res.license;
    applyLicenseGate();
    renderLicenseStatus();
    toast("Licenza disattivata", "info");
  }
}

// ============================================================
// Bridge — eventi spinti dal backend
// ============================================================
window.bridge = {
  emit(channel, payload) {
    const handler = bridgeHandlers[channel];
    if (handler) handler(payload);
  },
};

const bridgeHandlers = {
  "log": ({ view, msg }) => appendLog(view, msg),
  "quota:update": (q) => renderQuotaBox(q),

  "download:progress": (p) => {
    if (typeof p.overall === "number") {
      const pct = Math.round(p.overall * 100);
      $("#dlProgressFill").style.width = pct + "%";
      $("#dlPercent").textContent = pct + "%";
    }
    if (p.status === "searching" && typeof p.idx === "number") {
      const prefix = p.url_total > 1 ? `[${(p.url_idx ?? 0) + 1}/${p.url_total}] ` : "";
      $("#dlCounter").textContent = `${prefix}Brano ${p.idx + 1} di ${p.total}`;
    }
    if (p.status === "completed" && p.url_total > 1) {
      $("#dlCounter").textContent = `Completato: ${p.url_total} URL`;
    }
  },

  "download:done": () => {
    state.downloading = false;
    state.loaded = null;
    $("#urlListBadge").hidden = true;
    $("#urlListBadge").textContent = "";
    $("#downloadBtn").disabled = false;
    $("#loadListBtn").disabled = false;
    $("#stopDownloadBtn").disabled = true;
  },

  "upgrade:progress": (p) => {
    if (typeof p.overall === "number") {
      const pct = Math.round(p.overall * 100);
      $("#upProgressFill").style.width = pct + "%";
      $("#upPercent").textContent = pct + "%";
    }
    if (typeof p.idx === "number" && typeof p.total === "number" && p.total > 0) {
      $("#upCounter").textContent = `File ${p.idx} di ${p.total}`;
    }
    if (p.status === "completed") {
      $("#upCounter").textContent = `Completato: ${p.total} file`;
    }
  },

  "upgrade:done": () => {
    state.upgrading = false;
    $("#upgradeBtn").disabled = false;
    $("#stopUpgradeBtn").disabled = true;
    // Chiudi eventuale modal picker rimasto aperto
    const modal = $("#upgradePickerModal");
    if (modal && !modal.hidden) modal.hidden = true;
  },

  "upgrade:candidates_needed": (p) => openUpgradePicker(p),

  "video:progress": (p) => {
    if (typeof p.overall === "number") {
      const pct = Math.round(p.overall * 100);
      $("#videoProgressFill").style.width = pct + "%";
      $("#videoPercent").textContent = pct + "%";
    }
    if (p.status === "downloading" && typeof p.idx === "number") {
      const prefix = p.url_total > 1 ? `[${(p.url_idx ?? 0) + 1}/${p.url_total}] ` : "";
      $("#videoCounter").textContent = `${prefix}Video ${p.idx + 1} di ${p.total}`;
    }
    if (p.status === "completed" && p.url_total > 1) {
      $("#videoCounter").textContent = `Completato: ${p.url_total} URL`;
    }
  },

  "video:done": () => {
    state.videoDownloading = false;
    $("#videoDownloadBtn").disabled = false;
    $("#stopVideoBtn").disabled = true;
  },

  "recording:event": (p) => {
    const status = p.status;
    if (status === "started") {
      state.rec.recording = true;
      state.rec.seconds = 0;
      $("#recStartBtn").disabled = true;
      $("#recStartBtn").classList.add("recording");
      $("#recStopBtn").disabled = false;
      $("#recDevice").disabled = true;
      $("#recRefreshBtn").disabled = true;
      $("#recTimer").textContent = "00:00:00";
      $("#recStatus").textContent = "● Registrazione in corso…";
      $("#recErrorCard").hidden = true;  // pulisci eventuale errore precedente
    } else if (status === "tick") {
      state.rec.seconds = p.seconds || 0;
      $("#recTimer").textContent = formatHms(state.rec.seconds);
    } else if (status === "stopped") {
      state.rec.recording = false;
      $("#recStartBtn").disabled = false;
      $("#recStartBtn").classList.remove("recording");
      $("#recStopBtn").disabled = true;
      $("#recDevice").disabled = false;
      $("#recRefreshBtn").disabled = false;
      $("#recStatus").textContent = "";
      $("#recOutputCard").hidden = false;
      $("#recResult").innerHTML = `
        <span class="badge-dur">${formatHms(p.seconds || 0)}</span>
        ${p.output_path || ""}
      `;
      toast("Registrazione salvata", "success");
    } else if (status === "error") {
      state.rec.recording = false;
      $("#recStartBtn").disabled = false;
      $("#recStartBtn").classList.remove("recording");
      $("#recStopBtn").disabled = true;
      $("#recDevice").disabled = false;
      $("#recRefreshBtn").disabled = false;
      $("#recStatus").textContent = "";
      const msg = p.error || "Errore sconosciuto";
      $("#recErrorMsg").textContent = msg;
      $("#recErrorCard").hidden = false;
      $("#recErrorLog").hidden = true;
      $("#recErrorLog").textContent = "";
      $("#recCopyLogBtn").hidden = true;
      $("#recShowLogBtn").textContent = "Mostra log tecnici";
      toast("Errore registrazione", "error");
    }
  },
};

function formatHms(sec) {
  const h = Math.floor(sec / 3600).toString().padStart(2, "0");
  const m = Math.floor((sec % 3600) / 60).toString().padStart(2, "0");
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${h}:${m}:${s}`;
}

// ============================================================
// Logging
// ============================================================
const logEls = {
  download: () => $("#dlLog"),
  upgrade: () => $("#upLog"),
  video: () => $("#videoLog"),
  spotify: () => $("#spotify-log"),
  youtube: () => $("#youtube-log"),
  convert: () => $("#convert-log"),
  traxsource: () => $("#traxsource-log"),
  dedup: () => $("#dedup-log"),
};

function classifyLog(msg) {
  if (msg.startsWith("[ERRORE]")) return "l-err";
  if (msg.startsWith("[OK]") || msg.startsWith("[UPGRADE]")) return "l-ok";
  if (msg.startsWith("[INFO]")) return "l-info";
  if (msg.startsWith("[SKIP]") || msg.startsWith("[CERCA]") || msg.startsWith("[DOWNLOAD]") || msg.startsWith("[CONV]")) return "l-muted";
  if (msg.startsWith("[NON TROVATO]")) return "l-warn";
  if (msg.startsWith("[LISTA]")) return "l-info";
  return "";
}

function appendLog(view, msg) {
  const el = logEls[view] && logEls[view]();
  if (!el) return;
  const cls = classifyLog(msg);
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

// ============================================================
// Toast
// ============================================================
let toastTimer = null;
function toast(msg, kind = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast show " + (kind ? `toast-${kind}` : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 3000);
}

// ============================================================
// Routing (sidebar)
// ============================================================
function showView(name) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
}

function applyTheme(theme) {
  const t = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
}

$$(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

// ============================================================
// Init
// ============================================================
async function init() {
  await waitApi();
  const data = await window.pywebview.api.get_init_data();
  state.config = data.config || {};
  state.license = data.license || { licensed: false };
  state.purchaseUrl = data.purchase_url || "https://musictools.djluza.com";
  $("#footerVersion").textContent = data.version;
  $("#currentVersionLabel").textContent = data.version;
  $("#guideBody").textContent = data.spotify_guide;

  applyLicenseGate();
  renderLicenseStatus();
  applyPlanGate();
  refreshQuota();

  // Populate Settings fields
  $("#clientIdInput").value = state.config.client_id || "";
  $("#clientSecretInput").value = state.config.client_secret || "";
  $("#bitrateSelect").value = state.config.bitrate || "320K";
  $("#hqThresholdInput").value = state.config.hq_threshold || 310;
  $("#cookiesInput").value = state.config.cookies_path || "";
  if ($("#cookiesBrowserSelect")) $("#cookiesBrowserSelect").value = state.config.cookies_browser || "";
  $("#outputInput").value = state.config.output_dir || "";
  $("#themeSelect").value = state.config.theme || "dark";
  applyTheme(state.config.theme);

  // Download tab — usa output_dir come default
  state.dlOutputDir = state.config.output_dir || "";
  if (state.dlOutputDir) {
    $("#dlPathDisplay").textContent = state.dlOutputDir;
    $("#dlPathDisplay").classList.remove("empty");
  }

  // Video tab — usa output_dir come default
  state.videoOutputDir = state.config.output_dir || "";
  if (state.videoOutputDir) {
    $("#videoPathDisplay").textContent = state.videoOutputDir;
    $("#videoPathDisplay").classList.remove("empty");
  }

  // Upgrade tab — default threshold
  $("#upThreshold").value = state.config.hq_threshold || 310;

  // Record tab — default output dir + carica dispositivi
  state.rec.outputDir = state.config.output_dir || "";
  if (state.rec.outputDir) {
    $("#recPathDisplay").textContent = state.rec.outputDir;
    $("#recPathDisplay").classList.remove("empty");
  }
  await refreshRecDevices();

  // Beatport tab — popola generi, ripristina ultimo genere, aggancia handler
  await BeatportUI.init();

  // Spotify + YouTube search tabs
  await SpotifyUI.init();
  await YoutubeUI.init();

  // Traxsource charts tab
  await TraxsourceUI.init();

  // WAV -> MP3 converter tab
  await ConvertUI.init();

  // Dedup tab (audio duplicati via Chromaprint)
  await DedupUI.init();
}

async function refreshRecDevices() {
  const res = await window.pywebview.api.list_audio_inputs();
  const select = $("#recDevice");
  select.innerHTML = "";
  state.rec.devices = res.devices || [];
  if (!state.rec.devices.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Nessun dispositivo trovato";
    select.appendChild(opt);
    return;
  }
  for (const d of state.rec.devices) {
    const opt = document.createElement("option");
    opt.value = d.id;
    opt.textContent = d.is_virtual ? `🔄 ${d.name} (loopback)` : d.name;
    select.appendChild(opt);
  }
}

// ============================================================
// DOWNLOAD tab
// ============================================================
$("#dlBrowseBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_directory();
  if (path) {
    state.dlOutputDir = path;
    $("#dlPathDisplay").textContent = path;
    $("#dlPathDisplay").classList.remove("empty");
  }
});

$("#loadListBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_file([
    "Text files (*.txt)",
    "All files (*.*)",
  ]);
  if (!path) return;
  const res = await window.pywebview.api.load_url_list(path);
  if (!res.ok) {
    toast("Impossibile leggere il file: " + (res.error || ""), "error");
    return;
  }
  if (!res.count) {
    toast("Il file non contiene voci valide", "error");
    return;
  }
  state.loaded = res;
  $("#urlInput").value = path;
  const badge = $("#urlListBadge");
  if (res.kind === "tracks") {
    badge.textContent = `· ${res.count} tracce`;
    appendLog("download", `[INFO] Caricata tracklist: ${res.count} brani`);
  } else {
    badge.textContent = `· ${res.count} URL`;
    appendLog("download", `[INFO] Caricati ${res.count} URL dal file`);
  }
  badge.hidden = false;
});

$("#downloadBtn").addEventListener("click", async () => {
  if (!state.dlOutputDir) {
    toast("Seleziona una cartella di destinazione", "error");
    return;
  }

  state.downloading = true;
  $("#downloadBtn").disabled = true;
  $("#loadListBtn").disabled = true;
  $("#stopDownloadBtn").disabled = false;
  $("#dlProgressFill").style.width = "0%";
  $("#dlPercent").textContent = "0%";

  let res;
  if (state.loaded && state.loaded.kind === "tracks") {
    res = await window.pywebview.api.start_tracks_download({
      tracks: state.loaded.tracks,
      output_dir: state.dlOutputDir,
      subfolder: state.loaded.name || "",
    });
  } else {
    let urls = state.loaded && state.loaded.kind === "urls" ? state.loaded.urls : [];
    if (!urls.length) {
      const single = $("#urlInput").value.trim();
      if (!single) {
        toast("Inserisci un URL, un titolo o carica una lista", "error");
        bridgeHandlers["download:done"]();
        return;
      }
      if (looksLikeUrl(single)) {
        urls = [single];
      } else {
        const track = parseQueryToTrack(single);
        res = await window.pywebview.api.start_tracks_download({
          tracks: [track],
          output_dir: state.dlOutputDir,
          subfolder: "",
        });
        if (!res.ok) {
          if (!handleGateBlock(res)) toast(res.error || "Errore", "error");
          bridgeHandlers["download:done"]();
        }
        return;
      }
    }
    res = await window.pywebview.api.start_download({
      urls,
      output_dir: state.dlOutputDir,
    });
  }

  if (!res.ok) {
    if (!handleGateBlock(res)) toast(res.error || "Errore", "error");
    bridgeHandlers["download:done"]();
  }
});

$("#stopDownloadBtn").addEventListener("click", async () => {
  await window.pywebview.api.stop_download();
  $("#stopDownloadBtn").disabled = true;
});

// ============================================================
// VIDEO tab
// ============================================================
$("#videoBrowseBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_directory();
  if (path) {
    state.videoOutputDir = path;
    $("#videoPathDisplay").textContent = path;
    $("#videoPathDisplay").classList.remove("empty");
  }
});

let videoMode = "video";  // "video" | "audio"

$$("#videoMode .seg-btn").forEach((b) => {
  b.addEventListener("click", () => {
    $$("#videoMode .seg-btn").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    videoMode = b.dataset.mode;
    $("#videoQualityField").style.display = videoMode === "audio" ? "none" : "";
  });
});

$("#videoDownloadBtn").addEventListener("click", async () => {
  const url = $("#videoUrlInput").value.trim();
  if (!url) {
    toast("Inserisci un URL", "error");
    return;
  }
  if (!state.videoOutputDir) {
    toast("Seleziona una cartella di destinazione", "error");
    return;
  }

  state.videoDownloading = true;
  $("#videoDownloadBtn").disabled = true;
  $("#stopVideoBtn").disabled = false;
  $("#videoProgressFill").style.width = "0%";
  $("#videoPercent").textContent = "0%";

  const res = await window.pywebview.api.start_video_download({
    urls: [url],
    output_dir: state.videoOutputDir,
    quality: $("#videoQuality").value,
    audio_only: videoMode === "audio",
  });
  if (!res.ok) {
    if (!handleGateBlock(res)) toast(res.error || "Errore", "error");
    bridgeHandlers["video:done"]();
  }
});

$("#stopVideoBtn").addEventListener("click", async () => {
  await window.pywebview.api.stop_video_download();
  $("#stopVideoBtn").disabled = true;
});

// ============================================================
// UPGRADE tab
// ============================================================
$("#upBrowseBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_directory();
  if (path) {
    state.upDir = path;
    $("#upPathDisplay").textContent = path;
    $("#upPathDisplay").classList.remove("empty");
    await refreshUpgradeScan();
  }
});

$("#upRecursive").addEventListener("change", refreshUpgradeScan);

// --- Cartella archivio (opzionale) ---
$("#upArchiveBrowseBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_directory();
  if (path) {
    state.upArchiveDir = path;
    const disp = $("#upArchivePathDisplay");
    disp.textContent = path;
    disp.classList.remove("empty");
    $("#upArchiveClearBtn").hidden = false;
  }
});

$("#upArchiveClearBtn").addEventListener("click", () => {
  state.upArchiveDir = "";
  const disp = $("#upArchivePathDisplay");
  disp.textContent = "Nessuna cartella";
  disp.classList.add("empty");
  $("#upArchiveClearBtn").hidden = true;
});

async function refreshUpgradeScan() {
  if (!state.upDir) return;
  const res = await window.pywebview.api.scan_audio_folder(state.upDir, $("#upRecursive").checked);
  const info = $("#upInfo");
  if (!res.ok) {
    info.textContent = "Errore scansione: " + (res.error || "");
    return;
  }
  if (!res.total) {
    info.textContent = "Nessun file audio trovato";
    return;
  }
  if (res.done > 0) {
    info.textContent = `● ${res.total} file audio · ${res.done} già convertiti · ${res.remaining} da fare`;
  } else {
    info.textContent = `● ${res.total} file audio trovati`;
  }
}

$("#upgradeBtn").addEventListener("click", async () => {
  if (!state.upDir) {
    toast("Seleziona una cartella", "error");
    return;
  }
  state.upgrading = true;
  $("#upgradeBtn").disabled = true;
  $("#stopUpgradeBtn").disabled = false;
  $("#upProgressFill").style.width = "0%";
  $("#upPercent").textContent = "0%";

  const res = await window.pywebview.api.start_upgrade({
    directory: state.upDir,
    recursive: $("#upRecursive").checked,
    threshold: parseInt($("#upThreshold").value, 10) || 310,
    archive_dir: state.upArchiveDir || "",
    archive_auto_pick: $("#upArchiveAutoPick").checked,
  });
  if (!res.ok) {
    if (!handleGateBlock(res)) toast(res.error || "Errore", "error");
    bridgeHandlers["upgrade:done"]();
  }
});

$("#stopUpgradeBtn").addEventListener("click", async () => {
  await window.pywebview.api.stop_upgrade();
  $("#stopUpgradeBtn").disabled = true;
});

// --- Modal picker "Match locali multipli" ---
function _fmtBytes(n) {
  if (!n || n < 0) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
  return (n / (1024 * 1024 * 1024)).toFixed(2) + " GB";
}

function _basename(p) {
  if (!p) return "";
  const parts = String(p).split(/[/\\]/);
  return parts[parts.length - 1] || p;
}

function _escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// --- Audio preview per il picker (single audio element condiviso) ---
let _upgradePreviewAudio = null;
let _upgradePreviewBtn = null;  // bottone corrente in "playing" state

function _fileUrl(absPath) {
  if (!absPath) return "";
  // Split percorso e encode ogni segment (spazi → %20, unicode → utf-8 encoded)
  const parts = String(absPath).split("/").map(encodeURIComponent);
  return "file://" + parts.join("/");
}

function _stopUpgradePreview() {
  if (_upgradePreviewAudio) {
    // Rimuovi handler error PRIMA di pause/clear così stop manuale
    // non fa scattare il toast di errore
    _upgradePreviewAudio.onerror = null;
    _upgradePreviewAudio.onended = null;
    try { _upgradePreviewAudio.pause(); } catch {}
    try { _upgradePreviewAudio.removeAttribute("src"); } catch {}
    _upgradePreviewAudio = null;
  }
  if (_upgradePreviewBtn) {
    _upgradePreviewBtn.textContent = "▶";
    _upgradePreviewBtn.classList.remove("playing");
    _upgradePreviewBtn = null;
  }
}

function _makePreviewBtn(absPath) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "upgrade-preview-btn";
  btn.textContent = "▶";
  btn.title = "Anteprima audio";
  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Se già in play su questo bottone → stop
    if (_upgradePreviewBtn === btn) {
      _stopUpgradePreview();
      return;
    }
    _stopUpgradePreview();
    btn.textContent = "⏳";
    btn.disabled = true;
    let res;
    try {
      res = await window.pywebview.api.read_audio_data_url(absPath);
    } catch (err) {
      btn.textContent = "▶";
      btn.disabled = false;
      toast && toast("Errore lettura file: " + err, "error");
      return;
    }
    btn.disabled = false;
    if (!res || !res.ok) {
      btn.textContent = "▶";
      toast && toast(res && res.error || "Impossibile leggere il file", "error");
      return;
    }
    _upgradePreviewAudio = new Audio(res.data_url);
    _upgradePreviewBtn = btn;
    btn.textContent = "■";
    btn.classList.add("playing");
    _upgradePreviewAudio.onended = _stopUpgradePreview;
    _upgradePreviewAudio.onerror = () => {
      // Solo se il listener è ancora agganciato (stop manuale lo azzera prima)
      const wasPlaying = !!_upgradePreviewAudio;
      _stopUpgradePreview();
      if (wasPlaying) toast && toast("Errore riproduzione audio", "error");
    };
    _upgradePreviewAudio.play().catch(() => _stopUpgradePreview());
  });
  return btn;
}

function openUpgradePicker(payload) {
  const modal = $("#upgradePickerModal");
  if (!modal) return;
  const file = (payload && payload.file) || "";
  const sourcePath = (payload && payload.source_path) || "";
  const candidates = (payload && payload.candidates) || [];
  state.upPicker = { file, sourcePath, candidates, selectedIdx: -1 };

  // Header: filename + play button per il source
  const header = $("#upgradePickerFilename");
  header.innerHTML = "";
  const label = document.createElement("span");
  label.textContent = "Brano da upgradare: " + file + " ";
  header.appendChild(label);
  if (sourcePath) header.appendChild(_makePreviewBtn(sourcePath));

  const list = $("#upgradePickerList");
  list.innerHTML = "";
  candidates.forEach((c, i) => {
    const row = document.createElement("label");
    row.className = "upgrade-picker-row";
    row.dataset.idx = String(i);
    const simPct = Math.round((c.similarity || 0) * 100);
    const kbps = c.bitrate ? `${c.bitrate}k` : "—";
    row.innerHTML = `
      <input type="radio" name="upgradePickerRadio" value="${i}" />
      <div class="upgrade-picker-info">
        <div class="upgrade-picker-title">${_escapeHtml(_basename(c.path))}</div>
        <div class="upgrade-picker-meta">${_escapeHtml(kbps)} · ${_escapeHtml(_fmtBytes(c.size))} · similarity ${simPct}%</div>
        <div class="upgrade-picker-path">${_escapeHtml(c.path || "")}</div>
      </div>
      <span class="upgrade-picker-play"></span>
    `;
    const playSlot = row.querySelector(".upgrade-picker-play");
    if (playSlot && c.path) playSlot.appendChild(_makePreviewBtn(c.path));
    row.addEventListener("click", (e) => {
      // Se il click viene dal bottone play, non selezionare la riga
      if (e.target.closest(".upgrade-preview-btn")) return;
      state.upPicker.selectedIdx = i;
      $("#upgradePickerUseBtn").disabled = false;
      $$("#upgradePickerList .upgrade-picker-row").forEach((r) =>
        r.classList.toggle("selected", r === row)
      );
      const radio = row.querySelector("input[type=radio]");
      if (radio) radio.checked = true;
    });
    list.appendChild(row);
  });
  $("#upgradePickerUseBtn").disabled = true;
  modal.hidden = false;
}

function closeUpgradePicker() {
  _stopUpgradePreview();
  const modal = $("#upgradePickerModal");
  if (modal) modal.hidden = true;
}

async function _sendUpgradeChoice(choice) {
  try {
    await window.pywebview.api.upgrade_resolve_candidates(choice);
  } catch (_e) { /* backend può essere già terminato: ignora */ }
  closeUpgradePicker();
}

$("#upgradePickerUseBtn")?.addEventListener("click", () => {
  const idx = state.upPicker.selectedIdx;
  if (idx < 0 || idx >= state.upPicker.candidates.length) return;
  const path = state.upPicker.candidates[idx].path;
  _sendUpgradeChoice({ action: "use_local", path });
});

$("#upgradePickerYoutubeBtn")?.addEventListener("click", () => {
  _sendUpgradeChoice({ action: "use_youtube" });
});

$("#upgradePickerSkipBtn")?.addEventListener("click", () => {
  _sendUpgradeChoice({ action: "skip" });
});

$("#upgradePickerCancelAllBtn")?.addEventListener("click", async () => {
  // Skip questo file per sbloccare il worker, poi ferma l'intera coda
  _sendUpgradeChoice({ action: "skip" });
  try { await window.pywebview.api.stop_upgrade(); } catch {}
});

$("#upgradePickerCloseBtn")?.addEventListener("click", () => {
  _sendUpgradeChoice({ action: "skip" });
});

$("#upgradePickerModal")?.addEventListener("click", (e) => {
  // Click sul backdrop (non sulla card) → skip
  if (e.target === e.currentTarget) _sendUpgradeChoice({ action: "skip" });
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const modal = $("#upgradePickerModal");
    if (modal && !modal.hidden) _sendUpgradeChoice({ action: "skip" });
  }
});

// ============================================================
// RECORDER tab
// ============================================================
$("#recRefreshBtn").addEventListener("click", refreshRecDevices);

$("#recOpenGuide").addEventListener("click", (e) => {
  e.preventDefault();
  showView("guide");
  setTimeout(() => {
    const el = document.getElementById("g-record");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 80);
});

// ============================================================
// GUIDE — link esterni + TOC active highlight
// ============================================================
document.querySelectorAll("#view-guide a[data-ext]").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    window.pywebview.api.open_external_url(a.dataset.ext);
  });
});

document.querySelectorAll(".toc-link").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    const id = a.getAttribute("href").slice(1);
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

// Aggiorna TOC active in base allo scroll della view
function setupGuideObserver() {
  const sections = document.querySelectorAll(".g-section[id]");
  const tocLinks = document.querySelectorAll(".toc-link");
  if (!sections.length || !tocLinks.length) return;

  const main = document.querySelector(".main");
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const id = entry.target.id;
        tocLinks.forEach((l) => {
          l.classList.toggle("active", l.getAttribute("href") === "#" + id);
        });
      });
    },
    { root: main, rootMargin: "-20% 0px -65% 0px", threshold: 0 }
  );
  sections.forEach((s) => observer.observe(s));
}
setupGuideObserver();

$("#recBrowseBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_directory();
  if (path) {
    state.rec.outputDir = path;
    $("#recPathDisplay").textContent = path;
    $("#recPathDisplay").classList.remove("empty");
  }
});

$("#recStartBtn").addEventListener("click", async () => {
  const deviceId = $("#recDevice").value;
  if (!deviceId) {
    toast("Seleziona un dispositivo", "error");
    return;
  }
  if (!state.rec.outputDir) {
    toast("Seleziona una cartella di destinazione", "error");
    return;
  }
  const res = await window.pywebview.api.start_audio_recording({
    device_id: deviceId,
    output_dir: state.rec.outputDir,
    filename: $("#recFilename").value.trim(),
    bitrate: $("#recBitrate").value,
  });
  if (!res.ok) {
    if (!handleGateBlock(res)) toast(res.error || "Errore", "error");
  }
});

$("#recStopBtn").addEventListener("click", async () => {
  $("#recStopBtn").disabled = true;
  await window.pywebview.api.stop_audio_recording();
});

$("#recShowLogBtn")?.addEventListener("click", async () => {
  const pre = $("#recErrorLog");
  if (!pre.hidden) {
    pre.hidden = true;
    $("#recShowLogBtn").textContent = "Mostra log tecnici";
    $("#recCopyLogBtn").hidden = true;
    return;
  }
  const res = await window.pywebview.api.get_recorder_log();
  const lines = (res && res.lines) || [];
  pre.textContent = lines.length ? lines.join("\n") : "(log vuoto)";
  pre.hidden = false;
  $("#recShowLogBtn").textContent = "Nascondi log tecnici";
  $("#recCopyLogBtn").hidden = false;
});

$("#recCopyLogBtn")?.addEventListener("click", async () => {
  const text = $("#recErrorLog").textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    toast("Log copiato negli appunti", "success");
  } catch {
    toast("Impossibile copiare", "error");
  }
});

// ============================================================
// METADATA editor
// ============================================================
function formatDuration(sec) {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function populateMetaForm(d) {
  $("#metaTitle").value = d.title || "";
  $("#metaArtist").value = d.artist || "";
  $("#metaAlbum").value = d.album || "";
  $("#metaAlbumArtist").value = d.album_artist || "";
  $("#metaYear").value = d.year || "";
  $("#metaTrack").value = d.track || "";
  $("#metaGenre").value = d.genre || "";
  $("#metaBpm").value = d.bpm || "";
  $("#metaKey").value = d.key || "";
  $("#metaComment").value = d.comment || "";

  // WhereFroms (macOS only)
  if (d.is_macos) {
    $("#metaWhereFromField").hidden = false;
    $("#metaWhereFrom").value = (d.where_from || []).join("\n");
  } else {
    $("#metaWhereFromField").hidden = true;
    $("#metaWhereFrom").value = "";
  }

  // Info riga sotto il path
  const info = $("#metaInfo");
  info.hidden = false;
  info.innerHTML = `
    <span><strong>Formato:</strong>${d.format || "—"}</span>
    <span><strong>Bitrate:</strong>${d.bitrate ? d.bitrate + " kbps" : "—"}</span>
    <span><strong>Durata:</strong>${formatDuration(d.duration)}</span>
  `;

  // Cover
  const preview = $("#metaCoverPreview");
  preview.innerHTML = "";
  if (d.cover_base64) {
    const img = document.createElement("img");
    img.src = `data:${d.cover_mime || "image/jpeg"};base64,${d.cover_base64}`;
    preview.appendChild(img);
  } else {
    const span = document.createElement("span");
    span.className = "cover-empty";
    span.textContent = "Nessuna copertina";
    preview.appendChild(span);
  }
  $("#metaCoverHint").textContent = "";
  $("#metaCoverHint").className = "cover-hint";

  state.meta.newCoverPath = "";
  state.meta.removeCover = false;
}

async function loadMetaFile(path) {
  const res = await window.pywebview.api.read_metadata(path);
  if (!res.ok) {
    toast("Errore lettura: " + (res.error || ""), "error");
    return;
  }
  state.meta.path = path;
  $("#metaPathDisplay").textContent = path;
  $("#metaPathDisplay").classList.remove("empty");
  $("#metaForm").hidden = false;
  populateMetaForm(res.data);
}

$("#metaPickBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.pick_audio_file();
  if (path) await loadMetaFile(path);
});

$("#metaCoverBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.pick_image_file();
  if (!path) return;
  state.meta.newCoverPath = path;
  state.meta.removeCover = false;

  // Mostra anteprima leggendo il file via fetch (file:// non funziona da webview;
  // usiamo solo il nome come hint, l'utente vedra il risultato dopo Save)
  const hint = $("#metaCoverHint");
  hint.textContent = "Nuova copertina: " + path.split("/").pop();
  hint.className = "cover-hint set";
});

$("#metaCoverRemoveBtn").addEventListener("click", () => {
  state.meta.newCoverPath = "";
  state.meta.removeCover = true;
  const preview = $("#metaCoverPreview");
  preview.innerHTML = '<span class="cover-empty">Verra rimossa al salvataggio</span>';
  const hint = $("#metaCoverHint");
  hint.textContent = "Copertina marcata per rimozione";
  hint.className = "cover-hint remove";
});

$("#metaReloadBtn").addEventListener("click", async () => {
  if (state.meta.path) await loadMetaFile(state.meta.path);
});

$("#metaSaveBtn").addEventListener("click", async () => {
  if (!state.meta.path) {
    toast("Nessun file caricato", "error");
    return;
  }

  $("#metaSaveBtn").disabled = true;
  const status = $("#metaStatus");
  status.textContent = "Salvataggio…";

  const payload = {
    path: state.meta.path,
    data: {
      title: $("#metaTitle").value,
      artist: $("#metaArtist").value,
      album: $("#metaAlbum").value,
      album_artist: $("#metaAlbumArtist").value,
      year: $("#metaYear").value,
      track: $("#metaTrack").value,
      genre: $("#metaGenre").value,
      bpm: $("#metaBpm").value,
      key: $("#metaKey").value,
      comment: $("#metaComment").value,
      where_from: $("#metaWhereFrom").value
        .split("\n")
        .map(s => s.trim())
        .filter(Boolean),
    },
    cover_path: state.meta.newCoverPath,
    remove_cover: state.meta.removeCover,
  };

  const res = await window.pywebview.api.save_metadata(payload);
  $("#metaSaveBtn").disabled = false;

  if (res.ok) {
    status.textContent = "✓ Tag salvati";
    toast("Tag salvati", "success");
    // Ricarica per mostrare lo stato aggiornato (es. nuova cover)
    await loadMetaFile(state.meta.path);
  } else {
    status.textContent = "";
    if (!handleGateBlock(res)) toast("Errore: " + (res.error || ""), "error");
  }
});

// ============================================================
// SETTINGS tab
// ============================================================
$("#toggleSecretBtn").addEventListener("click", () => {
  state.showSecret = !state.showSecret;
  $("#clientSecretInput").type = state.showSecret ? "text" : "password";
  $("#toggleSecretBtn").textContent = state.showSecret ? "Nascondi" : "Mostra";
});

$("#browseCookiesBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_file([
    "Text files (*.txt)",
    "All files (*.*)",
  ]);
  if (path) $("#cookiesInput").value = path;
});

$("#browseOutputBtn").addEventListener("click", async () => {
  const path = await window.pywebview.api.browse_directory();
  if (path) $("#outputInput").value = path;
});

$("#themeSelect").addEventListener("change", (e) => {
  applyTheme(e.target.value);
});

$("#saveBtn").addEventListener("click", async () => {
  const payload = {
    client_id: $("#clientIdInput").value,
    client_secret: $("#clientSecretInput").value,
    bitrate: $("#bitrateSelect").value,
    hq_threshold: parseInt($("#hqThresholdInput").value, 10) || 310,
    cookies_path: $("#cookiesInput").value,
    cookies_browser: $("#cookiesBrowserSelect") ? $("#cookiesBrowserSelect").value : "",
    output_dir: $("#outputInput").value,
    theme: $("#themeSelect").value,
  };
  applyTheme(payload.theme);
  const res = await window.pywebview.api.save_settings(payload);
  if (res.ok) {
    state.config = payload;
    // sync Download tab default path
    if (!state.dlOutputDir && payload.output_dir) {
      state.dlOutputDir = payload.output_dir;
      $("#dlPathDisplay").textContent = payload.output_dir;
      $("#dlPathDisplay").classList.remove("empty");
    }
    const status = $("#saveStatus");
    status.textContent = "✓ Impostazioni salvate";
    status.classList.add("show");
    setTimeout(() => status.classList.remove("show"), 2500);
  } else {
    toast("Errore nel salvataggio", "error");
  }
});

$("#openDashboardBtn").addEventListener("click", () => {
  window.pywebview.api.open_external_url("https://developer.spotify.com/dashboard");
});

$("#showGuideBtn").addEventListener("click", () => {
  $("#guideModal").hidden = false;
});

$("#guideCloseBtn").addEventListener("click", () => { $("#guideModal").hidden = true; });
$("#guideCloseBtn2").addEventListener("click", () => { $("#guideModal").hidden = true; });
$("#guideOpenDashBtn").addEventListener("click", () => {
  window.pywebview.api.open_external_url("https://developer.spotify.com/dashboard");
});

$("#checkUpdateBtn").addEventListener("click", async () => {
  const btn = $("#checkUpdateBtn");
  const status = $("#updateStatus");
  const notes = $("#updateNotes");
  const dlBtn = $("#downloadUpdateBtn");

  btn.disabled = true;
  btn.textContent = "Controllo...";
  status.className = "update-status";
  status.textContent = "";
  notes.textContent = "";
  dlBtn.hidden = true;

  const res = await window.pywebview.api.check_update();
  btn.disabled = false;
  btn.textContent = "Controlla aggiornamenti";

  if (!res.ok) {
    status.className = "update-status err";
    status.textContent = "Errore: " + (res.error || "");
    return;
  }
  if (res.is_new) {
    status.className = "update-status warn";
    status.textContent = `Nuova versione disponibile: ${res.remote}`;
    if (res.download_url) {
      dlBtn.hidden = false;
      dlBtn.onclick = () => window.pywebview.api.open_external_url(res.download_url);
    }
    if (res.notes) notes.textContent = res.notes;
  } else {
    status.className = "update-status ok";
    status.textContent = "✓ Sei aggiornato!";
  }
});

// ============================================================
// Licenza: listener dello schermo di attivazione + impostazioni
// ============================================================
$("#actActivateBtn")?.addEventListener("click", activateLicense);
$("#actBuyBtn")?.addEventListener("click", async () => {
  await window.pywebview.api.open_purchase_page();
});
$("#actKey")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") activateLicense();
});

$("#deactivateLicenseBtn")?.addEventListener("click", deactivateLicense);

$("#revalidateLicenseBtn")?.addEventListener("click", async () => {
  const btn = $("#revalidateLicenseBtn");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "Verifica in corso…";
  try {
    const res = await window.pywebview.api.revalidate_license();
    if (res.ok) {
      state.license = res.license;
      renderLicenseStatus();
      applyPlanGate();
      refreshQuota();
      if (res.license.licensed) {
        toast("Licenza verificata", "success");
      } else {
        applyLicenseGate();
        toast("Licenza non piu valida", "error");
      }
    }
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
});

// ============================================================
// Modal Upgrade
// ============================================================
$("#upgradeCloseBtn")?.addEventListener("click", hideUpgradeModal);
$("#upgradeCloseBtn2")?.addEventListener("click", hideUpgradeModal);
$("#upgradeModal")?.addEventListener("click", (e) => {
  if (e.target === e.currentTarget) hideUpgradeModal();
});
$("#upgradeOpenBtn")?.addEventListener("click", async () => {
  hideUpgradeModal();
  try { await window.pywebview.api.open_purchase_page(); } catch (_e) {}
});
$("#quotaUpgradeBtn")?.addEventListener("click", async () => {
  try { await window.pywebview.api.open_purchase_page(); } catch (_e) {}
});

// ============================================================
// Helper di ordinamento condivisi tra BeatportUI, SpotifyUI, YoutubeUI
// ============================================================
function _sortPairs(tracks, existing, col, dir) {
  const pairs = tracks.map((t, i) => ({ t, e: existing[i] || false, origIdx: i }));
  const dirMul = dir === "desc" ? -1 : 1;
  pairs.sort((a, b) => {
    let av = a.t[col], bv = b.t[col];
    if (col === "position") {
      // Per Beatport t.position esiste (rank ufficiale); per Spotify/YouTube
      // torniamo l'ordine originale della risposta API.
      av = (typeof av === "number") ? av : a.origIdx;
      bv = (typeof bv === "number") ? bv : b.origIdx;
    }
    if (typeof av === "number" && typeof bv === "number") {
      return (av - bv) * dirMul;
    }
    av = String(av == null ? "" : av).toLowerCase();
    bv = String(bv == null ? "" : bv).toLowerCase();
    // Empty strings sempre in fondo indipendentemente da direzione
    if (av === "" && bv !== "") return 1;
    if (bv === "" && av !== "") return -1;
    if (av < bv) return -1 * dirMul;
    if (av > bv) return 1 * dirMul;
    return 0;
  });
  return {
    tracks: pairs.map(p => p.t),
    existing: pairs.map(p => p.e),
    origIndexes: pairs.map(p => p.origIdx),
  };
}

function _bindSortableHeaders(tableSelector, onSort) {
  document.querySelectorAll(`${tableSelector} th.sortable`).forEach(th => {
    th.style.cursor = "pointer";
    th.style.userSelect = "none";
    th.addEventListener("click", () => onSort(th.dataset.sort));
  });
}

function _updateSortArrows(tableSelector, sortCol, sortDir) {
  document.querySelectorAll(`${tableSelector} th.sortable`).forEach(th => {
    const key = th.dataset.sort;
    // Usa un <span class="sort-arrow"> per non toccare il testo principale
    let arrow = th.querySelector(".sort-arrow");
    if (!arrow) {
      arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      th.appendChild(arrow);
    }
    arrow.textContent = key === sortCol ? (sortDir === "asc" ? " ▲" : " ▼") : "";
  });
}

// ============================================================
// BEATPORT tab — carica Top 100 per genere, seleziona tracce, scarica
// (il download riusa start_tracks_download, quindi passa dagli stessi
// canali "download:progress" / "download:done" / log view="download")
// ============================================================
const BeatportUI = (function () {
  let genres = [];
  let currentTracks = [];
  let existing = [];
  let currentGenreName = "";
  let currentGenreSlug = "";
  let downloading = false;
  let sortCol = null;
  let sortDir = "asc";

  function fmtDur(sec) {
    const n = Number(sec) || 0;
    const m = Math.floor(n / 60);
    const s = Math.floor(n % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function safeGenreFolder(name) {
    return String(name || "").replace(/[\/\\]/g, "_").trim();
  }

  function populateSelect() {
    const sel = $("#beatport-genre");
    if (!sel) return;
    sel.innerHTML = "";
    for (const g of genres) {
      const opt = document.createElement("option");
      opt.value = g.slug;
      opt.textContent = g.name;
      sel.appendChild(opt);
    }
  }

  function updateOutputInfo() {
    const info = $("#beatport-output-info");
    if (!info) return;
    const root = (state.config && state.config.output_dir) || "";
    if (!root) {
      info.textContent = "⚠ Imposta la cartella output in Impostazioni prima di scaricare";
      info.className = "beatport-output-info warn";
      return;
    }
    const folder = safeGenreFolder(currentGenreName);
    info.textContent = folder
      ? `Destinazione: ${root}/Beatport/${folder}`
      : `Destinazione: ${root}/Beatport`;
    info.className = "beatport-output-info";
  }

  function setStatus(text, kind) {
    const el = $("#beatport-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "beatport-status" + (kind ? " " + kind : "");
  }

  async function loadChart(forceRefresh) {
    const sel = $("#beatport-genre");
    const slug = sel && sel.value;
    if (!slug) return;
    const genreName = (sel.selectedOptions[0] && sel.selectedOptions[0].textContent) || slug;
    currentGenreSlug = slug;
    currentGenreName = genreName;

    setStatus(forceRefresh ? "Ricarico Top 100 (bypass cache)…" : "Caricamento Top 100…", "loading");
    $("#beatport-table").hidden = true;
    $("#beatport-toolbar").hidden = true;
    $("#beatport-table").querySelector("tbody").innerHTML = "";

    let res;
    try {
      res = await window.pywebview.api.beatport_fetch_chart(slug, !!forceRefresh);
    } catch (e) {
      setStatus("Errore: " + ((e && e.message) || e), "error");
      return;
    }
    if (!res || !res.ok) {
      const code = res && res.error;
      let msg = (res && res.message) || "Errore sconosciuto";
      if (code === "invalid_genre") msg = "Genere non valido";
      else if (code === "unreachable") msg = "Beatport non raggiungibile — riprova più tardi";
      else if (code === "parse") msg = "Impossibile leggere i dati (schema pagina cambiato?)";
      setStatus(msg, "error");
      return;
    }

    currentTracks = res.tracks || [];
    try {
      existing = await window.pywebview.api.beatport_check_existing(currentTracks, currentGenreName);
    } catch (_e) {
      existing = currentTracks.map(() => false);
    }
    setStatus(`${currentTracks.length} brani caricati`, "ok");
    renderTable();
  }

  function renderTable() {
    const table = $("#beatport-table");
    const tbody = table.querySelector("tbody");
    tbody.innerHTML = "";

    let displayTracks = currentTracks;
    let displayExisting = existing;
    let origIndexes = currentTracks.map((_, i) => i);
    if (sortCol) {
      const s = _sortPairs(currentTracks, existing, sortCol, sortDir);
      displayTracks = s.tracks;
      displayExisting = s.existing;
      origIndexes = s.origIndexes;
    }

    displayTracks.forEach((t, i) => {
      const origIdx = origIndexes[i];
      const alreadyDl = displayExisting[i];
      const tr = document.createElement("tr");
      if (alreadyDl) tr.classList.add("already-downloaded");

      const tdCheck = document.createElement("td");
      tdCheck.className = "col-check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.idx = String(origIdx);
      cb.checked = !alreadyDl;
      cb.addEventListener("change", updateSelectionCount);
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);

      const tdCover = document.createElement("td");
      tdCover.className = "col-cover";
      if (t.image_url) {
        const img = document.createElement("img");
        img.src = t.image_url;
        img.alt = "";
        img.loading = "lazy";
        img.referrerPolicy = "no-referrer";
        img.onerror = () => { img.style.visibility = "hidden"; };
        tdCover.appendChild(img);
      }
      tr.appendChild(tdCover);

      const tdPos = document.createElement("td");
      tdPos.className = "col-pos";
      tdPos.textContent = String(t.position || (origIdx + 1));
      tr.appendChild(tdPos);

      const tdArtist = document.createElement("td");
      tdArtist.textContent = t.artists || "";
      tr.appendChild(tdArtist);

      const tdTitle = document.createElement("td");
      tdTitle.textContent = t.mix ? `${t.title} (${t.mix})` : (t.title || "");
      tr.appendChild(tdTitle);

      const tdDur = document.createElement("td");
      tdDur.className = "col-dur";
      tdDur.textContent = fmtDur(t.duration_sec);
      tr.appendChild(tdDur);

      const tdDate = document.createElement("td");
      tdDate.className = "col-date";
      tdDate.textContent = t.release_date || "";
      tr.appendChild(tdDate);

      const tdState = document.createElement("td");
      tdState.className = "col-state";
      if (alreadyDl) tdState.textContent = "✓ già scaricato";
      tr.appendChild(tdState);

      tbody.appendChild(tr);
    });

    _updateSortArrows("#beatport-table", sortCol, sortDir);
    table.hidden = false;
    $("#beatport-toolbar").hidden = false;
    updateOutputInfo();
    updateSelectionCount();
  }

  function handleSort(col) {
    if (sortCol === col) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortCol = col;
      sortDir = "asc";
    }
    renderTable();
  }

  function updateSelectionCount() {
    const boxes = $$("#beatport-table tbody input[type=checkbox]");
    const total = boxes.length;
    const checked = boxes.filter((b) => b.checked).length;
    $("#beatport-selected-count").textContent = `${checked}/${total} selezionati`;
    const dlBtn = $("#beatport-download-btn");
    if (dlBtn) dlBtn.disabled = downloading || checked === 0;

    const master = $("#beatport-select-all");
    if (master) {
      if (total === 0) { master.checked = false; master.indeterminate = false; }
      else if (checked === 0) { master.checked = false; master.indeterminate = false; }
      else if (checked === total) { master.checked = true; master.indeterminate = false; }
      else { master.checked = false; master.indeterminate = true; }
    }
  }

  function toggleAll(checked) {
    $$("#beatport-table tbody input[type=checkbox]").forEach((b) => { b.checked = checked; });
    updateSelectionCount();
  }

  function appendBeatportLog(msg) {
    const el = $("#beatport-log");
    if (!el) return;
    const cls = classifyLog(msg);
    const line = document.createElement("div");
    if (cls) line.className = cls;
    line.textContent = msg;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  async function startDownload() {
    const boxes = $$("#beatport-table tbody input[type=checkbox]");
    const selected = [];
    boxes.forEach((b) => {
      if (b.checked) {
        const idx = parseInt(b.dataset.idx, 10);
        if (!isNaN(idx) && currentTracks[idx]) selected.push(currentTracks[idx]);
      }
    });
    if (!selected.length) {
      toast("Seleziona almeno un brano", "error");
      return;
    }
    if (!state.config || !state.config.output_dir) {
      toast("Imposta la cartella output in Impostazioni", "error");
      return;
    }

    downloading = true;
    $("#beatport-download-btn").disabled = true;
    $("#beatport-stop-btn").hidden = false;
    $("#beatport-stop-btn").disabled = false;
    $("#beatport-log").innerHTML = "";
    appendBeatportLog(`[INFO] Avvio download di ${selected.length} brani da ${currentGenreName}…`);

    let res;
    try {
      res = await window.pywebview.api.beatport_download_selected(selected, currentGenreName);
    } catch (e) {
      appendBeatportLog("[ERRORE] " + ((e && e.message) || e));
      finishDownload();
      return;
    }
    if (!res || !res.ok) {
      const errMsg = (res && (res.error || res.message)) || "Impossibile avviare il download";
      appendBeatportLog("[ERRORE] " + errMsg);
      if (!handleGateBlock(res || {})) toast(errMsg, "error");
      finishDownload();
    }
  }

  async function stopDownload() {
    try {
      await window.pywebview.api.stop_download();
    } catch (e) { console.error(e); }
  }

  function finishDownload() {
    downloading = false;
    $("#beatport-stop-btn").hidden = true;
    $("#beatport-stop-btn").disabled = true;
    updateSelectionCount();
    // Re-check existing per aggiornare i badge "già scaricato"
    if (currentTracks.length) {
      window.pywebview.api.beatport_check_existing(currentTracks, currentGenreName)
        .then((res) => { existing = res || existing; renderTable(); })
        .catch(() => {});
    }
  }

  async function init() {
    // Popola dropdown generi
    try {
      genres = await window.pywebview.api.beatport_genres();
    } catch (e) {
      console.error("Beatport: impossibile caricare i generi", e);
      genres = [];
    }
    populateSelect();

    // Ripristina l'ultimo genere selezionato (state.config gia' caricato)
    const last = (state.config && state.config.beatport_last_genre) || "";
    const sel = $("#beatport-genre");
    if (sel && last && genres.some((g) => g.slug === last)) {
      sel.value = last;
    }
    updateOutputInfo();

    // Bind eventi
    $("#beatport-load-btn").addEventListener("click", (e) => loadChart(e.shiftKey));
    $("#beatport-download-btn").addEventListener("click", startDownload);
    $("#beatport-stop-btn").addEventListener("click", stopDownload);
    $("#beatport-select-all").addEventListener("change", (e) => toggleAll(e.target.checked));
    _bindSortableHeaders("#beatport-table", handleSort);

    // Aggancia agli event listener esistenti del canale "download" senza rompere
    // il comportamento della tab Scarica (wrapping additivo).
    const origProgress = bridgeHandlers["download:progress"];
    bridgeHandlers["download:progress"] = (p) => {
      if (origProgress) origProgress(p);
      // I contatori del tab Scarica sono aggiornati dall'handler originale;
      // qui potremmo aggiungere un contatore Beatport, ma i log sono sufficienti.
    };
    const origDone = bridgeHandlers["download:done"];
    bridgeHandlers["download:done"] = (p) => {
      if (origDone) origDone(p);
      if (downloading) finishDownload();
    };
    const origLog = bridgeHandlers["log"];
    bridgeHandlers["log"] = ({ view, msg }) => {
      if (origLog) origLog({ view, msg });
      if (downloading && view === "download") appendBeatportLog(msg);
    };
  }

  return { init };
})();

// =====================================================================
// Spotify search
// =====================================================================
const SpotifyUI = (() => {
  // NOTE: local module state — named `mstate` to NOT shadow the outer
  // module-level `state` (which holds `state.config`).
  const mstate = { tracks: [], existing: [], downloading: false, sortCol: null, sortDir: "asc" };

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function _fmtDuration(sec) {
    const n = Math.max(0, Math.floor(Number(sec) || 0));
    const m = Math.floor(n / 60);
    const s = n % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function updateSelectionCount() {
    const boxes = $$("#spotify-tbody input[type=checkbox]");
    const total = boxes.length;
    const selected = boxes.filter((b) => b.checked).length;
    $("#spotify-selected-count").textContent = `${selected}/${total} selezionati`;
    const btn = $("#spotify-download-btn");
    if (btn) {
      btn.disabled = mstate.downloading || selected === 0;
      btn.innerHTML = `<span class="ico">▶</span> Scarica selezionati${selected ? ` (${selected})` : ""}`;
    }
    const sa = $("#spotify-select-all");
    if (sa) {
      if (total === 0) { sa.checked = false; sa.indeterminate = false; }
      else if (selected === 0) { sa.checked = false; sa.indeterminate = false; }
      else if (selected === total) { sa.checked = true; sa.indeterminate = false; }
      else { sa.checked = false; sa.indeterminate = true; }
    }
  }

  function renderTable() {
    const tbody = $("#spotify-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    let displayTracks = mstate.tracks;
    let displayExisting = mstate.existing;
    let origIndexes = mstate.tracks.map((_, i) => i);
    if (mstate.sortCol) {
      const s = _sortPairs(mstate.tracks, mstate.existing, mstate.sortCol, mstate.sortDir);
      displayTracks = s.tracks;
      displayExisting = s.existing;
      origIndexes = s.origIndexes;
    }

    displayTracks.forEach((t, i) => {
      const origIdx = origIndexes[i];
      const already = !!displayExisting[i];
      const tr = document.createElement("tr");
      tr.dataset.idx = String(origIdx);
      if (already) tr.classList.add("already-downloaded");
      const coverImg = t.image_url
        ? `<img src="${_escape(t.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'"/>`
        : "";
      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" data-idx="${origIdx}" ${already ? "" : "checked"} /></td>
        <td class="col-cover">${coverImg}</td>
        <td class="col-pos">${origIdx + 1}</td>
        <td>${_escape(t.artists)}</td>
        <td>${_escape(t.name)}</td>
        <td>${_escape(t.album)}</td>
        <td class="col-dur">${_fmtDuration(t.duration_sec)}</td>
        <td class="col-date">${_escape(t.release_date || "")}</td>
        <td class="col-state">${already ? "✓ già scaricato" : ""}</td>
      `;
      const cb = tr.querySelector("input[type=checkbox]");
      if (cb) cb.addEventListener("change", updateSelectionCount);
      tbody.appendChild(tr);
    });
    _updateSortArrows("#spotify-table", mstate.sortCol, mstate.sortDir);
    updateSelectionCount();
  }

  function handleSort(col) {
    if (mstate.sortCol === col) {
      mstate.sortDir = mstate.sortDir === "asc" ? "desc" : "asc";
    } else {
      mstate.sortCol = col;
      mstate.sortDir = "asc";
    }
    renderTable();
  }

  function setStatus(text, kind) {
    const el = $("#spotify-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "beatport-status" + (kind ? " " + kind : "");
  }

  function updateOutputInfo() {
    const info = $("#spotify-output-info");
    if (!info) return;
    const root = (state.config && state.config.output_dir) || "";
    if (!root) {
      info.textContent = "⚠ Imposta la cartella output in Impostazioni prima di scaricare";
      info.className = "beatport-output-info warn";
    } else {
      info.textContent = `Destinazione: ${root}/Spotify`;
      info.className = "beatport-output-info";
    }
  }

  async function doSearch() {
    const q = ($("#spotify-query").value || "").trim();
    if (!q) return;
    const artistMode = $("#spotify-artist-mode").checked;
    const wrap = $("#spotify-table-wrap");

    setStatus("Ricerca in corso…", "loading");
    if (wrap) wrap.hidden = true;

    let res;
    try {
      res = await window.pywebview.api.spotify_search(q, artistMode);
    } catch (e) {
      setStatus("Errore: " + ((e && e.message) || e), "error");
      return;
    }
    if (!res || !res.ok) {
      const errKey = res && res.error;
      const messages = {
        empty_query: "Inserisci una query di ricerca.",
        no_creds: "Credenziali Spotify mancanti. Vai su Impostazioni.",
        auth: "Impossibile autenticarsi con Spotify. Verifica le credenziali.",
      };
      setStatus(messages[errKey] || (res && res.message) || "Errore sconosciuto", "error");
      return;
    }

    mstate.tracks = res.tracks || [];
    if (mstate.tracks.length === 0) {
      setStatus(`Nessun brano trovato per "${q}".`, "");
      return;
    }
    try {
      mstate.existing = await window.pywebview.api.spotify_check_existing(mstate.tracks);
    } catch (_e) {
      mstate.existing = mstate.tracks.map(() => false);
    }

    setStatus(`${mstate.tracks.length} risultati`, "ok");
    updateOutputInfo();
    renderTable();
    if (wrap) wrap.hidden = false;
  }

  function appendSpotifyLog(msg) {
    const el = $("#spotify-log");
    if (!el) return;
    const cls = classifyLog(msg);
    const line = document.createElement("div");
    if (cls) line.className = cls;
    line.textContent = msg;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  async function startDownload() {
    const boxes = $$("#spotify-tbody input[type=checkbox]");
    const selected = [];
    boxes.forEach((b) => {
      if (b.checked) {
        const idx = parseInt(b.dataset.idx, 10);
        if (!isNaN(idx) && mstate.tracks[idx]) selected.push(mstate.tracks[idx]);
      }
    });
    if (!selected.length) {
      toast("Seleziona almeno un brano", "error");
      return;
    }
    if (!state.config || !state.config.output_dir) {
      toast("Imposta la cartella output in Impostazioni", "error");
      return;
    }

    mstate.downloading = true;
    $("#spotify-download-btn").disabled = true;
    $("#spotify-stop-btn").hidden = false;
    $("#spotify-stop-btn").disabled = false;
    $("#spotify-log").innerHTML = "";
    appendSpotifyLog(`[INFO] Avvio download di ${selected.length} brani…`);

    let res;
    try {
      res = await window.pywebview.api.spotify_search_download(selected);
    } catch (e) {
      appendSpotifyLog("[ERRORE] " + ((e && e.message) || e));
      finishDownload();
      return;
    }
    if (!res || !res.ok) {
      const errMsg = (res && (res.error || res.message)) || "Impossibile avviare il download";
      appendSpotifyLog("[ERRORE] " + errMsg);
      if (!handleGateBlock(res || {})) toast(errMsg, "error");
      finishDownload();
    }
  }

  async function stopDownload() {
    try { await window.pywebview.api.stop_download(); } catch (e) { console.error(e); }
  }

  function finishDownload() {
    mstate.downloading = false;
    $("#spotify-stop-btn").hidden = true;
    $("#spotify-stop-btn").disabled = true;
    updateSelectionCount();
    if (mstate.tracks.length) {
      window.pywebview.api.spotify_check_existing(mstate.tracks)
        .then((r) => { mstate.existing = r || mstate.existing; renderTable(); })
        .catch(() => {});
    }
  }

  async function init() {
    // Pre-compila da config
    try {
      const q = (state.config && state.config.spotify_search_last_query) || "";
      const am = !!(state.config && state.config.spotify_search_artist_mode);
      const qi = $("#spotify-query");
      if (qi && q) qi.value = q;
      const ac = $("#spotify-artist-mode");
      if (ac) ac.checked = am;
    } catch (_e) { /* ignora */ }

    updateOutputInfo();

    $("#spotify-search-btn").addEventListener("click", doSearch);
    $("#spotify-query").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
    $("#spotify-select-all").addEventListener("change", (e) => {
      $$("#spotify-tbody input[type=checkbox]").forEach((b) => { b.checked = e.target.checked; });
      updateSelectionCount();
    });
    $("#spotify-download-btn").addEventListener("click", startDownload);
    $("#spotify-stop-btn").addEventListener("click", stopDownload);
    _bindSortableHeaders("#spotify-table", handleSort);

    // Wrap bridge handlers additivamente
    const origLog = bridgeHandlers["log"];
    bridgeHandlers["log"] = (payload) => {
      if (origLog) origLog(payload);
      if (mstate.downloading && payload && payload.view === "download") {
        appendSpotifyLog(payload.msg);
      }
    };
    const origDone = bridgeHandlers["download:done"];
    bridgeHandlers["download:done"] = (payload) => {
      if (origDone) origDone(payload);
      if (mstate.downloading) finishDownload();
    };
  }

  return { init };
})();

// =====================================================================
// YouTube search
// =====================================================================
const YoutubeUI = (() => {
  const mstate = { tracks: [], existing: [], downloading: false, sortCol: null, sortDir: "asc" };

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
  function _fmtDuration(sec) {
    const n = Math.max(0, Math.floor(Number(sec) || 0));
    const m = Math.floor(n / 60);
    const s = n % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function updateSelectionCount() {
    const boxes = $$("#youtube-tbody input[type=checkbox]");
    const total = boxes.length;
    const selected = boxes.filter((b) => b.checked).length;
    $("#youtube-selected-count").textContent = `${selected}/${total} selezionati`;
    const btn = $("#youtube-download-btn");
    if (btn) {
      btn.disabled = mstate.downloading || selected === 0;
      btn.innerHTML = `<span class="ico">▶</span> Scarica selezionati${selected ? ` (${selected})` : ""}`;
    }
    const sa = $("#youtube-select-all");
    if (sa) {
      if (total === 0) { sa.checked = false; sa.indeterminate = false; }
      else if (selected === 0) { sa.checked = false; sa.indeterminate = false; }
      else if (selected === total) { sa.checked = true; sa.indeterminate = false; }
      else { sa.checked = false; sa.indeterminate = true; }
    }
  }

  function renderTable() {
    const tbody = $("#youtube-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    let displayTracks = mstate.tracks;
    let displayExisting = mstate.existing;
    let origIndexes = mstate.tracks.map((_, i) => i);
    if (mstate.sortCol) {
      const s = _sortPairs(mstate.tracks, mstate.existing, mstate.sortCol, mstate.sortDir);
      displayTracks = s.tracks;
      displayExisting = s.existing;
      origIndexes = s.origIndexes;
    }

    displayTracks.forEach((t, i) => {
      const origIdx = origIndexes[i];
      const already = !!displayExisting[i];
      const tr = document.createElement("tr");
      tr.dataset.idx = String(origIdx);
      if (already) tr.classList.add("already-downloaded");
      const coverImg = t.image_url
        ? `<img src="${_escape(t.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'"/>`
        : "";
      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" data-idx="${origIdx}" ${already ? "" : "checked"} /></td>
        <td class="col-cover">${coverImg}</td>
        <td class="col-pos">${origIdx + 1}</td>
        <td>${_escape(t.title)}</td>
        <td>${_escape(t.channel)}</td>
        <td class="col-dur">${_fmtDuration(t.duration_sec)}</td>
        <td class="col-date">${_escape(t.release_date || "")}</td>
        <td class="col-state">${already ? "✓ già scaricato" : ""}</td>
      `;
      const cb = tr.querySelector("input[type=checkbox]");
      if (cb) cb.addEventListener("change", updateSelectionCount);
      tbody.appendChild(tr);
    });
    _updateSortArrows("#youtube-table", mstate.sortCol, mstate.sortDir);
    updateSelectionCount();
  }

  function handleSort(col) {
    if (mstate.sortCol === col) {
      mstate.sortDir = mstate.sortDir === "asc" ? "desc" : "asc";
    } else {
      mstate.sortCol = col;
      mstate.sortDir = "asc";
    }
    renderTable();
  }

  function setStatus(text, kind) {
    const el = $("#youtube-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "beatport-status" + (kind ? " " + kind : "");
  }

  function updateOutputInfo() {
    const info = $("#youtube-output-info");
    if (!info) return;
    const root = (state.config && state.config.output_dir) || "";
    if (!root) {
      info.textContent = "⚠ Imposta la cartella output in Impostazioni prima di scaricare";
      info.className = "beatport-output-info warn";
    } else {
      info.textContent = `Destinazione: ${root}/YouTube`;
      info.className = "beatport-output-info";
    }
  }

  async function doSearch() {
    const q = ($("#youtube-query").value || "").trim();
    if (!q) return;
    const wrap = $("#youtube-table-wrap");

    setStatus("Ricerca su YouTube in corso…", "loading");
    if (wrap) wrap.hidden = true;

    let res;
    try {
      res = await window.pywebview.api.youtube_search(q);
    } catch (e) {
      setStatus("Errore: " + ((e && e.message) || e), "error");
      return;
    }
    if (!res || !res.ok) {
      setStatus((res && res.message) || "Errore sconosciuto", "error");
      return;
    }

    mstate.tracks = res.tracks || [];
    if (mstate.tracks.length === 0) {
      setStatus(`Nessun video trovato per "${q}".`, "");
      return;
    }
    try {
      mstate.existing = await window.pywebview.api.youtube_check_existing(mstate.tracks);
    } catch (_e) {
      mstate.existing = mstate.tracks.map(() => false);
    }

    setStatus(`${mstate.tracks.length} risultati`, "ok");
    updateOutputInfo();
    renderTable();
    if (wrap) wrap.hidden = false;
  }

  function appendYoutubeLog(msg) {
    const el = $("#youtube-log");
    if (!el) return;
    const cls = classifyLog(msg);
    const line = document.createElement("div");
    if (cls) line.className = cls;
    line.textContent = msg;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  async function startDownload() {
    const boxes = $$("#youtube-tbody input[type=checkbox]");
    const selected = [];
    boxes.forEach((b) => {
      if (b.checked) {
        const idx = parseInt(b.dataset.idx, 10);
        if (!isNaN(idx) && mstate.tracks[idx]) selected.push(mstate.tracks[idx]);
      }
    });
    if (!selected.length) {
      toast("Seleziona almeno un video", "error");
      return;
    }
    if (!state.config || !state.config.output_dir) {
      toast("Imposta la cartella output in Impostazioni", "error");
      return;
    }

    mstate.downloading = true;
    $("#youtube-download-btn").disabled = true;
    $("#youtube-stop-btn").hidden = false;
    $("#youtube-stop-btn").disabled = false;
    $("#youtube-log").innerHTML = "";
    appendYoutubeLog(`[INFO] Avvio download di ${selected.length} video…`);

    let res;
    try {
      res = await window.pywebview.api.youtube_search_download(selected);
    } catch (e) {
      appendYoutubeLog("[ERRORE] " + ((e && e.message) || e));
      finishDownload();
      return;
    }
    if (!res || !res.ok) {
      const errMsg = (res && (res.error || res.message)) || "Impossibile avviare il download";
      appendYoutubeLog("[ERRORE] " + errMsg);
      if (!handleGateBlock(res || {})) toast(errMsg, "error");
      finishDownload();
    }
  }

  async function stopDownload() {
    try { await window.pywebview.api.stop_download(); } catch (e) { console.error(e); }
  }

  function finishDownload() {
    mstate.downloading = false;
    $("#youtube-stop-btn").hidden = true;
    $("#youtube-stop-btn").disabled = true;
    updateSelectionCount();
    if (mstate.tracks.length) {
      window.pywebview.api.youtube_check_existing(mstate.tracks)
        .then((r) => { mstate.existing = r || mstate.existing; renderTable(); })
        .catch(() => {});
    }
  }

  async function init() {
    try {
      const q = (state.config && state.config.youtube_search_last_query) || "";
      const qi = $("#youtube-query");
      if (qi && q) qi.value = q;
    } catch (_e) { /* ignora */ }

    updateOutputInfo();

    $("#youtube-search-btn").addEventListener("click", doSearch);
    $("#youtube-query").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
    $("#youtube-select-all").addEventListener("change", (e) => {
      $$("#youtube-tbody input[type=checkbox]").forEach((b) => { b.checked = e.target.checked; });
      updateSelectionCount();
    });
    $("#youtube-download-btn").addEventListener("click", startDownload);
    $("#youtube-stop-btn").addEventListener("click", stopDownload);
    _bindSortableHeaders("#youtube-table", handleSort);

    const origLog = bridgeHandlers["log"];
    bridgeHandlers["log"] = (payload) => {
      if (origLog) origLog(payload);
      if (mstate.downloading && payload && payload.view === "download") {
        appendYoutubeLog(payload.msg);
      }
    };
    const origDone = bridgeHandlers["download:done"];
    bridgeHandlers["download:done"] = (payload) => {
      if (origDone) origDone(payload);
      if (mstate.downloading) finishDownload();
    };
  }

  return { init };
})();

// ============================================================
// TRAXSOURCE tab — carica Top 100 per genere, seleziona tracce, scarica
// Parallelo a BeatportUI (stessi canali "download:progress" /
// "download:done" / log view="download"). Colonne: cover, #, artista,
// titolo (mix), label, stato. No Durata / Data (non nel markup Traxsource).
// ============================================================
const TraxsourceUI = (function () {
  let genres = [];
  let currentTracks = [];
  let existing = [];
  let currentGenreName = "";
  let currentGenreSlug = "";
  let downloading = false;
  let sortCol = null;
  let sortDir = "asc";

  function safeGenreFolder(name) {
    return String(name || "").replace(/[\/\\]/g, "_").trim();
  }

  function populateSelect() {
    const sel = $("#traxsource-genre");
    if (!sel) return;
    sel.innerHTML = "";
    for (const g of genres) {
      const opt = document.createElement("option");
      opt.value = g.slug;
      opt.textContent = g.name;
      sel.appendChild(opt);
    }
  }

  function updateOutputInfo() {
    const info = $("#traxsource-output-info");
    if (!info) return;
    const root = (state.config && state.config.output_dir) || "";
    if (!root) {
      info.textContent = "⚠ Imposta la cartella output in Impostazioni prima di scaricare";
      info.className = "beatport-output-info warn";
      return;
    }
    const folder = safeGenreFolder(currentGenreName);
    info.textContent = folder
      ? `Destinazione: ${root}/Traxsource_${folder}`
      : `Destinazione: ${root}/Traxsource`;
    info.className = "beatport-output-info";
  }

  function setStatus(text, kind) {
    const el = $("#traxsource-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "beatport-status" + (kind ? " " + kind : "");
  }

  async function loadChart(forceRefresh) {
    const sel = $("#traxsource-genre");
    const slug = sel && sel.value;
    if (!slug) return;
    const genreName = (sel.selectedOptions[0] && sel.selectedOptions[0].textContent) || slug;
    currentGenreSlug = slug;
    currentGenreName = genreName;

    setStatus(forceRefresh ? "Ricarico Top 100 (bypass cache)…" : "Caricamento Top 100…", "loading");
    $("#traxsource-table").hidden = true;
    $("#traxsource-toolbar").hidden = true;
    $("#traxsource-table").querySelector("tbody").innerHTML = "";

    let res;
    try {
      res = await window.pywebview.api.traxsource_fetch_chart(slug, !!forceRefresh);
    } catch (e) {
      setStatus("Errore: " + ((e && e.message) || e), "error");
      return;
    }
    if (!res || !res.ok) {
      const code = res && res.error;
      let msg = (res && res.message) || "Errore sconosciuto";
      if (code === "invalid_genre") msg = "Genere non valido";
      else if (code === "unreachable") msg = "Traxsource non raggiungibile — riprova più tardi";
      else if (code === "parse") msg = "Impossibile leggere i dati (schema pagina cambiato?)";
      setStatus(msg, "error");
      return;
    }

    currentTracks = res.tracks || [];
    try {
      existing = await window.pywebview.api.traxsource_check_existing(currentTracks, currentGenreName);
    } catch (_e) {
      existing = currentTracks.map(() => false);
    }
    setStatus(`${currentTracks.length} brani caricati`, "ok");
    renderTable();
  }

  function renderTable() {
    const table = $("#traxsource-table");
    const tbody = table.querySelector("tbody");
    tbody.innerHTML = "";

    let displayTracks = currentTracks;
    let displayExisting = existing;
    let origIndexes = currentTracks.map((_, i) => i);
    if (sortCol) {
      const s = _sortPairs(currentTracks, existing, sortCol, sortDir);
      displayTracks = s.tracks;
      displayExisting = s.existing;
      origIndexes = s.origIndexes;
    }

    displayTracks.forEach((t, i) => {
      const origIdx = origIndexes[i];
      const alreadyDl = displayExisting[i];
      const tr = document.createElement("tr");
      if (alreadyDl) tr.classList.add("already-downloaded");

      const tdCheck = document.createElement("td");
      tdCheck.className = "col-check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.idx = String(origIdx);
      cb.checked = !alreadyDl;
      cb.addEventListener("change", updateSelectionCount);
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);

      const tdCover = document.createElement("td");
      tdCover.className = "col-cover";
      if (t.image_url) {
        const img = document.createElement("img");
        img.src = t.image_url;
        img.alt = "";
        img.loading = "lazy";
        img.referrerPolicy = "no-referrer";
        img.onerror = () => { img.style.visibility = "hidden"; };
        tdCover.appendChild(img);
      }
      tr.appendChild(tdCover);

      const tdPos = document.createElement("td");
      tdPos.className = "col-pos";
      tdPos.textContent = String(t.position || (origIdx + 1));
      tr.appendChild(tdPos);

      const tdArtist = document.createElement("td");
      tdArtist.textContent = t.artists || "";
      tr.appendChild(tdArtist);

      const tdTitle = document.createElement("td");
      tdTitle.textContent = t.mix ? `${t.title} (${t.mix})` : (t.title || "");
      tr.appendChild(tdTitle);

      const tdLabel = document.createElement("td");
      tdLabel.textContent = t.label || "";
      tr.appendChild(tdLabel);

      const tdState = document.createElement("td");
      tdState.className = "col-state";
      if (alreadyDl) tdState.textContent = "✓ già scaricato";
      tr.appendChild(tdState);

      tbody.appendChild(tr);
    });

    _updateSortArrows("#traxsource-table", sortCol, sortDir);
    table.hidden = false;
    $("#traxsource-toolbar").hidden = false;
    updateOutputInfo();
    updateSelectionCount();
  }

  function handleSort(col) {
    if (sortCol === col) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortCol = col;
      sortDir = "asc";
    }
    renderTable();
  }

  function updateSelectionCount() {
    const boxes = $$("#traxsource-table tbody input[type=checkbox]");
    const total = boxes.length;
    const checked = boxes.filter((b) => b.checked).length;
    $("#traxsource-selected-count").textContent = `${checked}/${total} selezionati`;
    const dlBtn = $("#traxsource-download-btn");
    if (dlBtn) dlBtn.disabled = downloading || checked === 0;

    const master = $("#traxsource-select-all");
    if (master) {
      if (total === 0) { master.checked = false; master.indeterminate = false; }
      else if (checked === 0) { master.checked = false; master.indeterminate = false; }
      else if (checked === total) { master.checked = true; master.indeterminate = false; }
      else { master.checked = false; master.indeterminate = true; }
    }
  }

  function toggleAll(checked) {
    $$("#traxsource-table tbody input[type=checkbox]").forEach((b) => { b.checked = checked; });
    updateSelectionCount();
  }

  function appendTraxsourceLog(msg) {
    const el = $("#traxsource-log");
    if (!el) return;
    const cls = classifyLog(msg);
    const line = document.createElement("div");
    if (cls) line.className = cls;
    line.textContent = msg;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  async function startDownload() {
    const boxes = $$("#traxsource-table tbody input[type=checkbox]");
    const selected = [];
    boxes.forEach((b) => {
      if (b.checked) {
        const idx = parseInt(b.dataset.idx, 10);
        if (!isNaN(idx) && currentTracks[idx]) selected.push(currentTracks[idx]);
      }
    });
    if (!selected.length) {
      toast("Seleziona almeno un brano", "error");
      return;
    }
    if (!state.config || !state.config.output_dir) {
      toast("Imposta la cartella output in Impostazioni", "error");
      return;
    }

    downloading = true;
    $("#traxsource-download-btn").disabled = true;
    $("#traxsource-stop-btn").hidden = false;
    $("#traxsource-stop-btn").disabled = false;
    $("#traxsource-log").innerHTML = "";
    appendTraxsourceLog(`[INFO] Avvio download di ${selected.length} brani da ${currentGenreName}…`);

    let res;
    try {
      res = await window.pywebview.api.traxsource_download_selected(selected, currentGenreName);
    } catch (e) {
      appendTraxsourceLog("[ERRORE] " + ((e && e.message) || e));
      finishDownload();
      return;
    }
    if (!res || !res.ok) {
      const errMsg = (res && (res.error || res.message)) || "Impossibile avviare il download";
      appendTraxsourceLog("[ERRORE] " + errMsg);
      if (!handleGateBlock(res || {})) toast(errMsg, "error");
      finishDownload();
    }
  }

  async function stopDownload() {
    try {
      await window.pywebview.api.stop_download();
    } catch (e) { console.error(e); }
  }

  function finishDownload() {
    downloading = false;
    $("#traxsource-stop-btn").hidden = true;
    $("#traxsource-stop-btn").disabled = true;
    updateSelectionCount();
    if (currentTracks.length) {
      window.pywebview.api.traxsource_check_existing(currentTracks, currentGenreName)
        .then((res) => { existing = res || existing; renderTable(); })
        .catch(() => {});
    }
  }

  async function init() {
    try {
      genres = await window.pywebview.api.traxsource_genres();
    } catch (e) {
      console.error("Traxsource: impossibile caricare i generi", e);
      genres = [];
    }
    populateSelect();

    const last = (state.config && state.config.traxsource_last_genre) || "";
    const sel = $("#traxsource-genre");
    if (sel && last && genres.some((g) => g.slug === last)) {
      sel.value = last;
    }
    updateOutputInfo();

    $("#traxsource-load-btn").addEventListener("click", (e) => loadChart(e.shiftKey));
    $("#traxsource-download-btn").addEventListener("click", startDownload);
    $("#traxsource-stop-btn").addEventListener("click", stopDownload);
    $("#traxsource-select-all").addEventListener("change", (e) => toggleAll(e.target.checked));
    _bindSortableHeaders("#traxsource-table", handleSort);

    // Wrapping additivo sui bridgeHandlers (canale "download" condiviso)
    const origProgress = bridgeHandlers["download:progress"];
    bridgeHandlers["download:progress"] = (p) => {
      if (origProgress) origProgress(p);
    };
    const origDone = bridgeHandlers["download:done"];
    bridgeHandlers["download:done"] = (p) => {
      if (origDone) origDone(p);
      if (downloading) finishDownload();
    };
    const origLog = bridgeHandlers["log"];
    bridgeHandlers["log"] = ({ view, msg }) => {
      if (origLog) origLog({ view, msg });
      if (downloading && view === "download") appendTraxsourceLog(msg);
    };
  }

  return { init };
})();

// =====================================================================
// Converti (WAV -> MP3)
// =====================================================================
const ConvertUI = (() => {
  const mstate = { files: [], selected: new Set(), running: false, outputDir: "" };

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function renderTable() {
    const tbody = $("#convert-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    mstate.files.forEach((f, i) => {
      const tr = document.createElement("tr");
      tr.dataset.idx = String(i);
      const checked = mstate.selected.has(i) ? "checked" : "";
      const baseName = f.split(/[\/\\]/).pop();
      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" data-idx="${i}" ${checked} /></td>
        <td class="col-pos">${i + 1}</td>
        <td title="${_escape(f)}">${_escape(baseName)}</td>
        <td class="col-state" data-idx="${i}"></td>
      `;
      tr.querySelector("input[type=checkbox]").addEventListener("change", (e) => {
        if (e.target.checked) mstate.selected.add(i);
        else mstate.selected.delete(i);
        updateSelectionCount();
      });
      tbody.appendChild(tr);
    });
    $("#convert-table-wrap").hidden = mstate.files.length === 0;
    updateSelectionCount();
  }

  function updateSelectionCount() {
    const total = mstate.files.length;
    const sel = mstate.selected.size;
    $("#convert-selected-count").textContent = `${sel}/${total} selezionati`;
    $("#convert-run-btn").disabled = mstate.running || sel === 0;
    const sa = $("#convert-select-all");
    if (sa) {
      sa.indeterminate = sel > 0 && sel < total;
      sa.checked = sel === total && total > 0;
    }
  }

  function appendFiles(newFiles) {
    // Dedup + append
    const existing = new Set(mstate.files);
    for (const f of newFiles) {
      if (!existing.has(f)) {
        mstate.files.push(f);
        mstate.selected.add(mstate.files.length - 1);
        existing.add(f);
      }
    }
    renderTable();
  }

  function setStatus(text, kind) {
    const el = $("#convert-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "beatport-status" + (kind ? " " + kind : "");
  }

  async function pickFiles() {
    const files = await window.pywebview.api.convert_pick_wav_files();
    if (Array.isArray(files) && files.length) {
      appendFiles(files);
      setStatus("", "");
    } else {
      setStatus("Nessun file .wav selezionato", "");
    }
  }

  async function pickFolder() {
    setStatus("Scansione cartella...", "loading");
    const files = await window.pywebview.api.convert_pick_wav_folder(true);
    if (Array.isArray(files) && files.length) {
      appendFiles(files);
      setStatus(`Trovati ${files.length} file .wav`, "ok");
    } else {
      setStatus("Nessun file .wav trovato nella cartella", "");
    }
  }

  function clearFiles() {
    mstate.files = [];
    mstate.selected.clear();
    renderTable();
    setStatus("", "");
    $("#convert-log").innerHTML = "";
  }

  async function browseOutput() {
    const p = await window.pywebview.api.browse_directory();
    if (p && typeof p === "string") {
      mstate.outputDir = p;
      $("#convert-out-path").textContent = p;
      $("#convert-out-custom").checked = true;
    }
  }

  function appendConvertLog(msg) {
    const el = $("#convert-log");
    if (!el) return;
    const cls = classifyLog(msg);
    const line = document.createElement("div");
    if (cls) line.className = cls;
    line.textContent = msg;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  function updateStateCell(idx, text, cls) {
    const td = document.querySelector(`#convert-tbody td.col-state[data-idx="${idx}"]`);
    if (!td) return;
    td.textContent = text;
    td.style.color = cls === "err" ? "var(--red)" : (cls === "ok" ? "var(--green-text)" : "");
  }

  async function startConversion() {
    const files = [...mstate.selected].sort((a, b) => a - b).map((i) => mstate.files[i]);
    if (!files.length) return;
    const bitrate = parseInt($("#convert-bitrate").value, 10);
    const vbr = $("#convert-vbr").checked;
    const useCustom = $("#convert-out-custom").checked;
    const output_dir = useCustom ? (mstate.outputDir || "") : "";
    if (useCustom && !output_dir) {
      setStatus("Scegli una cartella di destinazione", "error");
      return;
    }

    mstate.running = true;
    $("#convert-run-btn").disabled = true;
    $("#convert-stop-btn").hidden = false;
    $("#convert-log").innerHTML = "";
    // Reset state cells
    $$("#convert-tbody td.col-state").forEach((td) => {
      td.textContent = "";
      td.style.color = "";
    });

    let res;
    try {
      res = await window.pywebview.api.convert_start({ files, bitrate, vbr, output_dir });
    } catch (e) {
      appendConvertLog("[ERRORE] " + ((e && e.message) || e));
      finishConversion();
      return;
    }
    if (!res || !res.ok) {
      const errMsg = (res && res.error) || "Impossibile avviare";
      appendConvertLog("[ERRORE] " + errMsg);
      if (!handleGateBlock(res || {})) toast(errMsg, "error");
      finishConversion();
    }
  }

  async function stopConversion() {
    try { await window.pywebview.api.convert_stop(); } catch (e) { console.error(e); }
  }

  function finishConversion() {
    mstate.running = false;
    $("#convert-run-btn").disabled = mstate.selected.size === 0;
    $("#convert-stop-btn").hidden = true;
  }

  async function init() {
    // Bind eventi
    $("#convert-pick-files").addEventListener("click", pickFiles);
    $("#convert-pick-folder").addEventListener("click", pickFolder);
    $("#convert-clear").addEventListener("click", clearFiles);
    $("#convert-out-browse").addEventListener("click", browseOutput);
    $("#convert-out-custom").addEventListener("change", () => {
      $("#convert-out-browse").disabled = false;
    });
    $("#convert-out-same").addEventListener("change", () => {
      $("#convert-out-browse").disabled = true;
    });
    $("#convert-select-all").addEventListener("change", (e) => {
      mstate.selected.clear();
      if (e.target.checked) {
        for (let i = 0; i < mstate.files.length; i++) mstate.selected.add(i);
      }
      renderTable();
    });
    $("#convert-run-btn").addEventListener("click", startConversion);
    $("#convert-stop-btn").addEventListener("click", stopConversion);

    // Bridge handlers per il canale "convert"
    const origProgress = bridgeHandlers["convert:progress"];
    bridgeHandlers["convert:progress"] = (p) => {
      if (origProgress) origProgress(p);
      if (!p) return;
      if (p.status === "done") updateStateCell(p.idx, "✓ fatto", "ok");
      else if (p.status === "skipped") updateStateCell(p.idx, "già esiste", "");
      else if (p.status === "stopped") updateStateCell(p.idx, "interrotto", "");
      else if (typeof p.status === "string" && p.status.startsWith("error")) updateStateCell(p.idx, "✗ errore", "err");
      else if (p.status === "converting") updateStateCell(p.idx, `${p.pct || 0}%`, "");
    };
    const origDone = bridgeHandlers["convert:done"];
    bridgeHandlers["convert:done"] = (p) => {
      if (origDone) origDone(p);
      if (mstate.running) {
        appendConvertLog("[INFO] Conversione terminata.");
        finishConversion();
      }
    };
    // Il canale "log" e' gia gestito da logEls.convert (aggiunto sopra), quindi
    // non serve wrap qui: appendLog(view=convert, msg) targeta #convert-log.
  }

  return { init };
})();

// ============================================================
// DedupUI — audio duplicati via Chromaprint fingerprinting
// ============================================================
const DedupUI = (() => {
  const mstate = {
    folder: "",
    recursive: true,
    scanning: false,
    groups: [],
    // Set di path da cancellare (chiave = string path)
    toDelete: new Set(),
  };

  function _fmtDur(sec) {
    if (!sec || sec <= 0) return "—";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function setStatus(text, kind) {
    const el = $("#dedup-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "beatport-status" + (kind ? " " + kind : "");
  }

  function updateSelectedCount() {
    const n = mstate.toDelete.size;
    const label = n === 1 ? "1 file da cancellare" : `${n} file da cancellare`;
    const cnt = $("#dedup-selected-count");
    if (cnt) cnt.textContent = label;
    const btn = $("#dedup-trash-btn");
    if (btn) btn.disabled = n === 0 || mstate.scanning;
    const bar = $("#dedup-footer-bar");
    if (bar) bar.hidden = mstate.groups.length === 0;
  }

  function renderGroups() {
    const wrap = $("#dedup-groups-wrap");
    if (!wrap) return;
    wrap.innerHTML = "";
    mstate.toDelete.clear();

    if (!mstate.groups.length) {
      $("#dedup-summary-card").hidden = true;
      $("#dedup-footer-bar").hidden = true;
      updateSelectedCount();
      return;
    }

    // Summary line
    const nGroups = mstate.groups.length;
    let nDupes = 0;
    let reclaim = 0;
    mstate.groups.forEach((g) => {
      nDupes += Math.max(0, g.length - 1);
      for (let i = 1; i < g.length; i++) reclaim += (g[i].size || 0);
    });
    $("#dedup-summary-line").textContent =
      `${nGroups} gruppi · ${nDupes} duplicati · spazio recuperabile ~${_fmtBytes(reclaim)}`;
    $("#dedup-summary-card").hidden = false;

    // Render each group card
    mstate.groups.forEach((group, gi) => {
      const card = document.createElement("div");
      card.className = "card dedup-group-card";

      const totalSize = group.reduce((s, e) => s + (e.size || 0), 0);
      const fpPreview = (group[0].fingerprint || "").slice(0, 12);
      const header = document.createElement("div");
      header.className = "dedup-group-header";
      header.innerHTML = `
        <strong>Gruppo ${gi + 1}</strong>
        · <span>${group.length} file</span>
        · <span>totale ${_fmtBytes(totalSize)}</span>
        · <span class="dedup-fp">fp ${_escapeHtml(fpPreview)}…</span>
      `;
      card.appendChild(header);

      const list = document.createElement("div");
      list.className = "dedup-file-list";

      group.forEach((entry, idx) => {
        const isKeep = idx === 0;  // primo = bitrate piu' alto = da tenere
        const row = document.createElement("div");
        row.className = "dedup-file-row" + (isKeep ? " dedup-keep" : "");

        // Pre-selezione: cancella tutti tranne il primo
        if (!isKeep) mstate.toDelete.add(entry.path);

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "dedup-file-check";
        checkbox.checked = !isKeep;
        checkbox.disabled = isKeep;
        checkbox.title = isKeep
          ? "File da tenere (bitrate massimo)"
          : "Marca per la cancellazione";
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) mstate.toDelete.add(entry.path);
          else mstate.toDelete.delete(entry.path);
          updateSelectedCount();
        });
        row.appendChild(checkbox);

        const info = document.createElement("div");
        info.className = "dedup-file-info";
        const kbps = entry.bitrate ? `${entry.bitrate}k` : "—";
        const keepBadge = isKeep ? '<span class="dedup-keep-badge">TIENI</span> ' : "";
        info.innerHTML = `
          <div class="dedup-file-title">${keepBadge}${_escapeHtml(_basename(entry.path))}</div>
          <div class="dedup-file-meta">
            ${_escapeHtml(kbps)} · ${_escapeHtml(_fmtBytes(entry.size))} · ${_escapeHtml(_fmtDur(entry.duration))}
          </div>
          <div class="dedup-file-path">${_escapeHtml(entry.path)}</div>
        `;
        row.appendChild(info);

        // Preview audio (riusa _makePreviewBtn della sezione Upgrade)
        const playSlot = document.createElement("div");
        playSlot.className = "dedup-file-play";
        playSlot.appendChild(_makePreviewBtn(entry.path));
        row.appendChild(playSlot);

        list.appendChild(row);
      });

      card.appendChild(list);
      wrap.appendChild(card);
    });

    updateSelectedCount();
  }

  async function pickFolder() {
    const p = await window.pywebview.api.dedup_pick_folder();
    if (p && typeof p === "string") {
      mstate.folder = p;
      $("#dedup-path-display").textContent = p;
      $("#dedup-start-btn").disabled = false;
      setStatus("", "");
    }
  }

  async function startScan() {
    if (!mstate.folder) return;
    mstate.recursive = $("#dedup-recursive").checked;
    mstate.scanning = true;
    mstate.groups = [];
    if (mstate._groupIndex) mstate._groupIndex.clear();
    mstate.toDelete.clear();
    renderGroups();
    $("#dedup-start-btn").disabled = true;
    $("#dedup-pick-folder").disabled = true;
    $("#dedup-stop-btn").hidden = false;
    $("#dedup-log").innerHTML = "";
    $("#dedupProgressFill").style.width = "0%";
    $("#dedupPercent").textContent = "0%";
    $("#dedupCounter").textContent = "Scansione in corso…";
    setStatus("Scansione in corso...", "loading");

    const method = $("#dedup-method")?.value || "fingerprint";
    let res;
    try {
      res = await window.pywebview.api.dedup_start_scan({
        directory: mstate.folder,
        recursive: mstate.recursive,
        method,
      });
    } catch (e) {
      setStatus("Errore avvio: " + ((e && e.message) || e), "error");
      finishScan();
      return;
    }
    if (!res || !res.ok) {
      const msg = (res && res.error) || "Impossibile avviare la scansione";
      setStatus(msg, "error");
      if (!handleGateBlock(res || {})) toast(msg, "error");
      finishScan();
    }
  }

  async function stopScan() {
    try { await window.pywebview.api.dedup_stop_scan(); } catch (e) { console.error(e); }
  }

  function finishScan() {
    mstate.scanning = false;
    $("#dedup-start-btn").disabled = !mstate.folder;
    $("#dedup-pick-folder").disabled = false;
    $("#dedup-stop-btn").hidden = true;
    updateSelectedCount();
  }

  async function moveSelectedToTrash() {
    const paths = [...mstate.toDelete];
    if (!paths.length) return;
    const msg = paths.length === 1
      ? "Spostare 1 file nel cestino?"
      : `Spostare ${paths.length} file nel cestino?`;
    if (!confirm(msg)) return;

    const btn = $("#dedup-trash-btn");
    btn.disabled = true;
    let res;
    try {
      res = await window.pywebview.api.dedup_move_to_trash(paths);
    } catch (e) {
      toast("Errore: " + ((e && e.message) || e), "error");
      btn.disabled = false;
      return;
    }
    if (!res || !res.ok) {
      toast((res && res.error) || "Errore spostamento", "error");
      btn.disabled = false;
      return;
    }

    const moved = new Set(res.moved || []);
    // Rimuovi dai gruppi i file spostati; scarta gruppi che scendono sotto i 2
    mstate.groups = mstate.groups
      .map((g) => g.filter((e) => !moved.has(e.path)))
      .filter((g) => g.length >= 2);
    renderGroups();

    const okN = res.moved_count || 0;
    const failN = res.failed_count || 0;
    if (failN > 0) {
      toast(`${okN} spostati, ${failN} falliti`, "error");
    } else {
      toast(`${okN} file spostati nel cestino`, "success");
    }
  }

  async function init() {
    // Bind eventi
    $("#dedup-pick-folder").addEventListener("click", pickFolder);
    $("#dedup-start-btn").addEventListener("click", startScan);
    $("#dedup-stop-btn").addEventListener("click", stopScan);
    $("#dedup-trash-btn").addEventListener("click", moveSelectedToTrash);
    $("#dedup-select-suggested-btn").addEventListener("click", () => {
      // Reset selezione: per ogni gruppo, marca-per-cancellazione TUTTI
      // tranne il primo (il "TIENI" consigliato). Non tocca i primi.
      mstate.toDelete.clear();
      mstate.groups.forEach((group) => {
        for (let i = 1; i < group.length; i++) {
          if (group[i] && group[i].path) mstate.toDelete.add(group[i].path);
        }
      });
      // Sync checkbox nel DOM
      $$("#dedup-groups-wrap .dedup-file-check").forEach((cb) => {
        if (cb.disabled) return;  // skip il "TIENI"
        cb.checked = true;
      });
      updateSelectedCount();
    });
    $("#dedup-recursive").addEventListener("change", (e) => {
      mstate.recursive = e.target.checked;
    });

    // Ripristina ultima cartella + recursive da config
    const cfg = state.config || {};
    if (cfg.dedup_last_folder) {
      mstate.folder = cfg.dedup_last_folder;
      $("#dedup-path-display").textContent = cfg.dedup_last_folder;
      $("#dedup-start-btn").disabled = false;
    }
    if (typeof cfg.dedup_recursive === "boolean") {
      $("#dedup-recursive").checked = cfg.dedup_recursive;
      mstate.recursive = cfg.dedup_recursive;
    }
    if (cfg.dedup_method && $("#dedup-method")) {
      $("#dedup-method").value = cfg.dedup_method;
    }

    // Bridge handlers
    bridgeHandlers["dedup:progress"] = (p) => {
      if (!p) return;
      if (typeof p.overall === "number") {
        const pct = Math.round(p.overall * 100);
        $("#dedupProgressFill").style.width = pct + "%";
        $("#dedupPercent").textContent = pct + "%";
      }
      if (typeof p.idx === "number" && typeof p.total === "number" && p.total > 0) {
        const status = p.status || "";
        let label;
        if (status === "cached") label = `File ${p.idx}/${p.total} · cache`;
        else if (status === "computing") label = `File ${p.idx}/${p.total} · calcolo`;
        else if (status === "completed") label = `Completato: ${p.total} file`;
        else if (status === "stopped") label = "Interrotta";
        else if (status === "error") label = `File ${p.idx}/${p.total} · errore`;
        else label = `File ${p.idx}/${p.total}`;
        $("#dedupCounter").textContent = label;
      }
    };

    // Streaming: gruppi arrivano uno alla volta man mano che si formano.
    // mstate.groups è una lista di ARRAY di entries (shape richiesta da
    // renderGroups). Manteniamo un indice group_id → arrayRef per poter
    // aggiornare in-place quando il gruppo cresce.
    if (!mstate._groupIndex) mstate._groupIndex = new Map();
    bridgeHandlers["dedup:group"] = (p) => {
      if (!p || !p.id || !Array.isArray(p.entries)) return;
      const idx = mstate._groupIndex;
      const existing = idx.get(p.id);
      if (existing) {
        // Aggiorna elementi in-place (stesso riferimento array in mstate.groups)
        existing.length = 0;
        for (const e of p.entries) existing.push(e);
      } else {
        // Nuovo gruppo: array copia + tag `_id` non-enumerabile per il lookup
        const arr = p.entries.slice();
        Object.defineProperty(arr, "_id", { value: p.id, enumerable: false });
        idx.set(p.id, arr);
        mstate.groups.push(arr);
      }
      renderGroups();
      setStatus(`Trovati ${mstate.groups.length} gruppi finora…`, "loading");
    };

    bridgeHandlers["dedup:done"] = (p) => {
      // Se sono arrivati group via streaming, ignoriamo p.groups (già in mstate).
      // Fallback: se lo streaming non ha popolato nulla, usiamo p.groups.
      if (mstate.groups.length === 0 && p && Array.isArray(p.groups)) {
        mstate.groups = p.groups;
      }
      renderGroups();
      if (p && p.ok === false) {
        setStatus(p.error || "Errore scansione", "error");
      } else if (!mstate.groups.length) {
        setStatus("Nessun duplicato trovato", "ok");
      } else {
        setStatus(`Trovati ${mstate.groups.length} gruppi di duplicati`, "ok");
      }
      finishScan();
    };
  }

  return { init };
})();

// ============================================================
// Boot
// ============================================================
init().catch((e) => {
  console.error(e);
  toast("Errore di inizializzazione: " + e.message, "error");
});
