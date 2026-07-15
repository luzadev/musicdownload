"""Fetch Top 100 Beatport per genere.

Approccio: estrai il JSON `__NEXT_DATA__` dal HTML della pagina Next.js.
Bypass Cloudflare via curl_cffi (TLS impersonation).
Vedi docs/superpowers/specs/2026-07-14-beatport-charts-design.md.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from curl_cffi import requests as _cffi_requests


@dataclass(frozen=True)
class BeatportTrack:
    position: int
    title: str
    mix: str          # es. "Extended Mix", "Original Mix", ""
    artists: str      # es. "A, B & C" già formattato
    duration_sec: int
    beatport_id: int
    image_url: str = ""   # URL cover art (default vuoto per retrocompatibilità test)

    @property
    def display(self) -> str:
        """Formato testo compatibile coi file .txt curati a mano:
        'Artista – Titolo (Mix) (M:SS)'."""
        m, s = divmod(self.duration_sec, 60)
        return f"{self.artists} – {self.title} ({self.mix}) ({m}:{s:02d})"

    @property
    def spotify_query(self) -> str:
        """Query pura per la search Spotify (senza mix name, che disturba
        il matching su titoli tipo 'Extended Mix')."""
        return f"{self.artists} {self.title}"


class BeatportError(Exception):
    """Base per errori Beatport."""


class BeatportUnreachableError(BeatportError):
    """Rete o server Beatport non raggiungibile / 5xx."""


class BeatportParseError(BeatportError):
    """HTML/JSON ricevuto ma non conforme allo schema atteso."""


_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
    re.DOTALL,
)


def _extract_next_data(html: str) -> dict:
    """Estrae il payload JSON dallo script <__NEXT_DATA__> di Next.js."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise BeatportParseError("__NEXT_DATA__ non trovato nella pagina Beatport")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise BeatportParseError(f"__NEXT_DATA__ JSON malformato: {e}") from e


# Mappa slug URL Beatport -> (numeric_id, display_name)
# Enumerata via scripts/refresh_beatport_genres.py (Task 1).
# Copia dell'output di /tmp/genres_output.txt (31 generi).
GENRES: dict = {
    "drum-bass": (1, "Drum & Bass"),
    "hard-techno": (2, "Hard Techno"),
    "electronica": (3, "Electronica"),
    "house": (5, "House"),
    "techno-peak-time-driving": (6, "Techno (Peak Time / Driving)"),
    "trance-main-floor": (7, "Trance (Main Floor)"),
    "hard-dance-hardcore-neo-rave": (8, "Hard Dance / Hardcore / Neo Rave"),
    "breaks-breakbeat-uk-bass": (9, "Breaks / Breakbeat / UK Bass"),
    "tech-house": (11, "Tech House"),
    "deep-house": (12, "Deep House"),
    "psy-trance": (13, "Psy-Trance"),
    "minimal-deep-tech": (14, "Minimal / Deep Tech"),
    "progressive-house": (15, "Progressive House"),
    "dubstep": (18, "Dubstep"),
    "indie-dance": (37, "Indie Dance"),
    "trap-future-bass": (38, "Trap / Future Bass"),
    "dance-pop": (39, "Dance / Pop"),
    "nu-disco-disco": (50, "Nu Disco / Disco"),
    "funky-house": (81, "Funky House"),
    "bass-club": (85, "Bass / Club"),
    "uk-garage-bassline": (86, "UK Garage / Bassline"),
    "afro-house": (89, "Afro House"),
    "melodic-house-techno": (90, "Melodic House & Techno"),
    "bass-house": (91, "Bass House"),
    "techno-raw-deep-hypnotic": (92, "Techno (Raw / Deep / Hypnotic)"),
    "organic-house": (93, "Organic House"),
    "electro-classic-detroit-modern": (94, "Electro (Classic / Detroit / Modern)"),
    "140-deep-dubstep-grime": (95, "140 / Deep Dubstep / Grime"),
    "mainstage": (96, "Mainstage"),
    "jackin-house": (97, "Jackin House"),
    "trance-raw-deep-hypnotic": (99, "Trance (Raw / Deep / Hypnotic)"),
}


def list_genres() -> list:
    """Ritorna [{slug, id, name}, ...] ordinato alfabeticamente per name."""
    result = [
        {"slug": slug, "id": gid, "name": name}
        for slug, (gid, name) in GENRES.items()
    ]
    result.sort(key=lambda g: g["name"].casefold())
    return result


def _find_tracks_results(data: dict) -> list:
    """Cerca dentro le queries dehydrated il primo `results` che ha almeno 50 elementi
    e la shape di una track (chiave `id` presente)."""
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError) as e:
        raise BeatportParseError(
            f"schema JSON inatteso, `results` non localizzabile (chiave mancante: {e})"
        ) from e

    for q in queries:
        state_data = (q or {}).get("state", {}).get("data")
        if not isinstance(state_data, dict):
            continue
        results = state_data.get("results")
        if isinstance(results, list) and len(results) >= 50:
            if results and isinstance(results[0], dict) and "id" in results[0]:
                return results
    raise BeatportParseError("nessun `results` di 50+ track trovato in __NEXT_DATA__")


def _format_artists(artists_field: object) -> str:
    """Beatport ritorna artists come lista di dict {name, ...}.
    Formatta come 'A, B & C' (& prima dell'ultimo)."""
    if not isinstance(artists_field, list) or not artists_field:
        return ""
    names = [a.get("name", "") for a in artists_field if isinstance(a, dict)]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " & " + names[-1]


def _extract_image_url(image_field: object, size: int = 95) -> str:
    """Estrae URL cover art dall'oggetto `image` di Beatport.
    Preferisce `dynamic_uri` sostituendo {w}x{h}, fallback a `uri` fisso."""
    if not isinstance(image_field, dict):
        return ""
    dyn = image_field.get("dynamic_uri") or ""
    if isinstance(dyn, str) and "{w}" in dyn and "{h}" in dyn:
        return dyn.replace("{w}", str(size)).replace("{h}", str(size))
    return image_field.get("uri") or ""


def _parse_tracks(data: dict) -> list:
    """Trasforma i track dict di Beatport in BeatportTrack ordinati per posizione."""
    raw = _find_tracks_results(data)
    out: list = []
    for i, item in enumerate(raw, 1):
        try:
            length_ms = int(item.get("length_ms") or 0)
            track = BeatportTrack(
                position=i,
                title=str(item.get("name") or "").strip(),
                mix=str(item.get("mix_name") or "").strip(),
                artists=_format_artists(item.get("artists")),
                duration_sec=length_ms // 1000,
                beatport_id=int(item.get("id") or 0),
                image_url=_extract_image_url(item.get("image")),
            )
        except (TypeError, ValueError) as e:
            raise BeatportParseError(f"track[{i}] shape inattesa: {e}") from e
        out.append(track)
    return out


_IMPERSONATE = "chrome131"  # aggiorna se CF rompe il fingerprint
_REQUEST_TIMEOUT = 15
_MAX_ATTEMPTS = 3
_BACKOFF_SEC = [1, 3]  # attese fra tentativi
_CACHE_TTL_SEC = 15 * 60

# Cache in-memory: slug → (timestamp_epoch, list[BeatportTrack])
_cache: dict = {}


def _url_for(slug: str) -> str:
    gid, _ = GENRES[slug]
    return f"https://www.beatport.com/genre/{slug}/{gid}/top-100"


def _do_get(url: str) -> str:
    """GET con retry e backoff. Solleva BeatportUnreachableError su fallimento definitivo."""
    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = _cffi_requests.get(
                url,
                impersonate=_IMPERSONATE,
                timeout=_REQUEST_TIMEOUT,
            )
            if resp.status_code >= 500 or resp.status_code == 403:
                raise Exception(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SEC[attempt])
    raise BeatportUnreachableError(f"Beatport irraggiungibile dopo {_MAX_ATTEMPTS} tentativi: {last_exc}")


def fetch_top100(slug: str, force_refresh: bool = False) -> list:
    """Fetches la Top 100 Beatport per il genere dato.

    Cache in-memory 15 min. `force_refresh=True` bypassa la cache.

    Raises:
        ValueError: se slug non è in GENRES.
        BeatportUnreachableError: rete/5xx dopo i retry.
        BeatportParseError: HTML/JSON non conforme allo schema.
    """
    if slug not in GENRES:
        raise ValueError(f"slug genere non valido: {slug!r}")

    now = time.time()
    if not force_refresh:
        cached = _cache.get(slug)
        if cached and (now - cached[0]) < _CACHE_TTL_SEC:
            return cached[1]

    html = _do_get(_url_for(slug))
    data = _extract_next_data(html)
    tracks = _parse_tracks(data)
    _cache[slug] = (now, tracks)
    return tracks
