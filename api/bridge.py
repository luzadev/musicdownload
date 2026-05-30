"""Ponte JS <-> Python: tutti i metodi che la UI invoca via pywebview.api."""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from typing import Any, Optional

from core.config import load_config, save_config, VERSION
from core.downloader import (
    download_playlist,
    download_direct_url,
    download_video,
    request_stop as request_download_stop,
    reset_stop as reset_download_stop,
    is_stopped as download_is_stopped,
)
from core.spotify_client import get_access_token, resolve_spotify_url
from core.upgrader import (
    upgrade_folder,
    request_stop as request_upgrade_stop,
    count_files_info,
)


SPOTIFY_GUIDE_TEXT = """\
1) Vai su https://developer.spotify.com/dashboard e accedi (anche con account free).
2) Clicca "Create app".
3) Compila:
   - App name: MusicDownload (o quello che vuoi)
   - Description: a piacere
   - Redirect URI: http://localhost:8888/callback (obbligatorio ma non usato)
   - Seleziona "Web API"
   - Accetta i termini, "Save"
4) Apri la app appena creata > "Settings" e copia:
   - Client ID
   - Client Secret (clicca "View client secret")
5) Incollali qui sotto e premi "Salva".

Note: credenziali gratuite, no Premium. Limite 100 richieste/minuto.
"""


def _js_safe(value: Any) -> str:
    """Serializza un valore per inserirlo in evaluate_js."""
    return json.dumps(value, ensure_ascii=False)


class Api:
    """Espone i metodi a JavaScript tramite pywebview js_api."""

    def __init__(self):
        self.window = None  # impostato dopo create_window
        self._download_thread: Optional[threading.Thread] = None
        self._upgrade_thread: Optional[threading.Thread] = None
        self._video_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit(self, channel: str, payload: dict | str | None = None) -> None:
        """Invia un evento al frontend."""
        if not self.window:
            return
        try:
            self.window.evaluate_js(
                f"window.bridge && window.bridge.emit({_js_safe(channel)}, {_js_safe(payload)});"
            )
        except Exception:
            pass

    def _log(self, view: str, msg: str) -> None:
        self._emit("log", {"view": view, "msg": msg})

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    def get_init_data(self) -> dict:
        """Chiamato dal frontend all'avvio per popolare lo stato iniziale."""
        cfg = load_config()
        return {
            "version": VERSION,
            "config": cfg,
            "spotify_guide": SPOTIFY_GUIDE_TEXT,
        }

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def save_settings(self, payload: dict) -> dict:
        try:
            threshold = int(payload.get("hq_threshold", 310))
        except (TypeError, ValueError):
            threshold = 310

        config = {
            "client_id": (payload.get("client_id") or "").strip(),
            "client_secret": (payload.get("client_secret") or "").strip(),
            "bitrate": payload.get("bitrate", "320K"),
            "hq_threshold": threshold,
            "cookies_path": (payload.get("cookies_path") or "").strip(),
            "output_dir": (payload.get("output_dir") or "").strip(),
            "theme": payload.get("theme", "dark"),
        }
        save_config(config)
        return {"ok": True}

    def check_update(self) -> dict:
        """Controlla aggiornamenti chiamando version.json remoto."""
        import urllib.request

        UPDATE_URL = "https://www.djluza.com/musicdownload/version.json"
        try:
            req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "MusicDownload"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            remote = data.get("version", "")
            return {
                "ok": True,
                "current": VERSION,
                "remote": remote,
                "is_new": bool(remote and remote != VERSION),
                "download_url": data.get("download_url", ""),
                "notes": data.get("notes", ""),
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "current": VERSION}

    # ------------------------------------------------------------------
    # File dialogs (delegati a pywebview)
    # ------------------------------------------------------------------
    def _folder_dialog_type(self):
        import webview
        # API nuova (>= 5.x): webview.FileDialog.FOLDER
        # API vecchia: webview.FOLDER_DIALOG
        if hasattr(webview, "FileDialog"):
            return webview.FileDialog.FOLDER
        return webview.FOLDER_DIALOG

    def _open_dialog_type(self):
        import webview
        if hasattr(webview, "FileDialog"):
            return webview.FileDialog.OPEN
        return webview.OPEN_DIALOG

    def browse_directory(self) -> str:
        if not self.window:
            return ""
        result = self.window.create_file_dialog(self._folder_dialog_type())
        if result:
            return result[0] if isinstance(result, (list, tuple)) else result
        return ""

    def browse_file(self, filetypes: Optional[list] = None) -> str:
        if not self.window:
            return ""
        if filetypes:
            ft = tuple(filetypes)
        else:
            ft = ("Text files (*.txt)", "All files (*.*)")
        result = self.window.create_file_dialog(self._open_dialog_type(), file_types=ft)
        if result:
            return result[0] if isinstance(result, (list, tuple)) else result
        return ""

    def load_url_list(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
            return {"ok": True, "urls": urls, "count": len(urls)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_external_url(self, url: str) -> None:
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # Audio folder scan (Upgrade tab)
    # ------------------------------------------------------------------
    def scan_audio_folder(self, directory: str, recursive: bool) -> dict:
        try:
            total, done = count_files_info(directory, bool(recursive))
            return {"ok": True, "total": total, "done": done, "remaining": total - done}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # DOWNLOAD
    # ------------------------------------------------------------------
    def _any_job_running(self) -> bool:
        return (
            (self._download_thread and self._download_thread.is_alive()) or
            (self._video_thread and self._video_thread.is_alive())
        )

    def start_download(self, payload: dict) -> dict:
        if self._any_job_running():
            return {"ok": False, "error": "Un download gia in corso"}

        urls = payload.get("urls") or []
        output_dir = (payload.get("output_dir") or "").strip()
        if not urls:
            return {"ok": False, "error": "Nessun URL fornito"}
        if not output_dir:
            return {"ok": False, "error": "Cartella output non impostata"}

        self._download_thread = threading.Thread(
            target=self._download_worker,
            args=(list(urls), output_dir),
            daemon=True,
        )
        self._download_thread.start()
        return {"ok": True}

    def stop_download(self) -> dict:
        request_download_stop()
        self._log("download", "[INFO] Interruzione richiesta...")
        return {"ok": True}

    def _download_worker(self, urls: list, output_dir: str) -> None:
        reset_download_stop()
        cfg = load_config()
        bitrate = cfg.get("bitrate", "320K")
        cookies_path = cfg.get("cookies_path", "")
        total_urls = len(urls)
        multi = total_urls > 1
        view = "download"

        token = None
        has_spotify = any("spotify.com" in u for u in urls)
        if has_spotify:
            client_id = cfg.get("client_id", "")
            client_secret = cfg.get("client_secret", "")
            if not client_id or not client_secret:
                self._log(view, "[ERRORE] Configura Client ID e Client Secret nelle Impostazioni.")
                self._emit("download:done", {"ok": False})
                return
            self._log(view, "[INFO] Autenticazione Spotify...")
            try:
                token = get_access_token(client_id, client_secret)
            except Exception as e:
                self._log(view, f"[ERRORE] Autenticazione fallita: {e}")
                self._emit("download:done", {"ok": False})
                return

        for url_idx, url in enumerate(urls):
            if download_is_stopped():
                self._log(view, "[INFO] Download interrotto.")
                break

            if multi:
                self._log(view, f"\n{'='*50}")
                self._log(view, f"[LISTA] URL {url_idx + 1} di {total_urls}")
                self._log(view, f"{'='*50}")

            is_spotify = "spotify.com" in url

            _last = [0.0]
            _THROTTLE = 0.10
            url_base = url_idx / total_urls if multi else 0
            url_weight = 1 / total_urls if multi else 1

            def progress_cb(idx, total, track_name, status, pct,
                            _base=url_base, _weight=url_weight, _uidx=url_idx):
                if status == "downloading":
                    now = time.monotonic()
                    if now - _last[0] < _THROTTLE:
                        return
                    _last[0] = now

                payload_evt = {
                    "idx": idx, "total": total, "track": track_name,
                    "status": status, "pct": pct,
                    "url_idx": _uidx, "url_total": total_urls,
                }

                if status == "searching":
                    self._log(view, f"[CERCA] {track_name}")
                elif status == "skipped":
                    self._log(view, f"[SKIP] {track_name} (gia scaricato)")
                    track_progress = (idx + 1) / total if total > 0 else 1
                    payload_evt["overall"] = min(_base + track_progress * _weight, 1.0)
                elif status == "downloading":
                    track_progress = (idx / total) + (pct / 100 / total) if total > 0 else 0
                    payload_evt["overall"] = min(_base + track_progress * _weight, 1.0)
                elif status == "done":
                    self._log(view, f"[OK] {track_name}")
                    track_progress = (idx + 1) / total if total > 0 else 1
                    payload_evt["overall"] = min(_base + track_progress * _weight, 1.0)
                elif status == "stopped":
                    self._log(view, "[INFO] Download interrotto.")
                elif status == "completed":
                    if not multi:
                        payload_evt["overall"] = 1.0
                    self._log(view, "[INFO] Download completato!")
                elif status.startswith("error"):
                    self._log(view, f"[ERRORE] {track_name}: {status}")

                self._emit("download:progress", payload_evt)

            if is_spotify:
                self._log(view, "[INFO] Recupero informazioni da Spotify...")
                try:
                    label, name, tracks = resolve_spotify_url(token, url)
                except Exception as e:
                    self._log(view, f"[ERRORE] {e}")
                    continue
                self._log(view, f"[INFO] {label}: {name} ({len(tracks)} brani)")
                dest_dir = os.path.join(output_dir, name)
                download_playlist(tracks, dest_dir, bitrate, cookies_path, progress_cb)
            else:
                self._log(view, f"[INFO] Download diretto via yt-dlp: {url}")
                download_direct_url(url, output_dir, bitrate, cookies_path, progress_cb)

        if multi and not download_is_stopped():
            self._log(view, f"\n[INFO] Completate tutte le {total_urls} playlist/URL!")
            self._emit("download:progress", {
                "status": "completed", "overall": 1.0,
                "url_total": total_urls,
            })

        self._emit("download:done", {"ok": True})

    # ------------------------------------------------------------------
    # UPGRADE
    # ------------------------------------------------------------------
    def start_upgrade(self, payload: dict) -> dict:
        if self._upgrade_thread and self._upgrade_thread.is_alive():
            return {"ok": False, "error": "Upgrade gia in corso"}

        directory = (payload.get("directory") or "").strip()
        recursive = bool(payload.get("recursive", False))
        try:
            threshold = int(payload.get("threshold", 310))
        except (TypeError, ValueError):
            threshold = 310

        if not directory:
            return {"ok": False, "error": "Cartella non impostata"}

        cfg = load_config()
        cookies_path = cfg.get("cookies_path", "")

        self._upgrade_thread = threading.Thread(
            target=self._upgrade_worker,
            args=(directory, threshold, cookies_path, recursive),
            daemon=True,
        )
        self._upgrade_thread.start()
        return {"ok": True}

    def stop_upgrade(self) -> dict:
        request_upgrade_stop()
        self._log("upgrade", "[INFO] Interruzione richiesta...")
        return {"ok": True}

    def _upgrade_worker(self, directory, threshold, cookies_path, recursive):
        view = "upgrade"

        def progress_cb(idx, total, filename, status, old_kbps, new_kbps):
            payload_evt = {
                "idx": idx, "total": total, "filename": filename,
                "status": status, "old_kbps": old_kbps, "new_kbps": new_kbps,
            }
            if total > 0:
                payload_evt["overall"] = min(idx / total, 1.0)

            if status == "searching":
                self._log(view, f"[CERCA] {filename} ({old_kbps}kbps)")
            elif status == "not_found":
                self._log(view, f"[NON TROVATO] {filename}")
            elif status == "cover_only":
                self._log(view, f"[COPERTINA] {filename} (gia {old_kbps}kbps)")
            elif status == "cover_done":
                self._log(view, f"[OK COPERTINA] {filename}")
            elif status == "cover_failed":
                self._log(view, f"[SKIP] {filename} - copertina non disponibile ({old_kbps}kbps ok)")
            elif status == "downloading":
                self._log(view, f"[DOWNLOAD] {filename} ({old_kbps}kbps)")
            elif status == "upgraded":
                diff = new_kbps - old_kbps
                diff_str = f" (+{diff}kbps)" if diff > 0 else ""
                self._log(view, f"[UPGRADE] {filename}: {old_kbps} -> {new_kbps}kbps{diff_str}")
            elif status == "download_error":
                self._log(view, f"[ERRORE] {filename}: download fallito")
            elif status == "stopped":
                self._log(view, "[INFO] Upgrade interrotto.")
            elif status == "completed":
                payload_evt["overall"] = 1.0
                self._log(view, "[INFO] Upgrade completato!")

            self._emit("upgrade:progress", payload_evt)

        upgrade_folder(directory, threshold, cookies_path, recursive, progress_cb)
        self._emit("upgrade:done", {"ok": True})

    # ------------------------------------------------------------------
    # VIDEO (YouTube, TikTok, Instagram, Facebook)
    # ------------------------------------------------------------------
    def start_video_download(self, payload: dict) -> dict:
        if self._any_job_running():
            return {"ok": False, "error": "Un download gia in corso"}

        urls = payload.get("urls") or []
        output_dir = (payload.get("output_dir") or "").strip()
        quality = payload.get("quality") or "1080p"

        if not urls:
            return {"ok": False, "error": "Nessun URL fornito"}
        if not output_dir:
            return {"ok": False, "error": "Cartella output non impostata"}

        self._video_thread = threading.Thread(
            target=self._video_worker,
            args=(list(urls), output_dir, quality),
            daemon=True,
        )
        self._video_thread.start()
        return {"ok": True}

    def stop_video_download(self) -> dict:
        request_download_stop()
        self._log("video", "[INFO] Interruzione richiesta...")
        return {"ok": True}

    def _video_worker(self, urls: list, output_dir: str, quality: str) -> None:
        reset_download_stop()
        cfg = load_config()
        cookies_path = cfg.get("cookies_path", "")
        total_urls = len(urls)
        multi = total_urls > 1
        view = "video"

        for url_idx, url in enumerate(urls):
            if download_is_stopped():
                self._log(view, "[INFO] Download interrotto.")
                break

            if multi:
                self._log(view, f"\n{'='*50}")
                self._log(view, f"[LISTA] URL {url_idx + 1} di {total_urls}")
                self._log(view, f"{'='*50}")

            _last = [0.0]
            _THROTTLE = 0.10
            url_base = url_idx / total_urls if multi else 0
            url_weight = 1 / total_urls if multi else 1

            def progress_cb(idx, total, track_name, status, pct,
                            _base=url_base, _weight=url_weight, _uidx=url_idx):
                if status == "downloading":
                    now = time.monotonic()
                    if now - _last[0] < _THROTTLE:
                        return
                    _last[0] = now

                payload_evt = {
                    "idx": idx, "total": total, "track": track_name,
                    "status": status, "pct": pct,
                    "url_idx": _uidx, "url_total": total_urls,
                }

                if status == "skipped":
                    self._log(view, f"[SKIP] {track_name} (gia scaricato)")
                    track_progress = (idx + 1) / total if total > 0 else 1
                    payload_evt["overall"] = min(_base + track_progress * _weight, 1.0)
                elif status == "downloading":
                    track_progress = (idx / total) + (pct / 100 / total) if total > 0 else 0
                    payload_evt["overall"] = min(_base + track_progress * _weight, 1.0)
                elif status == "done":
                    self._log(view, f"[OK] {track_name}")
                    track_progress = (idx + 1) / total if total > 0 else 1
                    payload_evt["overall"] = min(_base + track_progress * _weight, 1.0)
                elif status == "stopped":
                    self._log(view, "[INFO] Download interrotto.")
                elif status == "completed":
                    if not multi:
                        payload_evt["overall"] = 1.0
                    self._log(view, "[INFO] Download completato!")
                elif status.startswith("error"):
                    self._log(view, f"[ERRORE] {track_name}: {status}")

                self._emit("video:progress", payload_evt)

            self._log(view, f"[INFO] Video: {url}")
            try:
                download_video(url, output_dir, quality, cookies_path, progress_cb)
            except Exception as e:
                self._log(view, f"[ERRORE] {e}")
                continue

        if multi and not download_is_stopped():
            self._log(view, f"\n[INFO] Completate tutte le {total_urls} URL!")
            self._emit("video:progress", {
                "status": "completed", "overall": 1.0,
                "url_total": total_urls,
            })

        self._emit("video:done", {"ok": True})
