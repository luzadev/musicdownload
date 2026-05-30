/* ======================================================
   MusicDownload — Frontend (vanilla JS)
   ====================================================== */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  config: {},
  urlList: [],
  dlOutputDir: "",
  upDir: "",
  showSecret: false,
  downloading: false,
  upgrading: false,
};

// Wait for pywebview ready
function waitApi() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", resolve, { once: true });
  });
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
    state.urlList = [];
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
  },
};

// ============================================================
// Logging
// ============================================================
const logEls = { download: () => $("#dlLog"), upgrade: () => $("#upLog") };

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
  $("#footerVersion").textContent = data.version;
  $("#currentVersionLabel").textContent = data.version;
  $("#guideBody").textContent = data.spotify_guide;

  // Populate Settings fields
  $("#clientIdInput").value = state.config.client_id || "";
  $("#clientSecretInput").value = state.config.client_secret || "";
  $("#bitrateSelect").value = state.config.bitrate || "320K";
  $("#hqThresholdInput").value = state.config.hq_threshold || 310;
  $("#cookiesInput").value = state.config.cookies_path || "";
  $("#outputInput").value = state.config.output_dir || "";
  $("#themeSelect").value = state.config.theme || "dark";

  // Download tab — usa output_dir come default
  state.dlOutputDir = state.config.output_dir || "";
  if (state.dlOutputDir) {
    $("#dlPathDisplay").textContent = state.dlOutputDir;
    $("#dlPathDisplay").classList.remove("empty");
  }

  // Upgrade tab — default threshold
  $("#upThreshold").value = state.config.hq_threshold || 310;
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
    toast("Il file non contiene URL validi", "error");
    return;
  }
  state.urlList = res.urls;
  $("#urlInput").value = path;
  const badge = $("#urlListBadge");
  badge.textContent = `· ${res.count} URL caricati`;
  badge.hidden = false;
  appendLog("download", `[INFO] Caricati ${res.count} URL dal file`);
});

$("#downloadBtn").addEventListener("click", async () => {
  let urls = state.urlList;
  if (!urls.length) {
    const single = $("#urlInput").value.trim();
    if (!single) {
      toast("Inserisci un URL o carica una lista", "error");
      return;
    }
    urls = [single];
  }
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

  const res = await window.pywebview.api.start_download({
    urls,
    output_dir: state.dlOutputDir,
  });
  if (!res.ok) {
    toast(res.error || "Errore", "error");
    bridgeHandlers["download:done"]();
  }
});

$("#stopDownloadBtn").addEventListener("click", async () => {
  await window.pywebview.api.stop_download();
  $("#stopDownloadBtn").disabled = true;
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
  });
  if (!res.ok) {
    toast(res.error || "Errore", "error");
    bridgeHandlers["upgrade:done"]();
  }
});

$("#stopUpgradeBtn").addEventListener("click", async () => {
  await window.pywebview.api.stop_upgrade();
  $("#stopUpgradeBtn").disabled = true;
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

$("#saveBtn").addEventListener("click", async () => {
  const payload = {
    client_id: $("#clientIdInput").value,
    client_secret: $("#clientSecretInput").value,
    bitrate: $("#bitrateSelect").value,
    hq_threshold: parseInt($("#hqThresholdInput").value, 10) || 310,
    cookies_path: $("#cookiesInput").value,
    output_dir: $("#outputInput").value,
    theme: $("#themeSelect").value,
  };
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
// Boot
// ============================================================
init().catch((e) => {
  console.error(e);
  toast("Errore di inizializzazione: " + e.message, "error");
});
