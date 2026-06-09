"""Risoluzione path per binari esterni (yt-dlp, ffmpeg).

Quando l'app gira come bundle PyInstaller, i binari sono inclusi
nella cartella del bundle. Altrimenti cerca nel sistema.

Cross-platform: macOS e Windows.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

_IS_WINDOWS = sys.platform == "win32"


def _is_frozen() -> bool:
    """True se stiamo girando come bundle PyInstaller."""
    return getattr(sys, "frozen", False)


def _bundle_dirs() -> list[Path]:
    """Directories dove cercare i binari bundled (PyInstaller)."""
    dirs = []
    if _is_frozen():
        # _MEIPASS: directory dove PyInstaller estrae i file
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        if meipass.exists():
            dirs.append(meipass)
        # Directory dell'eseguibile
        exe_dir = Path(sys.executable).parent
        dirs.append(exe_dir)
        # macOS: Contents/Frameworks/ (PyInstaller onedir .app) + sub-bundle
        # ffmpeg.app / ffprobe.app dove sono incapsulati per TCC.
        if not _IS_WINDOWS:
            frameworks = exe_dir.parent / "Frameworks"
            if frameworks.exists():
                dirs.append(frameworks)
                # Mini-bundle .app per i subprocess (vedi build_macos.py
                # wrap_subprocess_in_bundle).
                for sub in ("ffmpeg.app", "ffprobe.app"):
                    sub_macos = frameworks / sub / "Contents" / "MacOS"
                    if sub_macos.exists():
                        dirs.append(sub_macos)
    return dirs


def _exe(name: str) -> str:
    """Aggiunge .exe su Windows."""
    if _IS_WINDOWS and not name.endswith(".exe"):
        return name + ".exe"
    return name


def subprocess_flags() -> dict:
    """Kwargs per subprocess.run/Popen che nascondono la console su Windows.

    Senza CREATE_NO_WINDOW, ogni subprocess (yt-dlp, ffmpeg, ffprobe) lanciato
    da un'app GUI PyInstaller apre una finestra cmd nera per la durata del
    processo. Su macOS/Linux il flag non esiste, quindi ritorniamo dict vuoto.
    """
    if _IS_WINDOWS:
        # 0x08000000 == CREATE_NO_WINDOW
        return {"creationflags": 0x08000000}
    return {}


def find_ytdlp() -> str:
    """Trova il path di yt-dlp.

    Ordine di ricerca:
    1. Bundle PyInstaller
    2. Homebrew (macOS) / PATH comune (Windows)
    3. Qualsiasi posizione nel PATH
    """
    name = _exe("yt-dlp")

    # 1. Bundle
    for d in _bundle_dirs():
        candidate = d / name
        if candidate.exists():
            return str(candidate)

    # 2. Percorsi noti per OS
    if not _IS_WINDOWS:
        brew = shutil.which("yt-dlp", path="/opt/homebrew/bin:/usr/local/bin")
        if brew:
            return brew

    # 3. PATH generico
    system = shutil.which("yt-dlp")
    if system:
        return system

    msg = "yt-dlp non trovato. "
    if _IS_WINDOWS:
        msg += "Scaricalo da https://github.com/yt-dlp/yt-dlp/releases"
    else:
        msg += "Installalo con: brew install yt-dlp"
    raise FileNotFoundError(msg)


def _find_binary(name: str) -> Optional[str]:
    """Trova un binario (ffmpeg o ffprobe) nelle dir del bundle o nel sistema."""
    exe_name = _exe(name)
    # 1. Bundle (incluso eventuali sub-bundle .app su macOS)
    for d in _bundle_dirs():
        candidate = d / exe_name
        if candidate.exists():
            return str(candidate)
    # 2. Percorsi noti per OS
    if _IS_WINDOWS:
        for search in (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ffmpeg" / "bin",
            Path("C:/ffmpeg/bin"),
            Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin",
        ):
            cand = search / exe_name
            if cand.exists():
                return str(cand)
    else:
        for search_path in ("/opt/homebrew/bin", "/usr/local/bin"):
            cand = Path(search_path) / exe_name
            if cand.exists():
                return str(cand)
    # 3. PATH generico
    found = shutil.which(name)
    return found if found else None


def find_ffmpeg_dir() -> Optional[str]:
    """Ritorna la directory contenente ffmpeg (utile per PATH env)."""
    ff = _find_binary("ffmpeg")
    return str(Path(ff).parent) if ff else None


def find_ffmpeg() -> Optional[str]:
    """Ritorna il path completo di ffmpeg."""
    return _find_binary("ffmpeg")


def find_ffprobe() -> Optional[str]:
    """Ritorna il path completo di ffprobe."""
    return _find_binary("ffprobe")
