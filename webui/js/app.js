/* ======================================================
   MusicTools — Frontend (vanilla JS)
   ====================================================== */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  config: {},
  loaded: null,  // { kind: "urls"|"tracks", urls?, tracks?, count }
  dlOutputDir: "",
  upDir: "",
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
  },

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
      toast("Errore registrazione: " + (p.error || ""), "error");
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
        toast("Inserisci un URL o carica una lista", "error");
        bridgeHandlers["download:done"]();
        return;
      }
      urls = [single];
    }
    res = await window.pywebview.api.start_download({
      urls,
      output_dir: state.dlOutputDir,
    });
  }

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
    toast(res.error || "Errore", "error");
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
// RECORDER tab
// ============================================================
$("#recRefreshBtn").addEventListener("click", refreshRecDevices);

$("#recOpenGuide").addEventListener("click", (e) => {
  e.preventDefault();
  window.pywebview.api.open_external_url(
    "https://github.com/luzadev/musicdownload#guida-rapida-registrazione-audio-di-sistema-macos"
  );
});

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
    toast(res.error || "Errore", "error");
  }
});

$("#recStopBtn").addEventListener("click", async () => {
  $("#recStopBtn").disabled = true;
  await window.pywebview.api.stop_audio_recording();
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
    toast("Errore: " + (res.error || ""), "error");
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
