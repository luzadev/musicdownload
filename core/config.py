"""Gestione configurazione persistente (JSON)."""

import json
import os
import sys
from pathlib import Path

VERSION = "v1.0"


def _get_config_dir() -> Path:
    """Ritorna la directory per config.json.

    Frozen (bundle PyInstaller):
    - macOS:   ~/Library/Application Support/MusicDownload/
    - Windows: %APPDATA%/MusicDownload/
    Dev (non frozen):
    - directory del progetto
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            base = Path.home() / "Library" / "Application Support"
        config_dir = base / "MusicDownload"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _get_config_dir() / "config.json"

# Default: i path relativi al progetto (se non frozen)
_project_dir = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "client_id": "",
    "client_secret": "",
    "bitrate": "320K",
    "hq_threshold": 310,
    "cookies_path": str(_project_dir / "cookies.txt"),
    "output_dir": str(_project_dir / "MUSICA"),
    "theme": "dark",
}


def load_config() -> dict:
    """Carica la configurazione da config.json, con fallback ai default."""
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            config.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: dict) -> None:
    """Salva la configurazione su config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
