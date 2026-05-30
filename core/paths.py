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
        # macOS: Contents/Frameworks/ (PyInstaller onedir .app)
        if not _IS_WINDOWS:
            frameworks = exe_dir.parent / "Frameworks"
            if frameworks.exists():
                dirs.append(frameworks)
    return dirs


def _exe(name: str) -> str:
    """Aggiunge .exe su Windows."""
    if _IS_WINDOWS and not name.endswith(".exe"):
        return name + ".exe"
    return name


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


def find_ffmpeg_dir() -> Optional[str]:
    """Trova la directory contenente ffmpeg e ffprobe.

    Ordine di ricerca:
    1. Bundle PyInstaller
    2. Percorsi noti per OS
    3. Qualsiasi posizione nel PATH
    """
    ffmpeg_name = _exe("ffmpeg")

    # 1. Bundle
    for d in _bundle_dirs():
        if (d / ffmpeg_name).exists():
            return str(d)

    # 2. Percorsi noti
    if _IS_WINDOWS:
        # Posizioni comuni su Windows
        for search in (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ffmpeg" / "bin",
            Path("C:/ffmpeg/bin"),
            Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin",
        ):
            if (search / "ffmpeg.exe").exists():
                return str(search)
    else:
        for search_path in ("/opt/homebrew/bin", "/usr/local/bin"):
            if (Path(search_path) / "ffmpeg").exists():
                return search_path

    # 3. PATH generico
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return str(Path(ffmpeg).parent)

    return None


def find_ffmpeg() -> Optional[str]:
    """Ritorna il path completo di ffmpeg."""
    d = find_ffmpeg_dir()
    if d:
        return str(Path(d) / _exe("ffmpeg"))
    return None


def find_ffprobe() -> Optional[str]:
    """Ritorna il path completo di ffprobe."""
    d = find_ffmpeg_dir()
    if d:
        return str(Path(d) / _exe("ffprobe"))
    return None
