"""Fetch classifiche musicali da varie sorgenti + cache SQLite.

Sorgenti supportate:
- **iTunes RSS** (`fetch_itunes`) — Top 100 "most-played" per paese (it/us/gb/ww).
  Endpoint pubblico, no auth. Response JSON.
- **Last.fm** (`fetch_lastfm`) — Top tracks per tag (combinazione decade
  + genere musicale, es. "90s dance"). Richiede API key: c'e' una demo
  hardcoded, l'utente puo' generarne una propria e sovrascriverla via
  config (`lastfm_api_key`). https://www.last.fm/api/account/create
- **Spotify** (`fetch_spotify`) — Legge playlist chart editoriali di Spotify
  (Top 50 / Viral 50 per paese) via `playlists/<id>/tracks`. Riusa le
  credenziali Client Credentials gia' configurate (`client_id`/
  `client_secret`). Se mancano ritorna [].
- **M2O Chart** (`fetch_m2o`) — Scraping HTML della chart dance italiana
  settimanale di M2O (https://www.m2o.it/classifiche/m2o-chart/).

Tutte le funzioni ritornano una lista di dict con keys:
    {rank, artist, title, album, image_url, popularity}

Cache SQLite in `~/Library/Application Support/MusicTools/charts_cache.db`
(dev: nella dir del progetto). TTL 6h. `force=True` bypassa la cache.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests


# ---- Last.fm ----
# Demo key: sostituibile via config `lastfm_api_key`. Se questa non funziona
# piu', registrane una nuova su https://www.last.fm/api/account/create.
_LASTFM_KEY = "d060bf4a1907efe5b1e4b8b0f9a4a86e"
_LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

# ---- iTunes RSS ----
_ITUNES_URL_TPL = (
    "https://rss.applemarketingtools.com/api/v2/{country}/music/"
    "most-played/100/songs.json"
)

# ---- Spotify chart playlists ----
# Playlist ID editoriali di Spotify. Chiave interna -> (playlist_id, nome UI).
_SPOTIFY_CHARTS = {
    "top50_global":   ("37i9dQZEVXbMDoHDwVN2tF", "Top 50 Global"),
    "top50_italy":    ("37i9dQZEVXbIQnj7RRhdSX", "Top 50 Italy"),
    "top50_usa":      ("37i9dQZEVXbLRQDuF5jeBp", "Top 50 USA"),
    "top50_uk":       ("37i9dQZEVXbLnolsZ8PSNw", "Top 50 UK"),
    "viral50_global": ("37i9dQZEVXbLiRSasKsNU9", "Viral 50 Global"),
    "viral50_italy":  ("37i9dQZEVXbNFJfN1Vw8d9", "Viral 50 Italy"),
}

# ---- M2O Chart ----
_M2O_URL = "https://www.m2o.it/classifiche/m2o-chart/"

# ---- Cache ----
_CACHE_TTL_SEC = 6 * 3600  # 6h


# ------------------------------------------------------------------
# Cache SQLite
# ------------------------------------------------------------------
def _cache_db_path() -> Path:
    from core.config import _get_config_dir
    return _get_config_dir() / "charts_cache.db"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS charts(
          key TEXT PRIMARY KEY,
          payload TEXT,
          cached_at REAL
        );
        """
    )


def _get_cached(conn: sqlite3.Connection, key: str) -> Optional[list]:
    row = conn.execute(
        "SELECT payload, cached_at FROM charts WHERE key=?", (key,)
    ).fetchone()
    if not row:
        return None
    payload, cached_at = row
    if time.time() - float(cached_at or 0) > _CACHE_TTL_SEC:
        return None
    try:
        data = json.loads(payload)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _put_cache(conn: sqlite3.Connection, key: str, data: list) -> None:
    try:
        conn.execute(
            "INSERT OR REPLACE INTO charts(key, payload, cached_at) VALUES (?, ?, ?)",
            (key, json.dumps(data, ensure_ascii=False), time.time()),
        )
        conn.commit()
    except sqlite3.Error:
        # Cache best-effort: se scrivere fallisce non blocchiamo il fetch
        pass


# ------------------------------------------------------------------
# Last.fm helpers
# ------------------------------------------------------------------
def _get_lastfm_key() -> str:
    """Ritorna la key Last.fm dalla config se settata, altrimenti la demo."""
    try:
        from core.config import load_config
        k = (load_config().get("lastfm_api_key") or "").strip()
        return k or _LASTFM_KEY
    except Exception:
        return _LASTFM_KEY


def _build_lastfm_tag(decade: str, genre: str) -> str:
    """Combina decade + genere in un tag Last.fm compatibile.

    decade: '' | '70s' | '80s' | '90s' | '2000s' | '2010s'
    genre:  '' | 'pop' | 'rock' | 'dance' | ...

    Esempi:
        _build_lastfm_tag('90s', 'dance') -> '90s dance'
        _build_lastfm_tag('', 'italo disco') -> 'italo disco'
        _build_lastfm_tag('80s', '') -> '80s'
        _build_lastfm_tag('', '') -> 'pop'  (fallback)
    """
    d = (decade or "").strip().lower()
    g = (genre or "").strip().lower()
    parts: list = []
    if d:
        parts.append(d)
    if g:
        parts.append(g)
    return " ".join(parts) if parts else "pop"


# ------------------------------------------------------------------
# iTunes RSS
# ------------------------------------------------------------------
def fetch_itunes(country: str = "it", force: bool = False) -> list:
    """Ritorna la top 100 iTunes "most-played" per il paese.

    country: "it" | "us" | "gb" | "ww"

    Ogni entry:
        {rank, artist, title, album, image_url, popularity=None}

    Cache 6h. `force=True` bypassa. In caso di errore HTTP/JSON ritorna [].
    """
    country = (country or "it").lower().strip() or "it"
    key = f"itunes:{country}"

    conn = sqlite3.connect(_cache_db_path())
    try:
        _init_db(conn)
        if not force:
            cached = _get_cached(conn, key)
            if cached is not None:
                return cached

        url = _ITUNES_URL_TPL.format(country=country)
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        entries: list = []
        for i, item in enumerate(
            (data.get("feed", {}) or {}).get("results", []) or [], start=1
        ):
            entries.append({
                "rank": i,
                "artist": (item.get("artistName") or "").strip(),
                "title": (item.get("name") or "").strip(),
                "album": (item.get("collectionName") or "").strip(),
                "image_url": (item.get("artworkUrl100") or "").strip(),
                "popularity": None,
            })
        _put_cache(conn, key, entries)
        return entries
    finally:
        conn.close()


# ------------------------------------------------------------------
# Last.fm
# ------------------------------------------------------------------
def fetch_lastfm(decade: str, genre: str, force: bool = False) -> list:
    """Ritorna top tracks per il tag Last.fm costruito da decade+genere.

    Esempi:
        fetch_lastfm('90s', 'dance')     -> tag '90s dance'
        fetch_lastfm('', 'italo disco')  -> tag 'italo disco'

    Cache 6h. In caso di errore o `tracks.track` mancante ritorna [].
    """
    tag = _build_lastfm_tag(decade, genre)
    key = f"lastfm:{tag}"

    conn = sqlite3.connect(_cache_db_path())
    try:
        _init_db(conn)
        if not force:
            cached = _get_cached(conn, key)
            if cached is not None:
                return cached

        try:
            resp = requests.get(
                _LASTFM_URL,
                params={
                    "method": "tag.gettoptracks",
                    "tag": tag,
                    "api_key": _get_lastfm_key(),
                    "format": "json",
                    "limit": 50,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        entries: list = []
        tracks = (data.get("tracks", {}) or {}).get("track", []) or []
        for i, item in enumerate(tracks, start=1):
            artist_obj = item.get("artist") or {}
            if isinstance(artist_obj, dict):
                artist_name = (artist_obj.get("name") or "").strip()
            else:
                artist_name = str(artist_obj).strip()
            # Ultima immagine (di solito la piu' grande) se presente
            image_url = ""
            imgs = item.get("image") or []
            if isinstance(imgs, list) and imgs:
                last = imgs[-1]
                if isinstance(last, dict):
                    image_url = (last.get("#text") or "").strip()
            entries.append({
                "rank": i,
                "artist": artist_name,
                "title": (item.get("name") or "").strip(),
                "album": "",
                "image_url": image_url,
                "popularity": item.get("listeners"),
            })
        _put_cache(conn, key, entries)
        return entries
    finally:
        conn.close()


# ------------------------------------------------------------------
# Spotify chart playlists
# ------------------------------------------------------------------
def _spotify_credentials() -> tuple:
    """Ritorna (client_id, client_secret) dalla config, o ('','') se assenti."""
    try:
        from core.config import load_config
        cfg = load_config()
        return (
            (cfg.get("client_id") or "").strip(),
            (cfg.get("client_secret") or "").strip(),
        )
    except Exception:
        return ("", "")


def fetch_spotify(playlist_key: str, force: bool = False) -> list:
    """Ritorna i primi 50 brani di una chart playlist editoriale Spotify.

    `playlist_key` deve essere una chiave di `_SPOTIFY_CHARTS`.
    Richiede `client_id`/`client_secret` gia' configurate (le stesse
    usate dalle altre tab). Se mancano o l'auth fallisce ritorna [].
    """
    key = (playlist_key or "").strip()
    if key not in _SPOTIFY_CHARTS:
        return []
    playlist_id, _label = _SPOTIFY_CHARTS[key]
    cache_key = f"spotify:{key}"

    conn = sqlite3.connect(_cache_db_path())
    try:
        _init_db(conn)
        if not force:
            cached = _get_cached(conn, cache_key)
            if cached is not None:
                return cached

        client_id, client_secret = _spotify_credentials()
        if not client_id or not client_secret:
            return []

        # Import qui per evitare import ciclici con core.config a livello modulo.
        from core.spotify_client import get_access_token
        try:
            token = get_access_token(client_id, client_secret)
        except Exception:
            return []

        try:
            resp = requests.get(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        entries: list = []
        items = data.get("items") or []
        for i, item in enumerate(items, start=1):
            track = (item or {}).get("track") or {}
            if not track:
                continue
            artists = track.get("artists") or []
            artist_names = [
                (a.get("name") or "").strip()
                for a in artists
                if isinstance(a, dict) and a.get("name")
            ]
            artist = ", ".join(artist_names)
            album = ((track.get("album") or {}).get("name") or "").strip()
            image_url = ""
            imgs = ((track.get("album") or {}).get("images") or [])
            if imgs and isinstance(imgs[0], dict):
                image_url = (imgs[0].get("url") or "").strip()
            entries.append({
                "rank": i,
                "artist": artist,
                "title": (track.get("name") or "").strip(),
                "album": album,
                "image_url": image_url,
                "popularity": track.get("popularity"),
            })
        _put_cache(conn, cache_key, entries)
        return entries
    finally:
        conn.close()


# ------------------------------------------------------------------
# M2O Chart
# ------------------------------------------------------------------
def fetch_m2o(force: bool = False) -> list:
    """Scraping della chart dance italiana settimanale di M2O.

    La pagina non ha API: parsiamo l'HTML con BeautifulSoup. Estraiamo
    da ogni <article>:
        - rank    <- .position (int, altrimenti skip)
        - title   <- h3.title.song
        - artist  <- h4.title.author (lista virgola-separata, lasciata così)
        - image_url <- figure img[src]

    album e popularity sono sempre vuoti (non presenti nella pagina).
    Cache 6h. Errori HTTP/parse -> [].
    """
    cache_key = "m2o:chart"

    conn = sqlite3.connect(_cache_db_path())
    try:
        _init_db(conn)
        if not force:
            cached = _get_cached(conn, cache_key)
            if cached is not None:
                return cached

        try:
            resp = requests.get(
                _M2O_URL,
                headers={"User-Agent": "Mozilla/5.0 (MusicTools charts)"},
                timeout=15,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception:
            return []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return []

        entries: list = []
        for art in soup.find_all("article"):
            pos_el = art.select_one(".position")
            if pos_el is None:
                continue
            try:
                rank = int((pos_el.get_text() or "").strip())
            except (ValueError, TypeError):
                continue

            title_el = art.select_one("h3.title.song") or art.select_one("h3.song")
            artist_el = art.select_one("h4.title.author") or art.select_one("h4.author")
            title = title_el.get_text(strip=True) if title_el else ""
            artist = artist_el.get_text(strip=True) if artist_el else ""
            if not title and not artist:
                continue

            img_el = art.select_one("figure img")
            image_url = ""
            if img_el is not None:
                image_url = (img_el.get("src") or img_el.get("data-src") or "").strip()

            entries.append({
                "rank": rank,
                "artist": artist,
                "title": title,
                "album": "",
                "image_url": image_url,
                "popularity": None,
            })

        entries.sort(key=lambda e: e.get("rank", 9999))
        _put_cache(conn, cache_key, entries)
        return entries
    finally:
        conn.close()
