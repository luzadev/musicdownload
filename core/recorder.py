"""Registrazione audio da un dispositivo di input via ffmpeg.

macOS: usa AVFoundation (ingresso fisico + driver virtuali tipo BlackHole)
Windows: usa DirectShow
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from core.paths import find_ffmpeg


_IS_MAC = sys.platform == "darwin"
_IS_WIN = sys.platform == "win32"


# ============================================================
# Stato globale (un solo recording alla volta)
# ============================================================
_current_proc: Optional[subprocess.Popen] = None
_proc_lock = threading.Lock()
_stop_event = threading.Event()
_recording_thread: Optional[threading.Thread] = None


def is_recording() -> bool:
    with _proc_lock:
        return _current_proc is not None and _current_proc.poll() is None


# ============================================================
# Lista dispositivi
# ============================================================
def list_input_devices() -> list[dict]:
    """Ritorna la lista dei dispositivi audio di input.
    Ogni voce: {"id": "0", "name": "...", "is_virtual": bool}.

    is_virtual = True per driver di loopback noti (BlackHole, Soundflower,
    Loopback, Audio Hijack, VB-Cable, ...)
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []

    if _IS_MAC:
        return _list_macos(ffmpeg)
    if _IS_WIN:
        return _list_windows(ffmpeg)
    return []


_VIRTUAL_KEYWORDS = (
    "blackhole", "soundflower", "loopback", "audio hijack",
    "vb-cable", "vb-audio", "stereo mix", "what u hear",
    "obs", "system audio",
)


def _is_virtual(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _VIRTUAL_KEYWORDS)


def _list_macos(ffmpeg: str) -> list[dict]:
    """Parsa l'output di `ffmpeg -f avfoundation -list_devices true -i ""`.
    L'output va su stderr."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "avfoundation",
             "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []

    devices: list[dict] = []
    in_audio = False
    audio_section_re = re.compile(r"AVFoundation\s+audio\s+devices", re.IGNORECASE)
    other_section_re = re.compile(r"AVFoundation\s+(?:video)\s+devices", re.IGNORECASE)
    line_re = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")

    for raw in proc.stderr.splitlines():
        line = raw.strip()
        if audio_section_re.search(line):
            in_audio = True
            continue
        if other_section_re.search(line):
            in_audio = False
            continue
        if not in_audio:
            continue
        clean = re.sub(r"^\[AVFoundation[^\]]*\]\s*", "", line)
        m = line_re.match(clean)
        if not m:
            continue
        idx, name = m.group(1), m.group(2).strip()
        devices.append({"id": idx, "name": name, "is_virtual": _is_virtual(name)})

    return devices


def _list_windows(ffmpeg: str) -> list[dict]:
    """Parsa l'output di `ffmpeg -f dshow -list_devices true -i dummy`."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "dshow",
             "-list_devices", "true", "-i", "dummy"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []

    devices: list[dict] = []
    in_audio = False
    line_re = re.compile(r'"([^"]+)"\s*\((audio|video)\)', re.IGNORECASE)
    name_re = re.compile(r'"([^"]+)"')

    for raw in proc.stderr.splitlines():
        line = raw.strip()
        low = line.lower()
        if "directshow audio devices" in low:
            in_audio = True
            continue
        if "directshow video devices" in low:
            in_audio = False
            continue

        m = line_re.search(line)
        if m:
            name, kind = m.group(1), m.group(2).lower()
            if kind == "audio":
                devices.append({"id": name, "name": name, "is_virtual": _is_virtual(name)})
            continue

        if in_audio:
            mn = name_re.search(line)
            if mn:
                name = mn.group(1)
                devices.append({"id": name, "name": name, "is_virtual": _is_virtual(name)})

    # Dedup preservando l'ordine
    seen = set()
    out = []
    for d in devices:
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        out.append(d)
    return out


# ============================================================
# Registrazione
# ============================================================
def _build_record_cmd(ffmpeg: str, device_id: str, output_path: str,
                      bitrate: str) -> list[str]:
    """Comando ffmpeg per registrare su file MP3."""
    if _IS_MAC:
        return [
            ffmpeg, "-hide_banner", "-y",
            "-f", "avfoundation",
            "-i", f":{device_id}",
            "-acodec", "libmp3lame",
            "-b:a", bitrate,
            "-vn",
            output_path,
        ]
    if _IS_WIN:
        return [
            ffmpeg, "-hide_banner", "-y",
            "-f", "dshow",
            "-i", f"audio={device_id}",
            "-acodec", "libmp3lame",
            "-b:a", bitrate,
            "-vn",
            output_path,
        ]
    raise RuntimeError("Sistema operativo non supportato per la registrazione")


def start_recording(
    device_id: str,
    output_path: str,
    bitrate: str = "320k",
    progress_callback: Optional[Callable] = None,
) -> dict:
    """Avvia una registrazione in un thread.
    Ritorna {ok, error?, output_path?}.

    progress_callback(status, payload) viene chiamato con:
      ("started",  {"output_path": ...})
      ("tick",     {"seconds": int})
      ("stopped",  {"output_path": ..., "seconds": int})
      ("error",    {"error": "..."})
    """
    global _current_proc, _recording_thread

    if is_recording():
        return {"ok": False, "error": "Una registrazione e gia in corso"}

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg non trovato"}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = _build_record_cmd(ffmpeg, device_id, str(out), bitrate)

    _stop_event.clear()

    def _worker():
        global _current_proc
        try:
            with _proc_lock:
                _current_proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,  # bytes su stdin per "q"
                )

            if progress_callback:
                progress_callback("started", {"output_path": str(out)})

            start = time.monotonic()
            # Pubblica un tick al secondo
            while True:
                if _stop_event.is_set():
                    break
                rc = _current_proc.poll()
                if rc is not None:
                    break
                elapsed = int(time.monotonic() - start)
                if progress_callback:
                    progress_callback("tick", {"seconds": elapsed})
                time.sleep(1.0)

            # Stop gracefully
            if _current_proc.poll() is None:
                try:
                    _current_proc.stdin.write(b"q\n")
                    _current_proc.stdin.flush()
                except Exception:
                    pass
                try:
                    _current_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _current_proc.terminate()
                    try:
                        _current_proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        _current_proc.kill()

            rc = _current_proc.returncode
            seconds = int(time.monotonic() - start)

            with _proc_lock:
                _current_proc = None

            if progress_callback:
                if rc == 0 or out.exists():
                    progress_callback("stopped", {"output_path": str(out), "seconds": seconds})
                else:
                    err = ""
                    try:
                        err = (_get_last_stderr() or "").strip().splitlines()[-1]
                    except Exception:
                        pass
                    progress_callback("error", {"error": err or f"ffmpeg exit {rc}"})
        except Exception as e:
            with _proc_lock:
                _current_proc = None
            if progress_callback:
                progress_callback("error", {"error": str(e)})

    _recording_thread = threading.Thread(target=_worker, daemon=True)
    _recording_thread.start()

    return {"ok": True, "output_path": str(out)}


def _get_last_stderr() -> str:
    """Tenta di leggere lo stderr residuo del processo corrente."""
    with _proc_lock:
        proc = _current_proc
    if proc is None or proc.stderr is None:
        return ""
    try:
        data = proc.stderr.read() or b""
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def stop_recording() -> dict:
    """Ferma la registrazione corrente (se attiva)."""
    _stop_event.set()
    return {"ok": True}
