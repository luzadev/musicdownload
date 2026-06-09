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

from core.paths import find_ffmpeg, subprocess_flags


_IS_MAC = sys.platform == "darwin"
_IS_WIN = sys.platform == "win32"


# ============================================================
# Stato globale (un solo recording alla volta)
# ============================================================
_current_proc: Optional[subprocess.Popen] = None
_proc_lock = threading.Lock()
_stop_event = threading.Event()
_recording_thread: Optional[threading.Thread] = None
_stderr_buf: list = []
_stderr_lock = threading.Lock()


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
    L'output va su stderr.

    IMPORTANTE: come 'id' usiamo il NOME del device (non l'index numerico).
    AVFoundation rinumera silenziosamente i device quando cambia il set di
    hardware collegato (es. iPhone in continuita', Multi-Output Device, ecc).
    Il nome e' invece stabile; ffmpeg AVFoundation accetta sia ':<index>'
    sia ':<name>' come specifica del device input.
    """
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "avfoundation",
             "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=10,
            **subprocess_flags(),
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
        devices.append({
            "id": name,           # nome stabile (vedi docstring)
            "index": idx,         # solo informativo per debug
            "name": name,
            "is_virtual": _is_virtual(name),
        })

    return devices


def _list_windows(ffmpeg: str) -> list[dict]:
    """Parsa l'output di `ffmpeg -f dshow -list_devices true -i dummy`."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "dshow",
             "-list_devices", "true", "-i", "dummy"],
            capture_output=True, text=True, timeout=10,
            **subprocess_flags(),
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
    with _stderr_lock:
        _stderr_buf.clear()

    def _drain_stderr(proc):
        """Drena lo stderr di ffmpeg in modo continuo per evitare blocchi
        del pipe e per salvare le ultime righe ai fini diagnostici."""
        try:
            for raw in iter(proc.stderr.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", errors="ignore").rstrip()
                with _stderr_lock:
                    _stderr_buf.append(line)
                    # Mantieni solo le ultime 50 righe per non sforare la RAM
                    if len(_stderr_buf) > 50:
                        del _stderr_buf[0]
        except Exception:
            pass

    def _worker():
        global _current_proc
        try:
            with _proc_lock:
                _current_proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=False,
                    **subprocess_flags(),
                )

            drain_t = threading.Thread(target=_drain_stderr,
                                       args=(_current_proc,), daemon=True)
            drain_t.start()

            # Aspetta brevemente che ffmpeg apra il device. Se fallisce nei
            # primi ~1.5s, segnala errore prima di emettere 'started'.
            start = time.monotonic()
            opened = False
            for _ in range(15):
                if _current_proc.poll() is not None:
                    break
                # ffmpeg stampa "Press [q] to stop" quando il device e' aperto
                with _stderr_lock:
                    if any("Press [q]" in l for l in _stderr_buf):
                        opened = True
                        break
                time.sleep(0.1)

            rc_early = _current_proc.poll()
            if not opened and rc_early is not None:
                # ffmpeg e' uscito prima di iniziare a registrare
                with _proc_lock:
                    _current_proc = None
                if progress_callback:
                    progress_callback("error", {"error": _extract_friendly_error(rc_early)})
                return

            if progress_callback:
                progress_callback("started", {"output_path": str(out)})

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
                    progress_callback("error", {"error": _extract_friendly_error(rc)})
        except Exception as e:
            with _proc_lock:
                _current_proc = None
            if progress_callback:
                progress_callback("error", {"error": str(e)})

    _recording_thread = threading.Thread(target=_worker, daemon=True)
    _recording_thread.start()

    return {"ok": True, "output_path": str(out)}


def _extract_friendly_error(rc: int) -> str:
    """Trasforma rc + stderr di ffmpeg in un messaggio leggibile.
    Riconosce i casi tipici: permessi microfono, device occupato,
    device non disponibile, clock drift di BlackHole, ecc.

    Fallback: se non riconosce il pattern, ritorna le ultime righe
    significative dello stderr cosi' l'utente puo' diagnosticare
    o aprire un ticket.
    """
    with _stderr_lock:
        lines = list(_stderr_buf)

    text = "\n".join(lines).lower()
    is_mac = sys.platform == "darwin"

    # ---- Errori specifici (priorita' alta) ----

    if "input/output error" in text or "errno 22" in text:
        return (
            "Dispositivo audio non pronto (BlackHole o scheda virtuale). "
            "Spesso si risolve cosi':\n"
            "  1) Smetti la registrazione e riprova fra 5 secondi\n"
            "  2) Se persiste, da Terminale: 'sudo killall coreaudiod'\n"
            "  3) Verifica che nessun'altra app stia gia' registrando il device"
        )

    if "device not configured" in text or "device not available" in text:
        return "Dispositivo non configurato. Premi 'Aggiorna' e riseleziona."

    if "permission" in text or "not authorized" in text or "not permitted" in text \
       or "tcc" in text or "denied" in text:
        return _permission_message()

    if "no such device" in text or "no such audio device" in text or "invalid device" in text:
        return "Dispositivo non trovato. Premi 'Aggiorna' e riseleziona dalla lista."

    # ---- Macro per rc=-6 (SIGABRT) su macOS ----
    # Su macOS rc=-6 e' quasi sempre il sintomo di un crash di ffmpeg
    # dovuto al permesso Microfono mancante. La parola 'abort' non
    # sempre compare nello stderr di ffmpeg recenti.
    if rc == -6 and is_mac:
        return _permission_message()

    # ---- Fallback: cerca le ultime righe significative ----
    for line in reversed(lines):
        l = line.strip()
        if not l:
            continue
        low = l.lower()
        # Riga AVFoundation/dshow specifica (es. "[avfoundation @ 0x...] Could not...")
        if l.startswith("[avfoundation") or l.startswith("[dshow") or "@ 0x" in l:
            return l
        if "error" in low or "fail" in low or "denied" in low or "cannot" in low:
            return l

    # Ultima spiaggia: rc + ultime 3 righe di stderr per debug
    tail = " | ".join(line for line in lines[-3:] if line.strip()) or "(nessuno)"
    return f"ffmpeg exit {rc}. Ultimo stderr: {tail}"


def _permission_message() -> str:
    """Messaggio standardizzato per il problema permesso Microfono macOS."""
    return (
        "Permesso Microfono mancante. Su macOS:\n"
        "  Impostazioni di Sistema -> Privacy e sicurezza -> Microfono\n"
        "  Abilita 'Terminal' (se lanci l'app da terminale) o 'MusicTools'\n"
        "  (se usi l'app installata). Poi riavvia l'app."
    )


def get_last_stderr(max_lines: int = 50) -> list[str]:
    """Espone le ultime righe di stderr ai fini diagnostici.
    Chiamato dal bridge per la UI 'Mostra log tecnici'."""
    with _stderr_lock:
        return list(_stderr_buf[-max_lines:])


def stop_recording() -> dict:
    """Ferma la registrazione corrente (se attiva)."""
    _stop_event.set()
    return {"ok": True}
