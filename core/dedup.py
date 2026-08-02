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
def _run_fpcalc(fpcalc: str, path: str, length: Optional[int] = None) -> dict:
    """Esegue fpcalc una volta. Ritorna {duration, fingerprint} su successo
    o {_error: str} su fallimento."""
    cmd = [fpcalc, "-json"]
    if length is not None:
        cmd += ["-length", str(length)]
    cmd.append(str(path))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_FPCALC_TIMEOUT_SEC,
            **subprocess_flags(),
        )
    except subprocess.TimeoutExpired:
        return {"_error": f"timeout {_FPCALC_TIMEOUT_SEC}s"}
    except (OSError, ValueError) as e:
        return {"_error": f"subprocess: {e}"}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        msg = err[-1] if err else f"exit {proc.returncode}"
        return {"_error": msg[:200]}
    try:
        data = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, ValueError) as e:
        return {"_error": f"JSON malformato: {e}"}
    fp = data.get("fingerprint")
    if not fp:
        return {"_error": "fingerprint vuoto (audio troppo corto?)"}
    try:
        dur = float(data.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"duration": dur, "fingerprint": str(fp)}


def compute_fingerprint(fpcalc: str, path: str) -> Optional[dict]:
    """Chiama fpcalc e ritorna {duration, fingerprint} o {_error}.

    Se il primo tentativo (full length) fallisce con "Invalid data" o simili
    (frame audio corrotti che libav rifiuta), riprova con `-length 30`.
    Molti file danneggiati hanno i frame corrotti nella parte finale e
    limitando la scansione ai primi 30s si riesce a estrarre comunque
    un fingerprint affidabile (30s bastano per l'unicità Chromaprint).
    """
    if not fpcalc:
        return {"_error": "fpcalc non trovato nel bundle"}

    res = _run_fpcalc(fpcalc, path)
    if "fingerprint" in res:
        return res

    err_msg = res.get("_error", "").lower()

    # Retry 1: frame audio corrotti → riduci finestra a 30s
    corrupt_signals = ("invalid data", "decoding audio frame",
                       "error while decoding", "invalid frame")
    if any(sig in err_msg for sig in corrupt_signals):
        res2 = _run_fpcalc(fpcalc, path, length=30)
        if "fingerprint" in res2:
            res2["_partial"] = True  # 30s soltanto
            return res2

    # Retry 2: fingerprint vuoto → prova con finestra piu' lunga (60s)
    # nel caso l'intro sia silenzio/muto (chromaprint richiede audio "reale")
    if "vuoto" in err_msg or "empty" in err_msg:
        res2 = _run_fpcalc(fpcalc, path, length=60)
        if "fingerprint" in res2:
            res2["_partial"] = True
            return res2
        # Ancora vuoto → prova algoritmo differente (chromaprint algo 1)
        # tramite subprocess diretto perche' _run_fpcalc non lo supporta
        try:
            proc = subprocess.run(
                [fpcalc, "-json", "-length", "60", "-algorithm", "1", str(path)],
                capture_output=True, text=True,
                timeout=_FPCALC_TIMEOUT_SEC,
                **subprocess_flags(),
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout or "{}")
                fp = data.get("fingerprint")
                if fp:
                    return {
                        "duration": float(data.get("duration") or 0),
                        "fingerprint": str(fp),
                        "_partial": True,
                    }
        except Exception:
            pass

    return res


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


def _scan_by_filename(files: list, progress_callback: Optional[Callable],
                       group_callback: Optional[Callable] = None,
                       similarity_threshold: float = 0.8) -> list[list[dict]]:
    """Raggruppa file per similarità nome (Jaccard sui token normalizzati),
    algoritmo INCREMENTALE: per ogni nuovo file cerca match tra i gruppi già
    formati (lookup O(K) dove K = numero gruppi). Emette streaming via
    `group_callback` appena un gruppo raggiunge ≥ 2 file.
    """
    from core.upgrader import _normalize_stem  # riuso

    def _pc(idx, total_n, name, status, err=""):
        if not progress_callback:
            return
        try:
            progress_callback(idx, total_n, name, status, err)
        except TypeError:
            progress_callback(idx, total_n, name, status)

    def _gc(group_id: str, entries: list) -> None:
        if group_callback:
            try:
                group_callback({"id": group_id, "entries": list(entries)})
            except Exception:
                pass

    total = len(files)
    # Ogni voce: {"id": str, "key_tokens": frozenset, "entries": [dict]}
    groups: list = []

    for i, fp_path in enumerate(files, start=1):
        if is_stopped():
            _pc(i - 1, total, "", "stopped")
            break
        try:
            size = fp_path.stat().st_size
        except OSError as e:
            _pc(i, total, fp_path.name, "error", f"stat: {e}")
            continue
        tokens = frozenset(_normalize_stem(fp_path.stem))
        if not tokens:
            _pc(i, total, fp_path.name, "error", "nome senza token utili")
            continue
        try:
            bitrate = get_bitrate(fp_path)
        except Exception:
            bitrate = 0
        entry = {
            "path": str(fp_path), "size": size, "bitrate": bitrate,
            "duration": 0, "fingerprint": "",
        }

        # Cerca match nei gruppi già formati (lineare sui gruppi, non sui file)
        matched = None
        for g in groups:
            common = len(tokens & g["key_tokens"])
            if common == 0:
                continue
            union = len(tokens | g["key_tokens"])
            if union > 0 and (common / union) >= similarity_threshold:
                matched = g
                break

        if matched is not None:
            was_solo = len(matched["entries"]) == 1
            matched["entries"].append(entry)
            matched["entries"].sort(key=lambda e: (-e["bitrate"], -e["size"]))
            # Streaming: emit ogni volta che il gruppo diventa/rimane ≥ 2 file
            _gc(matched["id"], matched["entries"])
        else:
            gid = f"fn_{len(groups)}_{fp_path.stem[:20]}"
            groups.append({
                "id": gid,
                "key_tokens": set(tokens),
                "entries": [entry],
            })
        _pc(i, total, fp_path.name, "cached")

    # Ritorna solo i gruppi con >= 2 file
    result = [sorted(g["entries"], key=lambda e: (-e["bitrate"], -e["size"]))
              for g in groups if len(g["entries"]) >= 2]
    result.sort(key=lambda g: -max(e["size"] for e in g))
    _pc(total, total, "", "completed")
    return result


def scan_folder(
    directory: str,
    recursive: bool = True,
    progress_callback: Optional[Callable] = None,
    method: str = "fingerprint",
    group_callback: Optional[Callable] = None,
) -> list[list[dict]]:
    """Ritorna la lista di gruppi di file duplicati (>= 2 file).

    Ogni file nel gruppo e' un dict:
        {path, size, bitrate, duration, fingerprint}

    Gruppi ordinati per size del file piu' grande DESC (i gruppi che
    occupano piu' spazio vengono prima). All'interno di ogni gruppo:
    bitrate DESC, poi size DESC (il primo e' quello "da tenere").

    `method`:
    - "fingerprint" (default): Chromaprint via fpcalc, preciso ma lento.
      Cache SQLite persistente. Raggruppa per fingerprint identico.
    - "filename": similarità Jaccard sui nomi file. Veloce ma euristico.
      Non richiede fpcalc.
    """
    reset_stop()
    files = _iter_audio_files(directory, recursive)
    total = len(files)
    if total == 0:
        if progress_callback:
            progress_callback(0, 0, "", "completed")
        return []

    if method == "filename":
        return _scan_by_filename(files, progress_callback, group_callback)

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

        def _pc(idx, total_n, name, status, err=""):
            """Chiama progress_callback in modo retrocompatibile: la firma
            legacy è a 4 args, quella nuova a 5 con `error_msg` opzionale."""
            if not progress_callback:
                return
            try:
                progress_callback(idx, total_n, name, status, err)
            except TypeError:
                progress_callback(idx, total_n, name, status)

        for i, fp_path in enumerate(files, start=1):
            if is_stopped():
                _pc(i - 1, total, "", "stopped")
                return []
            try:
                st = fp_path.stat()
                size = st.st_size
                mtime = st.st_mtime
            except OSError as e:
                _pc(i, total, fp_path.name, "error", f"stat: {e}")
                continue

            path_str = str(fp_path)
            cached = _cache_get(conn, path_str, size, mtime)
            if cached:
                fp_hash = cached["fingerprint"]
                duration = cached["duration"]
                bitrate = cached["bitrate"] or get_bitrate(fp_path)
                _pc(i, total, fp_path.name, "cached")
            else:
                _pc(i, total, fp_path.name, "computing")
                res = compute_fingerprint(fpcalc, path_str)
                if not res or not res.get("fingerprint"):
                    err_msg = (res or {}).get("_error", "errore sconosciuto")
                    _pc(i, total, fp_path.name, "error", err_msg)
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
            grp = by_fp.setdefault(fp_hash, [])
            grp.append(entry)
            # Streaming: appena il gruppo raggiunge (o supera) 2 elementi,
            # emetti update (JS accumula/aggiorna in tempo reale)
            if group_callback and len(grp) >= 2:
                # Ordinamento intra-gruppo prima di emit (best-to-keep primo)
                grp.sort(key=lambda e: (-int(e.get("bitrate") or 0),
                                        -int(e.get("size") or 0)))
                try:
                    group_callback({
                        "id": f"fp_{fp_hash[:24]}",
                        "entries": list(grp),
                    })
                except Exception:
                    pass
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
