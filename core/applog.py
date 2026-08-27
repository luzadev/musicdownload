"""Setup logging persistente su file rotante.

Chiamato in `main.py` prima di qualsiasi import pesante. Il file di log
vive in:
  - macOS:   ~/Library/Application Support/MusicTools/logs/app.log
  - Windows: %APPDATA%/MusicTools/logs/app.log
  - Dev:     <project_root>/logs/app.log

Rotazione: 1 file al giorno, mantiene gli ultimi 7. Cattura anche stdout
e stderr per non perdere `print()` o traceback che l'app windowed
altrimenti scarterebbe.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path


_setup_done = False


def _logs_dir() -> Path:
    """Directory dei log — parallela a config.json."""
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            base = Path.home() / "Library" / "Application Support"
        d = base / "MusicTools" / "logs"
    else:
        d = Path(__file__).resolve().parent.parent / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file_path() -> Path:
    return _logs_dir() / "app.log"


def _install_excepthook() -> None:
    """Cattura ogni uncaught exception dentro il file di log.
    NON tocca sys.stdout/stderr (romperebbe WebKit)."""
    import traceback
    logger = logging.getLogger("uncaught")
    _orig = sys.excepthook

    def _hook(exc_type, exc_value, tb):
        try:
            logger.error(
                "Uncaught: %s: %s\n%s",
                exc_type.__name__,
                exc_value,
                "".join(traceback.format_exception(exc_type, exc_value, tb)),
            )
        except Exception:
            pass
        try:
            _orig(exc_type, exc_value, tb)
        except Exception:
            pass

    sys.excepthook = _hook

    # Anche per exception in threading (Python 3.8+)
    try:
        _orig_thread = threading_excepthook = getattr(__import__("threading"), "excepthook", None)

        def _thread_hook(args):
            try:
                logger.error(
                    "Thread uncaught: %s: %s\n%s",
                    args.exc_type.__name__,
                    args.exc_value,
                    "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
                )
            except Exception:
                pass
            if _orig_thread:
                try:
                    _orig_thread(args)
                except Exception:
                    pass

        if threading_excepthook is not None:
            __import__("threading").excepthook = _thread_hook
    except Exception:
        pass


def setup() -> Path:
    """Configura il logger root — NON tocca stdout/stderr per non rompere
    WebKit (segfault). Cattura traceback via sys.excepthook + logger.
    """
    global _setup_done
    path = log_file_path()
    if _setup_done:
        return path
    _setup_done = True

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler con rotazione giornaliera (max 7 file = 7 giorni)
    fh = logging.handlers.TimedRotatingFileHandler(
        str(path),
        when="midnight",
        backupCount=7,
        encoding="utf-8",
        utc=False,
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)
    root.addHandler(fh)

    # Se in dev, mantieni anche console (utile durante lavoro)
    if not getattr(sys, "frozen", False):
        ch = logging.StreamHandler(sys.__stderr__)
        ch.setFormatter(fmt)
        ch.setLevel(logging.INFO)
        root.addHandler(ch)

    _install_excepthook()

    root.info(f"MusicTools log start — file: {path}")
    return path
