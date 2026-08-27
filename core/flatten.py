"""Appiattisce una cartella: sposta tutti i file audio delle sotto-cartelle
nella cartella padre. Utile come 'undo' di una catalogazione o per unire
archivi frammentati.

Non tocca i file gia' nella root della cartella padre.
Conflitti filename: aggiunge suffisso _1, _2... (mai overwrite).
Opzionalmente rimuove le sotto-cartelle rimaste vuote dopo il move.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

from core.upgrader import AUDIO_EXTENSIONS


_stop_event = threading.Event()


def request_stop() -> None:
    _stop_event.set()


def reset_stop() -> None:
    _stop_event.clear()


def is_stopped() -> bool:
    return _stop_event.is_set()


def _iter_audio_in_subfolders(parent: Path) -> list:
    """Enumera i file audio in TUTTE le sotto-cartelle (ricorsivo) escludendo
    quelli gia' nella root del `parent`."""
    if not parent.is_dir():
        return []
    files: list = []
    for f in parent.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if f.parent.resolve() == parent.resolve():
            continue  # gia' nella root
        files.append(f)
    files.sort()
    return files


def _unique_dst(dst: Path) -> Path:
    """Restituisce un path non-esistente aggiungendo `_1`, `_2`... se serve."""
    if not dst.exists():
        return dst
    stem = dst.stem
    suffix = dst.suffix
    i = 1
    while True:
        candidate = dst.parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _remove_empty_dirs(parent: Path) -> int:
    """Rimuove ricorsivamente tutte le sotto-cartelle vuote di `parent`.
    Non tocca `parent` stessa. Ritorna il numero di dir rimosse."""
    removed = 0
    for p in sorted(parent.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if not p.is_dir():
            continue
        if p.resolve() == parent.resolve():
            continue
        try:
            # rimuove .DS_Store residui che impediscono rmdir
            for junk in p.glob(".DS_Store"):
                try: junk.unlink()
                except Exception: pass
            p.rmdir()
            removed += 1
        except OSError:
            pass  # non vuota o senza permessi
    return removed


def flatten_folder(
    parent_dir: str,
    remove_empty: bool = True,
    progress_callback: Optional[Callable] = None,
    log_callback: Optional[Callable] = None,
) -> dict:
    """Sposta tutti i file audio delle sotto-cartelle in `parent_dir`.

    Args:
        parent_dir: cartella padre di destinazione
        remove_empty: se True, elimina le sotto-cartelle rimaste vuote
        progress_callback: (idx, total, filename, status[, err]) — status:
            'scanning' | 'moving' | 'skipped' | 'error' | 'stopped' | 'completed'
        log_callback: chiamato con {src, dst} per ogni move riuscito

    Ritorna:
        {moved, skipped, failed: [{path, error}], operations: [{src, dst}],
         dirs_removed}
    """
    reset_stop()
    parent = Path(parent_dir)
    result = {
        "moved": 0,
        "skipped": 0,
        "failed": [],
        "operations": [],
        "dirs_removed": 0,
    }

    if not parent.is_dir():
        return result

    files = _iter_audio_in_subfolders(parent)
    total = len(files)

    def _pc(idx, name, status, err=""):
        if not progress_callback:
            return
        try:
            progress_callback(idx, total, name, status, err)
        except TypeError:
            progress_callback(idx, total, name, status)

    for i, src in enumerate(files, start=1):
        if is_stopped():
            _pc(i - 1, "", "stopped")
            break

        dst = _unique_dst(parent / src.name)
        try:
            shutil.move(str(src), str(dst))
            result["moved"] += 1
            op = {"src": str(src), "dst": str(dst)}
            result["operations"].append(op)
            if log_callback:
                try:
                    log_callback(op)
                except Exception:
                    pass
            _pc(i, src.name, "moving")
        except Exception as e:
            result["failed"].append({"path": str(src), "error": str(e)})
            _pc(i, src.name, "error", str(e))

    if remove_empty and not is_stopped():
        result["dirs_removed"] = _remove_empty_dirs(parent)

    _pc(total, "", "completed")
    return result
