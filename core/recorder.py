"""Registrazione audio.

macOS: AVCaptureSession via PyObjC dentro al processo Python principale.
  Il bundle MusicTools.app ha NSMicrophoneUsageDescription e il TCC viene
  concesso al main, quindi AVFoundation registra senza problemi. ffmpeg
  viene usato SOLO per convertire il file CAF a MP3 (no microfono = no TCC).
Windows: ffmpeg DirectShow (qui il problema TCC non esiste).
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
_recording_lock = threading.Lock()
_recording_state: dict = {}
_stderr_buf: list = []
_stderr_lock = threading.Lock()


def is_recording() -> bool:
    with _recording_lock:
        return bool(_recording_state.get("active"))


def get_last_stderr(max_lines: int = 50) -> list[str]:
    """Espone le ultime righe di log diagnostico ai fini diagnostici.

    Su macOS contiene messaggi del backend AVCaptureSession + stderr di
    ffmpeg durante la conversione CAF->MP3. Su Windows contiene lo
    stderr di ffmpeg per la registrazione DirectShow.
    """
    with _stderr_lock:
        return list(_stderr_buf[-max_lines:])


def _log_diag(line: str) -> None:
    with _stderr_lock:
        _stderr_buf.append(line)
        if len(_stderr_buf) > 200:
            del _stderr_buf[0]


_VIRTUAL_KEYWORDS = (
    "blackhole", "soundflower", "loopback", "audio hijack",
    "vb-cable", "vb-audio", "stereo mix", "what u hear",
    "obs", "system audio",
)


def _is_virtual(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _VIRTUAL_KEYWORDS)


# ============================================================
# Lista dispositivi
# ============================================================
def list_input_devices() -> list[dict]:
    """Ritorna la lista dei dispositivi audio di input.

    Ogni voce: {"id": "...", "name": "...", "is_virtual": bool}.
    Su macOS l'`id` e' l'uniqueID di AVCaptureDevice (stabile).
    Su Windows e' il nome del device (richiesto da DirectShow).
    """
    if _IS_MAC:
        return _list_macos_avf()
    if _IS_WIN:
        ffmpeg = find_ffmpeg()
        return _list_windows(ffmpeg) if ffmpeg else []
    return []


def _list_macos_avf() -> list[dict]:
    """Enumera input audio via AVFoundation (no ffmpeg subprocess)."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except ImportError as e:
        _log_diag(f"[avf] AVFoundation non disponibile: {e}")
        return []

    devices: list[dict] = []
    for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeAudio):
        try:
            name = str(d.localizedName())
            uid = str(d.uniqueID())
        except Exception:
            continue
        devices.append({
            "id": uid,
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

    seen = set()
    out = []
    for d in devices:
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        out.append(d)
    return out


# ============================================================
# Permesso microfono (macOS)
# ============================================================
def _ensure_macos_mic_permission() -> tuple[bool, str]:
    """Verifica/richiede il permesso microfono (TCC) per il processo corrente.

    Ritorna (granted, reason).
    """
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except ImportError as e:
        return False, f"AVFoundation non disponibile: {e}"

    # 0=notDetermined, 1=restricted, 2=denied, 3=authorized
    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    if status == 3:
        return True, "authorized"
    if status in (1, 2):
        return False, (
            "Permesso microfono negato.\n"
            "Impostazioni di Sistema -> Privacy e sicurezza -> Microfono\n"
            "Attiva MusicTools e riavvia l'app."
        )
    # notDetermined -> chiedi il prompt in modo sincrono.
    ev = threading.Event()
    granted = [False]

    def cb(ok):
        granted[0] = bool(ok)
        ev.set()

    AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, cb)
    # PyObjC pumpa il run loop automaticamente in attesa del callback.
    ev.wait(60)
    if not granted[0]:
        return False, "Permesso microfono negato dall'utente."
    return True, "granted"


# ============================================================
# Registrazione macOS via AVCaptureSession
# ============================================================
def _start_recording_macos(device_id: str, output_path: str, bitrate: str,
                            progress_callback: Optional[Callable]) -> dict:
    from AVFoundation import (
        AVCaptureSession, AVCaptureDevice, AVCaptureDeviceInput,
        AVCaptureAudioFileOutput, AVMediaTypeAudio,
    )
    from Foundation import NSURL, NSObject

    ok, reason = _ensure_macos_mic_permission()
    if not ok:
        return {"ok": False, "error": reason}

    # Trova il device: prima per uniqueID, poi per nome (fallback)
    dev = AVCaptureDevice.deviceWithUniqueID_(device_id)
    if dev is None:
        for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeAudio):
            if str(d.localizedName()) == device_id:
                dev = d
                break
    if dev is None:
        return {"ok": False, "error": "Dispositivo audio non trovato."}

    session = AVCaptureSession.alloc().init()
    inp, err = AVCaptureDeviceInput.deviceInputWithDevice_error_(dev, None)
    if err is not None:
        return {"ok": False, "error": f"Errore input: {err.localizedDescription()}"}
    if not session.canAddInput_(inp):
        return {"ok": False, "error": "Impossibile aggiungere il device alla session."}
    session.addInput_(inp)

    out = AVCaptureAudioFileOutput.alloc().init()
    if not session.canAddOutput_(out):
        return {"ok": False, "error": "Impossibile aggiungere l'output alla session."}
    session.addOutput_(out)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    caf_path = out_path.with_suffix(".caf")

    # Delegate: aspetta che lo stop produca il file finale
    class _Delegate(NSObject):
        def captureOutput_didStartRecordingToOutputFileAtURL_fromConnections_(
                self, output, url, conns):
            self.started = True

        def captureOutput_didFinishRecordingToOutputFileAtURL_fromConnections_error_(
                self, output, url, conns, err):
            self.done = True
            self.err = err.localizedDescription() if err is not None else None

    delegate = _Delegate.alloc().init()
    delegate.started = False
    delegate.done = False
    delegate.err = None

    session.startRunning()
    out.startRecordingToOutputFileURL_outputFileType_recordingDelegate_(
        NSURL.fileURLWithPath_(str(caf_path)),
        "com.apple.coreaudio-format",
        delegate,
    )

    with _recording_lock:
        _recording_state.update({
            "active": True,
            "session": session,
            "output": out,
            "delegate": delegate,
            "caf_path": str(caf_path),
            "mp3_path": str(out_path),
            "bitrate": bitrate,
            "started_at": time.monotonic(),
            "progress_cb": progress_callback,
        })

    if progress_callback:
        progress_callback("started", {"output_path": str(out_path)})

    # Tick thread per emettere "seconds" elapsed (la UI lo mostra)
    threading.Thread(target=_tick_worker, daemon=True).start()

    _log_diag(f"[avf] Recording started -> {caf_path}")
    return {"ok": True, "output_path": str(out_path)}


def _tick_worker():
    while is_recording():
        with _recording_lock:
            cb = _recording_state.get("progress_cb")
            started_at = _recording_state.get("started_at", time.monotonic())
        elapsed = int(time.monotonic() - started_at)
        if cb:
            cb("tick", {"seconds": elapsed})
        time.sleep(1.0)


def _stop_recording_macos() -> dict:
    with _recording_lock:
        if not _recording_state.get("active"):
            return {"ok": True}
        state = dict(_recording_state)
        _recording_state["active"] = False

    session = state["session"]
    out = state["output"]
    delegate = state["delegate"]
    caf_path = Path(state["caf_path"])
    mp3_path = Path(state["mp3_path"])
    bitrate = state["bitrate"]
    cb = state["progress_cb"]
    started_at = state["started_at"]

    # Stop recording (chiama il delegate didFinish dopo aver finalizzato il file)
    out.stopRecording()
    # Aspetta il completamento del file
    deadline = time.time() + 8
    while not getattr(delegate, "done", False) and time.time() < deadline:
        time.sleep(0.1)
    session.stopRunning()

    if getattr(delegate, "err", None):
        _log_diag(f"[avf] delegate error: {delegate.err}")

    seconds = int(time.monotonic() - started_at)

    # Conversione CAF -> MP3 via ffmpeg (NO microfono: niente TCC)
    if caf_path.exists():
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            try:
                proc = subprocess.run(
                    [ffmpeg, "-hide_banner", "-y", "-i", str(caf_path),
                     "-acodec", "libmp3lame", "-b:a", bitrate,
                     "-vn", str(mp3_path)],
                    capture_output=True, text=True, timeout=120,
                    **subprocess_flags(),
                )
                if proc.returncode != 0:
                    _log_diag(f"[ffmpeg-convert] rc={proc.returncode}")
                    for ln in (proc.stderr or "").splitlines()[-10:]:
                        _log_diag(ln)
                # Cleanup CAF temporaneo
                try:
                    caf_path.unlink()
                except OSError:
                    pass
            except Exception as e:
                _log_diag(f"[ffmpeg-convert] exception: {e}")
        else:
            _log_diag("[ffmpeg-convert] ffmpeg non trovato, lascio il file CAF.")
            # Se ffmpeg non c'e', rinomina il CAF in MP3 (estensione errata
            # ma l'utente ha qualcosa)
            try:
                caf_path.rename(mp3_path.with_suffix(".caf"))
            except OSError:
                pass

    if cb:
        if mp3_path.exists():
            cb("stopped", {"output_path": str(mp3_path), "seconds": seconds})
        else:
            cb("error", {"error": "File registrato non trovato dopo lo stop."})

    return {"ok": True}


# ============================================================
# Registrazione Windows via ffmpeg DirectShow (invariato)
# ============================================================
def _start_recording_windows(device_id: str, output_path: str, bitrate: str,
                              progress_callback: Optional[Callable]) -> dict:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg non trovato"}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-hide_banner", "-y",
        "-f", "dshow",
        "-i", f"audio={device_id}",
        "-acodec", "libmp3lame",
        "-b:a", bitrate,
        "-vn",
        str(out),
    ]

    with _stderr_lock:
        _stderr_buf.clear()

    def _drain(proc):
        try:
            for raw in iter(proc.stderr.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", errors="ignore").rstrip()
                _log_diag(line)
        except Exception:
            pass

    def _worker():
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=False,
                **subprocess_flags(),
            )
            with _recording_lock:
                _recording_state.update({
                    "active": True,
                    "proc": proc,
                    "output_path": str(out),
                    "started_at": time.monotonic(),
                    "progress_cb": progress_callback,
                })
            threading.Thread(target=_drain, args=(proc,), daemon=True).start()

            start = time.monotonic()
            opened = False
            for _ in range(15):
                if proc.poll() is not None:
                    break
                with _stderr_lock:
                    if any("Press [q]" in l for l in _stderr_buf):
                        opened = True
                        break
                time.sleep(0.1)

            if not opened and proc.poll() is not None:
                with _recording_lock:
                    _recording_state["active"] = False
                if progress_callback:
                    progress_callback("error", {
                        "error": _extract_friendly_error_windows(proc.returncode),
                    })
                return

            if progress_callback:
                progress_callback("started", {"output_path": str(out)})

            while True:
                with _recording_lock:
                    if not _recording_state.get("active"):
                        break
                rc = proc.poll()
                if rc is not None:
                    break
                elapsed = int(time.monotonic() - start)
                if progress_callback:
                    progress_callback("tick", {"seconds": elapsed})
                time.sleep(1.0)

            if proc.poll() is None:
                try:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()

            seconds = int(time.monotonic() - start)
            with _recording_lock:
                _recording_state["active"] = False

            if progress_callback:
                if proc.returncode == 0 or out.exists():
                    progress_callback("stopped", {"output_path": str(out), "seconds": seconds})
                else:
                    progress_callback("error", {
                        "error": _extract_friendly_error_windows(proc.returncode),
                    })
        except Exception as e:
            with _recording_lock:
                _recording_state["active"] = False
            if progress_callback:
                progress_callback("error", {"error": f"{type(e).__name__}: {e}"})

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "output_path": str(out)}


def _extract_friendly_error_windows(rc: int) -> str:
    with _stderr_lock:
        lines = list(_stderr_buf)
    text = "\n".join(lines).lower()
    if "no such device" in text or "could not find" in text:
        return "Dispositivo non trovato. Premi 'Aggiorna' e riseleziona."
    if "permission" in text or "denied" in text:
        return "Permesso microfono mancante. Impostazioni Windows -> Privacy -> Microfono."
    for line in reversed(lines):
        l = line.strip()
        if not l:
            continue
        low = l.lower()
        if "error" in low or "fail" in low or "denied" in low:
            return l
    tail = " | ".join(line for line in lines[-3:] if line.strip()) or "(nessuno)"
    return f"ffmpeg exit {rc}. Ultimo stderr: {tail}"


def _stop_recording_windows() -> dict:
    with _recording_lock:
        if not _recording_state.get("active"):
            return {"ok": True}
        # Il worker thread vede 'active'=False e termina ffmpeg con 'q'.
        _recording_state["active"] = False
    return {"ok": True}


# ============================================================
# API pubblica
# ============================================================
def start_recording(
    device_id: str,
    output_path: str,
    bitrate: str = "320k",
    progress_callback: Optional[Callable] = None,
) -> dict:
    if is_recording():
        return {"ok": False, "error": "Una registrazione e gia in corso"}

    with _stderr_lock:
        _stderr_buf.clear()

    if _IS_MAC:
        return _start_recording_macos(device_id, output_path, bitrate, progress_callback)
    if _IS_WIN:
        return _start_recording_windows(device_id, output_path, bitrate, progress_callback)
    return {"ok": False, "error": "Sistema operativo non supportato per la registrazione"}


def stop_recording() -> dict:
    if _IS_MAC:
        return _stop_recording_macos()
    if _IS_WIN:
        return _stop_recording_windows()
    return {"ok": True}
