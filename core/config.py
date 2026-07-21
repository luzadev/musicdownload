"""Gestione configurazione persistente (JSON)."""

import json
import os
import sys
from pathlib import Path

VERSION = "v1.8.6"


APP_NAME = "MusicTools"
_LEGACY_NAME = "MusicDownload"

# Endpoint dell'API di licenza/aggiornamenti. Cambialo qui per puntare
# a un ambiente di staging.
LICENSE_API_URL = "https://musictools.djluza.com"

# Quanti giorni puo' restare l'app offline prima di richiedere una
# nuova validazione contro il server.
LICENSE_GRACE_DAYS = 14

# Ogni quanti giorni l'app rivalida la licenza in background quando online.
LICENSE_REVALIDATE_DAYS = 7


def _get_config_dir() -> Path:
    """Ritorna la directory per config.json.

    Frozen (bundle PyInstaller):
    - macOS:   ~/Library/Application Support/MusicTools/
    - Windows: %APPDATA%/MusicTools/
    Dev (non frozen):
    - directory del progetto

    Se la cartella nuova non esiste ma quella legacy 'MusicDownload' si',
    viene migrata (copia di config.json) cosi' l'utente non perde le
    impostazioni dopo il rename.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            base = Path.home() / "Library" / "Application Support"
        config_dir = base / APP_NAME
        legacy_dir = base / _LEGACY_NAME
        # Migrazione one-shot: se non esiste la nuova ma esiste la vecchia
        if not config_dir.exists() and legacy_dir.exists():
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
                legacy_cfg = legacy_dir / "config.json"
                if legacy_cfg.exists():
                    (config_dir / "config.json").write_bytes(legacy_cfg.read_bytes())
            except OSError:
                pass
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
    # ---- Beatport ----
    "beatport_last_genre": "melodic-house-techno",  # ultimo genere Top 100 caricato
    # ---- Music Search (Spotify + YouTube) ----
    "spotify_search_last_query": "",
    "spotify_search_artist_mode": False,
    "youtube_search_last_query": "",
    # ---- Licenza ----
    "license_key": "",          # chiave fornita all'utente via email
    "license_email": "",        # email associata all'acquisto
    "license_token": "",        # JWT firmato dal server (claims offline)
    "license_activated_at": 0,  # epoch della prima attivazione
    "last_validated_at": 0,     # epoch dell'ultima revalidate online riuscita
    "device_id": "",            # UUID generato al primo avvio
    # ---- Piano (snapshot dei claims JWT) ----
    "plan_code": "",            # "basic" | "pro" | "premium" | "annual"
    "plan_name": "",            # nome user-facing
    "plan_features": [],        # ["audio", "video", "record", "metadata", "upgrade"]
    "plan_daily_limit": None,   # None = unlimited (annual), altrimenti int
    "plan_is_subscription": False,
    "plan_expires_at": 0,       # solo per annual one-time
    "plan_period_end": 0,       # solo per subscription mensili
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
