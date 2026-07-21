"""Conversione WAV -> MP3 via ffmpeg subprocess."""

from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from core.paths import find_ffmpeg_dir, subprocess_flags


_stop_event = threading.Event()
_current_process: Optional[subprocess.Popen] = None
_process_lock = threading.Lock()


def request_stop() -> None:
    _stop_event.set()
    with _process_lock:
        if _current_process and _current_process.poll() is None:
            _current_process.terminate()


def reset_stop() -> None:
    _stop_event.clear()


def is_stopped() -> bool:
    return _stop_event.is_set()


# VBR quality mapping da bitrate label a -q:a (libmp3lame). Piu basso = migliore qualita.
# Vedi https://trac.ffmpeg.org/wiki/Encode/MP3
_VBR_QUALITY = {
    128: 5,
    192: 2,
    256: 0,
    320: 0,  # V0 e' ~245k medio; per >V0 c'e' solo CBR 320
}


def _find_ffmpeg() -> str:
    """Trova il binario ffmpeg dentro bundle_bin o PATH.

    Solleva RuntimeError se non trovato.
    """
    ffmpeg_dir = find_ffmpeg_dir()
    if ffmpeg_dir:
        for name in ("ffmpeg", "ffmpeg.exe"):
            p = Path(ffmpeg_dir) / name
            if p.exists():
                return str(p)
    # Fallback PATH
    import shutil
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    raise RuntimeError("ffmpeg non trovato nel bundle o nel PATH")


def convert_wav_to_mp3(
    input_path: str,
    output_path: str,
    bitrate: int = 320,
    vbr: bool = False,
    progress_callback: Optional[Callable] = None,
) -> None:
    """Converte un file WAV in MP3.

    Args:
        input_path: file .wav sorgente
        output_path: file .mp3 destinazione
        bitrate: 128 / 192 / 256 / 320
        vbr: True per Variable Bit Rate (-q:a), False per Constant (-b:a)
        progress_callback: opzionale, chiamato con (percent 0..100)

    Raises:
        RuntimeError: se ffmpeg non trovato o exit non-zero.
        FileNotFoundError: se input_path non esiste.
    """
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"File sorgente non trovato: {input_path}")

    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _find_ffmpeg()

    cmd = [ffmpeg, "-y", "-i", str(src)]
    if vbr:
        quality = _VBR_QUALITY.get(bitrate, 2)
        cmd.extend(["-c:a", "libmp3lame", "-q:a", str(quality)])
    else:
        cmd.extend(["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"])
    cmd.extend([
        "-map_metadata", "0",     # copia metadata WAV se presenti
        "-id3v2_version", "3",
        "-progress", "pipe:2",     # progress su stderr in formato key=value
        str(dst),
    ])

    # Prova a ottenere la durata totale per calcolare % — leggendo lo stream INFO
    duration_us = _probe_duration_us(ffmpeg, str(src))

    global _current_process
    with _process_lock:
        _current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            **subprocess_flags(),
        )
        proc = _current_process

    try:
        for line in proc.stderr:
            if is_stopped():
                proc.terminate()
                if progress_callback:
                    progress_callback(-1)  # segnale di interruzione
                return
            if not progress_callback or not duration_us:
                continue
            # ffmpeg -progress emette "out_time_us=<microsecondi>"
            m = re.match(r"out_time_us=(\d+)", line.strip())
            if m:
                elapsed = int(m.group(1))
                pct = min(100, int(elapsed * 100 / duration_us))
                progress_callback(pct)

        rc = proc.wait()

        if rc != 0:
            raise RuntimeError(f"ffmpeg exit {rc}")

        if progress_callback:
            progress_callback(100)
    finally:
        with _process_lock:
            _current_process = None


def _probe_duration_us(ffmpeg: str, input_path: str) -> int:
    """Estrae la durata in microsecondi via ffmpeg -f null. Ritorna 0 se non riesce."""
    try:
        # ffprobe potrebbe non essere sempre bundlato; usa ffmpeg
        result = subprocess.run(
            [ffmpeg, "-i", input_path, "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=10,
            **subprocess_flags(),
        )
        # Cerca "Duration: HH:MM:SS.ms"
        m = re.search(r"Duration:\s+(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if m:
            h, mi, s, ms = map(int, m.groups())
            total_sec = h * 3600 + mi * 60 + s + ms / 100
            return int(total_sec * 1_000_000)
    except Exception:
        pass
    return 0


def list_wav_files(directory: str, recursive: bool = True) -> list:
    """Scan cartella per file .wav. Ritorna list di path stringa ordinati."""
    root = Path(directory)
    if not root.is_dir():
        return []
    pattern = "**/*.wav" if recursive else "*.wav"
    return sorted(str(p) for p in root.glob(pattern) if p.is_file())
