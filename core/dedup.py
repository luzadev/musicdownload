"""Deduplicator audio via Chromaprint fingerprinting + SQLite cache.

Pipeline:
  1. Scansiona la cartella (opzionalmente ricorsivo) filtrando per
     estensioni audio (AUDIO_EXTENSIONS di core.upgrader).
  2. Per ogni file calcola il fingerprint Chromaprint (`fpcalc -json`).
     Il valore viene messo in cache SQLite: al re-scan, se
     (size, mtime) coincide col record, riusiamo il fingerprint senza
     rilanciare fpcalc.
  3. Raggruppa i file per fingerprint identico (>= 2 file). Per ogni
     gruppo, i file vengono ordinati per bitrate DESC (tie-break: size
     DESC): il primo e' quello "da tenere", gli altri i duplicati.
  4. `move_to_trash` invia i path selezionati al cestino di sistema
     tramite send2trash (reversibile via Finder/Explorer).

Progress callback firma:
    (processed: int, total: int, filename: str, status: str)
Status validi: 'scanning' | 'computing' | 'cached' | 'error' | 'stopped'
              | 'completed'.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from core.paths import find_fpcalc, subprocess_flags
from core.upgrader import AUDIO_EXTENSIONS, get_bitrate


# Timeout massimo per una singola invocazione fpcalc.
_FPCALC_TIMEOUT_SEC = 30


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
# Cache SQLite
# ------------------------------------------------------------------
def _cache_db_path() -> Path:
    """Path del DB di cache dei fingerprint.

    Riusa `_get_config_dir` di core.config cosi' finisce nella stessa
    cartella di config.json (~/Library/Application Support/MusicTools/
    su macOS, %APPDATA%/MusicTools/ su Windows, project root in dev).
    """
    from core.config import _get_config_dir
    return _get_config_dir() / "dedup_cache.db"


def _init_db(conn: sqlite3.Connection) -> None:
    """Crea (idempotente) lo schema della cache."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path        TEXT PRIMARY KEY,
            size        INTEGER NOT NULL,
            mtime       REAL NOT NULL,
            duration    REAL,
            fingerprint TEXT,
            bitrate     INTEGER
        )
        """
    )
    conn.commit()


def _open_cache(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Apre (creando se serve) la connessione alla cache."""
    p = db_path or _cache_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    _init_db(conn)
    return conn


def _cache_get(conn: sqlite3.Connection, path: str,
               size: int, mtime: float) -> Optional[dict]:
    """Ritorna il record se (size, mtime) invariato, altrimenti None."""
    cur = conn.execute(
        "SELECT size, mtime, duration, fingerprint, bitrate FROM files WHERE path = ?",
        (path,),
    )
    row = cur.fetchone()
    if not row:
        return None
    csize, cmtime, dur, fp, br = row
    # Tolleranza minima sul mtime (float precision su alcuni FS)
    if csize != size or abs(float(cmtime) - float(mtime)) > 0.001:
        return None
    if not fp:
        return None
    return {
        "size": int(csize),
        "mtime": float(cmtime),
        "duration": float(dur) if dur is not None else 0.0,
        "fingerprint": str(fp),
        "bitrate": int(br) if br is not None else 0,
    }


def _cache_put(conn: sqlite3.Connection, path: str, size: int, mtime: float,
               duration: float, fingerprint: str, bitrate: int) -> None:
    """Upsert (SQLite ha ON CONFLICT REPLACE via INSERT OR REPLACE)."""
    conn.execute(
        "INSERT OR REPLACE INTO files (path, size, mtime, duration, fingerprint, bitrate)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (path, int(size), float(mtime), float(duration or 0),
         str(fingerprint or ""), int(bitrate or 0)),
    )
    conn.commit()


# ------------------------------------------------------------------
# fpcalc
# ------------------------------------------------------------------
def compute_fingerprint(fpcalc: str, path: str) -> Optional[dict]:
    """Chiama `fpcalc -json <file>` e ritorna {duration, fingerprint}.

    Ritorna None su qualsiasi errore (fpcalc mancante, file corrotto,
    timeout, JSON malformato).
    """
    if not fpcalc:
        return None
    try:
        proc = subprocess.run(
            [fpcalc, "-json", str(path)],
            capture_output=True,
            text=True,
            timeout=_FPCALC_TIMEOUT_SEC,
            **subprocess_flags(),
        )
    except subprocess.TimeoutExpired:
        return None
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, ValueError):
        return None
    fp = data.get("fingerprint")
    if not fp:
        return None
    try:
        dur = float(data.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"duration": dur, "fingerprint": str(fp)}


# ------------------------------------------------------------------
# Scan
# ------------------------------------------------------------------
def _iter_audio_files(directory: str, recursive: bool) -> list[Path]:
    """Elenca tutti i file audio (estensione case-insensitive)."""
    base = Path(directory)
    if not base.exists() or not base.is_dir():
        return []
    files: list[Path] = []
    if recursive:
        for f in base.rglob("*"):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                files.append(f)
    else:
        for f in base.iterdir():
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                files.append(f)
    files.sort()
    return files


def scan_folder(
    directory: str,
    recursive: bool = True,
    progress_callback: Optional[Callable] = None,
) -> list[list[dict]]:
    """Ritorna la lista di gruppi di file duplicati (>= 2 file).

    Ogni file nel gruppo e' un dict:
        {path, size, bitrate, duration, fingerprint}

    Gruppi ordinati per size del file piu' grande DESC (i gruppi che
    occupano piu' spazio vengono prima). All'interno di ogni gruppo:
    bitrate DESC, poi size DESC (il primo e' quello "da tenere").

    Il fingerprint viene calcolato via `fpcalc -json` e messo in cache
    SQLite. Al re-scan, se (size, mtime) invariati, non si rilancia fpcalc.
    """
    reset_stop()
    files = _iter_audio_files(directory, recursive)
    total = len(files)
    if total == 0:
        if progress_callback:
            progress_callback(0, 0, "", "completed")
        return []

    fpcalc = find_fpcalc()
    if not fpcalc:
        # Senza fpcalc non possiamo fare nulla. Segnaliamo errore su ogni
        # file e ritorniamo lista vuota.
        if progress_callback:
            progress_callback(0, total, "", "error")
        return []

    conn = _open_cache()
    try:
        # {fingerprint: [entry, ...]}
        by_fp: dict[str, list[dict]] = {}

        for i, fp_path in enumerate(files, start=1):
            if is_stopped():
                if progress_callback:
                    progress_callback(i - 1, total, "", "stopped")
                return []
            try:
                st = fp_path.stat()
                size = st.st_size
                mtime = st.st_mtime
            except OSError:
                if progress_callback:
                    progress_callback(i, total, fp_path.name, "error")
                continue

            path_str = str(fp_path)
            cached = _cache_get(conn, path_str, size, mtime)
            if cached:
                fp_hash = cached["fingerprint"]
                duration = cached["duration"]
                bitrate = cached["bitrate"] or get_bitrate(fp_path)
                if progress_callback:
                    progress_callback(i, total, fp_path.name, "cached")
            else:
                if progress_callback:
                    progress_callback(i, total, fp_path.name, "computing")
                res = compute_fingerprint(fpcalc, path_str)
                if not res:
                    if progress_callback:
                        progress_callback(i, total, fp_path.name, "error")
                    continue
                fp_hash = res["fingerprint"]
                duration = res["duration"]
                try:
                    bitrate = get_bitrate(fp_path)
                except Exception:
                    bitrate = 0
                _cache_put(conn, path_str, size, mtime, duration, fp_hash, bitrate)

            entry = {
                "path": path_str,
                "size": int(size),
                "bitrate": int(bitrate or 0),
                "duration": float(duration or 0),
                "fingerprint": fp_hash,
            }
            by_fp.setdefault(fp_hash, []).append(entry)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Filtra: solo gruppi con >= 2 file
    groups = [g for g in by_fp.values() if len(g) >= 2]

    # Sort dei file dentro il gruppo: bitrate DESC, size DESC.
    # Sort dei gruppi: size del file piu' grande DESC (usa max del gruppo).
    for g in groups:
        g.sort(key=lambda e: (-int(e.get("bitrate") or 0),
                              -int(e.get("size") or 0)))
    groups.sort(key=lambda g: -max(int(e.get("size") or 0) for e in g))

    if progress_callback:
        progress_callback(total, total, "", "completed")

    return groups


# ------------------------------------------------------------------
# Trash
# ------------------------------------------------------------------
def move_to_trash(paths: list[str]) -> dict:
    """Sposta i file in cestino tramite send2trash.

    Ritorna {moved: [...], failed: [{path, error}, ...]}. Non solleva
    mai eccezioni: gli errori per file singolo finiscono in `failed`.
    Aggiorna la cache SQLite rimuovendo i record dei file spostati (per
    quelli riusciti), cosi' un re-scan non li propone piu'.
    """
    # Import interno per rendere il modulo importabile anche se
    # send2trash non e' installato (i test possono mockarlo).
    try:
        from send2trash import send2trash
    except Exception as e:  # pragma: no cover — solo se pacchetto mancante
        return {
            "moved": [],
            "failed": [{"path": p, "error": f"send2trash non disponibile: {e}"}
                       for p in (paths or [])],
        }

    moved: list[str] = []
    failed: list[dict] = []
    for p in (paths or []):
        try:
            send2trash(p)
            moved.append(p)
        except Exception as e:
            failed.append({"path": p, "error": str(e)})

    # Cache cleanup best-effort (non fatale se fallisce)
    if moved:
        try:
            conn = _open_cache()
            try:
                for p in moved:
                    conn.execute("DELETE FROM files WHERE path = ?", (p,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    return {"moved": moved, "failed": failed}
