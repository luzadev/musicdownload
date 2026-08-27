"""AcoustID + MusicBrainz lookup con cache SQLite.

Data un fingerprint Chromaprint (calcolato via `fpcalc`), interroga il
servizio pubblico AcoustID (https://acoustid.org) per recuperare
metadati sulla traccia: artista, titolo, anno di rilascio piu' antico
e (best-effort) un genere estratto dai tag dei release group MusicBrainz.

I risultati vengono cacheati su SQLite (chiave = fingerprint) per non
sprecare quota API su scan ripetute. La rate limit e' auto-imposta a
~3 req/s per rispettare i limiti pubblici AcoustID.

Nota: l'API AcoustID base NON restituisce sempre il genere — dipende
dai tag presenti nel release group MusicBrainz. Molte tracce dance
electronic hanno pochi tag; il campo `genre` puo' quindi essere vuoto
anche con un match valido. In quel caso il chiamante rimapa in
"Unknown Genre".
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests


# App key pubblica per MusicTools. Puo' essere sovrascritta passando
# `app_key` esplicito o via config. Chiavi si ottengono gratis su
# https://acoustid.org/api-key (max ~3 req/s).
_APP_KEY = "8XaBELgH"  # placeholder demo — sostituibile via config
_API_URL = "https://api.acoustid.org/v2/lookup"
_REQUEST_TIMEOUT = 20
_RATE_LIMIT_SEC = 0.35  # ~3 req/s max


def _cache_db_path() -> Path:
    """Path del DB di cache dei lookup AcoustID.

    Riusa `_get_config_dir` di core.config cosi' finisce nella stessa
    cartella di config.json e dedup_cache.db.
    """
    from core.config import _get_config_dir
    return _get_config_dir() / "catalog_cache.db"


def _init_db(conn: sqlite3.Connection) -> None:
    """Crea (idempotente) lo schema della cache."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lookups(
            fingerprint TEXT PRIMARY KEY,
            payload     TEXT NOT NULL,
            cached_at   REAL NOT NULL
        );
        """
    )
    conn.commit()


def _open_cache() -> sqlite3.Connection:
    """Apre (creando se serve) la connessione alla cache."""
    p = _cache_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    _init_db(conn)
    return conn


def _get_cached(conn: sqlite3.Connection, fingerprint: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT payload FROM lookups WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _put_cache(conn: sqlite3.Connection, fingerprint: str, data: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO lookups(fingerprint, payload, cached_at)"
        " VALUES (?, ?, ?)",
        (fingerprint, json.dumps(data, ensure_ascii=False), time.time()),
    )
    conn.commit()


# Rate-limit state (globale al processo — vale anche se lookup chiamato
# da thread diversi: non e' esattamente thread-safe ma il worst-case e'
# una richiesta leggermente troppo veloce, non un ban).
_last_request_at = [0.0]


def _throttle() -> None:
    """Attende quel tanto che basta per rispettare _RATE_LIMIT_SEC."""
    now = time.monotonic()
    elapsed = now - _last_request_at[0]
    if elapsed < _RATE_LIMIT_SEC:
        time.sleep(_RATE_LIMIT_SEC - elapsed)
    _last_request_at[0] = time.monotonic()


def _extract_min_year(releases: list) -> Optional[int]:
    """Trova l'anno piu' antico tra i release. Ignora date invalide."""
    year: Optional[int] = None
    for rel in releases or []:
        date = rel.get("date") if isinstance(rel, dict) else None
        if not isinstance(date, dict):
            continue
        y = date.get("year")
        if isinstance(y, int) and y > 0:
            if year is None or y < year:
                year = y
    return year


def _extract_top_genre(releases: list) -> str:
    """Sceglie il tag piu' rilevante dai releasegroup (max `count`)."""
    for rel in releases or []:
        rg = rel.get("releasegroup") if isinstance(rel, dict) else None
        if not isinstance(rg, dict):
            continue
        tags = rg.get("tags") or []
        if not isinstance(tags, list) or not tags:
            continue
        try:
            top = max(tags, key=lambda t: int(t.get("count", 0) or 0))
        except (TypeError, ValueError):
            top = tags[0]
        name = (top.get("name") or "").strip() if isinstance(top, dict) else ""
        if name:
            return name
    return ""


def lookup(fingerprint: str, duration: float,
           app_key: str = _APP_KEY) -> dict:
    """Interroga AcoustID (o cache) per una tripla (year, genre, title).

    Ritorna sempre un dict con almeno il campo `matched: bool`. In caso
    di match valido, aggiunge `year: int|None`, `genre: str`,
    `artist: str`, `title: str`. In caso di errore aggiunge `error: str`
    ma NON alza eccezione: chiamanti di batch (Cataloga) devono poter
    continuare anche se una chiamata singola fallisce.

    Cache: risultati validi E "no match" vengono cacheati sul
    fingerprint — cosi' scansioni ripetute non re-interrogano l'API.
    Errori transitori (rete/HTTP) NON vengono cacheati.
    """
    if not fingerprint:
        return {"matched": False, "error": "fingerprint vuoto"}
    if not app_key:
        app_key = _APP_KEY

    conn = _open_cache()
    try:
        cached = _get_cached(conn, fingerprint)
        if cached is not None:
            return cached

        _throttle()
        try:
            resp = requests.get(
                _API_URL,
                params={
                    "client": app_key,
                    "meta": "recordings+releases+releasegroups",
                    "duration": int(duration or 0),
                    "fingerprint": fingerprint,
                },
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            return {"matched": False, "error": f"network: {e}"}
        except Exception as e:
            return {"matched": False, "error": str(e)}

        if resp.status_code != 200:
            return {"matched": False, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except Exception as e:
            return {"matched": False, "error": f"JSON malformato: {e}"}

        if data.get("status") != "ok":
            err = data.get("error", {}) or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            return {"matched": False, "error": msg or "AcoustID status non-ok"}

        results = data.get("results") or []
        if not results:
            result = {"matched": False}
            _put_cache(conn, fingerprint, result)
            return result

        # Match col miglior score
        best = max(results, key=lambda r: r.get("score", 0) or 0)
        recordings = best.get("recordings") or []
        if not recordings:
            result = {"matched": False}
            _put_cache(conn, fingerprint, result)
            return result

        rec = recordings[0] or {}
        title = (rec.get("title") or "").strip()
        artists = rec.get("artists") or []
        artist_names = [
            (a.get("name") or "").strip()
            for a in artists
            if isinstance(a, dict) and a.get("name")
        ]
        artist = ", ".join(n for n in artist_names if n)

        releases = rec.get("releases") or []
        year = _extract_min_year(releases)
        genre = _extract_top_genre(releases)

        result = {
            "matched": bool(year or genre or title),
            "year": year,
            "genre": genre,
            "artist": artist,
            "title": title,
        }
        _put_cache(conn, fingerprint, result)
        return result
    finally:
        try:
            conn.close()
        except Exception:
            pass
