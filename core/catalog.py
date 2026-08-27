"""Cataloga file audio in sottocartelle <Anno>/<Genere>/ via AcoustID.

Pipeline:
  1. Scansiona la cartella (opzionalmente ricorsivo) filtrando per
     estensioni audio (AUDIO_EXTENSIONS di core.upgrader).
  2. Per ogni file calcola il fingerprint Chromaprint (`fpcalc`,
     riusa `core.dedup.compute_fingerprint`).
  3. Lookup AcoustID (cache SQLite) per estrarre year + genre +
     artist + title.
  4. `move_files` sposta le entry selezionate in
     `<target>/<Year>/<Genre>/<filename>`. Se manca year/genre usa
     "Unknown Year" / "Unknown Genre".

Progress callback firma:
    (processed, total, filename, status[, err_msg])
Status: 'computing' | 'lookup' | 'error' | 'stopped' | 'completed'.

`entry_callback(entry)` viene chiamato per ogni file processato,
permettendo alla UI di aggiornare la tabella in streaming.
"""

from __future__ import annotations

import re
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

from core.acoustid import lookup
from core.dedup import compute_fingerprint
from core.paths import find_fpcalc
from core.upgrader import AUDIO_EXTENSIONS


# ------------------------------------------------------------------
# Stop / interrupt
# ------------------------------------------------------------------
_stop_event = threading.Event()


def request_stop() -> None:
    """Segnala al worker di interrompere la scansione al prossimo file."""
    _stop_event.set()


def reset_stop() -> None:
    """Azzera il flag di stop prima di iniziare una nuova scansione."""
    _stop_event.clear()


def is_stopped() -> bool:
    return _stop_event.is_set()


# ------------------------------------------------------------------
# Sanitize path
# ------------------------------------------------------------------
# Caratteri vietati o problematici in nomi cartella cross-platform.
# `/` e `\` sono trattati a parte perche' MusicBrainz usa spesso
# genre-name-style come "electronic/house": vogliamo rimpiazzarli con
# `_` (non con lo split, che creerebbe path nesting indesiderati).
_FORBIDDEN = re.compile(r'[<>:"|?*\\/]+')
_MULTI_SPACE = re.compile(r"\s+")


def _sanitize_folder(name: str) -> str:
    """Sanitize per path filesystem: rimpiazza chars non validi con `_`.

    - Chars vietati Windows (<>:"|?*) + slash → `_`
    - Spazi multipli collassati in uno solo
    - Trim finale
    - Troncamento a 100 char (limite pratico per path lunghi cumulati)
    """
    if not name:
        return ""
    s = _FORBIDDEN.sub("_", name).strip()
    s = _MULTI_SPACE.sub(" ", s)
    if len(s) > 100:
        s = s[:100].rstrip()
    return s


# ------------------------------------------------------------------
# Scan
# ------------------------------------------------------------------
def scan_folder(
    directory: str,
    recursive: bool = True,
    progress_callback: Optional[Callable] = None,
    entry_callback: Optional[Callable] = None,
) -> list:
    """Scansiona la cartella e ritorna la lista di entry con metadata.

    Ogni entry:
        {path, size, fingerprint, matched, year, genre, artist, title, error?}

    - `progress_callback(idx, total, filename, status[, err])`:
      chiamato con status 'computing' | 'lookup' | 'error' | 'stopped'
      | 'completed'. Firma retrocompatibile (4 args) supportata.
    - `entry_callback(entry)`: chiamato appena ogni file e' processato
      (streaming alla UI).
    """
    reset_stop()
    base = Path(directory)
    if not base.exists() or not base.is_dir():
        if progress_callback:
            _emit_progress(progress_callback, 0, 0, "", "completed", "")
        return []

    files: list = []
    iterator = base.rglob("*") if recursive else base.iterdir()
    for f in iterator:
        try:
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                files.append(f)
        except OSError:
            continue
    files.sort()

    total = len(files)
    if total == 0:
        if progress_callback:
            _emit_progress(progress_callback, 0, 0, "", "completed", "")
        return []

    fpcalc = find_fpcalc()

    entries: list = []
    for i, fp_path in enumerate(files, start=1):
        if is_stopped():
            _emit_progress(progress_callback, i - 1, total, "", "stopped", "")
            return entries

        try:
            size = fp_path.stat().st_size
        except OSError as e:
            _emit_progress(progress_callback, i, total, fp_path.name,
                           "error", f"stat: {e}")
            continue

        # Fingerprint
        _emit_progress(progress_callback, i, total, fp_path.name, "computing", "")
        res = compute_fingerprint(fpcalc, str(fp_path)) if fpcalc else None
        if not res or not res.get("fingerprint"):
            err = (res or {}).get("_error") or "fpcalc non disponibile"
            entry = {
                "path": str(fp_path), "size": size, "fingerprint": "",
                "matched": False, "error": err,
                "year": None, "genre": "", "artist": "", "title": "",
            }
            entries.append(entry)
            if entry_callback:
                try:
                    entry_callback(entry)
                except Exception:
                    pass
            _emit_progress(progress_callback, i, total, fp_path.name,
                           "error", err)
            continue

        fp_hash = res["fingerprint"]
        duration = float(res.get("duration") or 0)

        # AcoustID lookup (cache SQLite dentro core.acoustid)
        _emit_progress(progress_callback, i, total, fp_path.name, "lookup", "")
        info = lookup(fp_hash, duration)

        entry = {
            "path": str(fp_path),
            "size": size,
            "fingerprint": fp_hash,
            "matched": bool(info.get("matched")),
            "year": info.get("year"),
            "genre": (info.get("genre") or "").strip(),
            "artist": (info.get("artist") or "").strip(),
            "title": (info.get("title") or "").strip(),
        }
        if info.get("error"):
            entry["error"] = info["error"]

        entries.append(entry)
        if entry_callback:
            try:
                entry_callback(entry)
            except Exception:
                pass

    _emit_progress(progress_callback, total, total, "", "completed", "")
    return entries


def _emit_progress(cb: Optional[Callable], idx: int, total: int,
                    name: str, status: str, err: str = "") -> None:
    """Chiama progress_callback in modo retrocompatibile (4 o 5 args)."""
    if not cb:
        return
    try:
        cb(idx, total, name, status, err)
    except TypeError:
        try:
            cb(idx, total, name, status)
        except Exception:
            pass
    except Exception:
        pass


# ------------------------------------------------------------------
# Move
# ------------------------------------------------------------------
def move_files(entries: list, target_root: str,
                log_callback: Optional[Callable] = None) -> dict:
    """Sposta i file elencati in `<target_root>/<year>/<genre>/<filename>`.

    - Se `year` manca → cartella "Unknown Year"
    - Se `genre` manca → cartella "Unknown Genre"
    - Se il file destinazione esiste gia', aggiunge suffisso _1, _2...
      (non sovrascrive mai).

    Ritorna un dict:
        {
          "moved": int,               # numero file spostati con successo
          "skipped": int,             # entries scartate (0 per ora)
          "failed": [{path, error}],  # errori per file
          "operations": [{src, dst}], # log ops riuscite (utile per undo)
        }

    `log_callback(op)` viene chiamato per ogni operazione riuscita
    (streaming alla UI).
    """
    target_base = Path(target_root)
    try:
        target_base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"moved": 0, "skipped": 0,
                "failed": [{"path": target_root,
                            "error": f"impossibile creare target: {e}"}],
                "operations": []}

    result = {"moved": 0, "skipped": 0, "failed": [], "operations": []}

    for entry in entries or []:
        src_str = (entry or {}).get("path") or ""
        src = Path(src_str)
        if not src_str:
            result["failed"].append({"path": "",
                                     "error": "path mancante"})
            continue
        if not src.exists():
            result["failed"].append({"path": src_str,
                                     "error": "file non esiste"})
            continue

        year = entry.get("year")
        genre = (entry.get("genre") or "").strip()

        year_folder = str(year) if year else "Unknown Year"
        genre_folder = _sanitize_folder(genre) or "Unknown Genre"

        dst_dir = target_base / year_folder / genre_folder
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            result["failed"].append({"path": src_str,
                                     "error": f"mkdir: {e}"})
            continue

        dst = dst_dir / src.name

        # Anti-overwrite: se il target esiste, aggiungi _1, _2, ...
        if dst.exists():
            stem = dst.stem
            suffix = dst.suffix
            i = 1
            while dst.exists():
                dst = dst_dir / f"{stem}_{i}{suffix}"
                i += 1

        try:
            shutil.move(str(src), str(dst))
        except Exception as e:
            result["failed"].append({"path": src_str, "error": str(e)})
            continue

        result["moved"] += 1
        op = {"src": src_str, "dst": str(dst)}
        result["operations"].append(op)
        if log_callback:
            try:
                log_callback(op)
            except Exception:
                pass

    return result
