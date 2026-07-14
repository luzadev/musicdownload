"""Client API Spotify — autenticazione e fetch playlist/track/album."""

from __future__ import annotations

import re
import requests


def get_access_token(client_id: str, client_secret: str) -> str:
    """Ottiene un access token tramite Client Credentials Flow."""
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise ValueError("Token non ricevuto da Spotify")
    return token


# ---------------------------------------------------------------------------
# Riconoscimento tipo URL
# ---------------------------------------------------------------------------

def detect_url_type(url: str) -> tuple[str, str]:
    """Rileva il tipo di URL Spotify e ne estrae l'ID.

    Ritorna (tipo, id) dove tipo e "track", "album" o "playlist".
    Solleva ValueError se l'URL non e riconosciuto.
    """
    for kind in ("track", "album", "playlist"):
        match = re.search(rf"{kind}/([a-zA-Z0-9]+)", url)
        if match:
            return kind, match.group(1)
    raise ValueError(
        "URL non riconosciuto. Sono supportati: playlist, album e singoli brani."
    )


# ---------------------------------------------------------------------------
# Singolo brano
# ---------------------------------------------------------------------------

def get_track_info(token: str, track_id: str) -> tuple[str, list[dict]]:
    """Ritorna (track_name, [{"name": ..., "artist": ...}]) per un singolo brano."""
    resp = requests.get(
        f"https://api.spotify.com/v1/tracks/{track_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    name = data.get("name", "Unknown")
    artists = data.get("artists", [])
    artist = artists[0].get("name", "Unknown") if artists else "Unknown"
    return name, [{"name": name, "artist": artist}]


# ---------------------------------------------------------------------------
# Album
# ---------------------------------------------------------------------------

def get_album_info(token: str, album_id: str) -> tuple[str, list[dict]]:
    """Ritorna (album_name, lista tracce) per un album."""
    resp = requests.get(
        f"https://api.spotify.com/v1/albums/{album_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    album_name = data.get("name", "Unknown Album")

    tracks = []
    # Prima pagina inclusa nella risposta
    tracks_data = data.get("tracks", {})
    _collect_album_tracks(tracks_data, tracks)

    # Paginazione se ci sono piu di 50 tracce
    next_url = tracks_data.get("next")
    while next_url:
        resp = requests.get(
            next_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        page = resp.json()
        _collect_album_tracks(page, tracks)
        next_url = page.get("next")

    return album_name, tracks


def _collect_album_tracks(data: dict, out: list[dict]) -> None:
    for item in data.get("items", []):
        name = item.get("name", "Unknown")
        artists = item.get("artists", [])
        artist = artists[0].get("name", "Unknown") if artists else "Unknown"
        out.append({"name": name, "artist": artist})


# ---------------------------------------------------------------------------
# Playlist
# ---------------------------------------------------------------------------

def get_playlist_info(token: str, playlist_id: str) -> tuple[str, list[dict]]:
    """Ritorna (playlist_name, lista tracce) per una playlist."""
    resp = requests.get(
        f"https://api.spotify.com/v1/playlists/{playlist_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    name = data.get("name")
    if not name:
        raise ValueError("Impossibile leggere il nome della playlist")

    tracks = get_all_tracks(token, playlist_id)
    return name, tracks


def get_all_tracks(token: str, playlist_id: str) -> list[dict]:
    """Scarica tutte le tracce con paginazione (100 per pagina).

    Ritorna lista di {"name": ..., "artist": ...}.
    """
    tracks: list[dict] = []
    url: str | None = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=100&offset=0"

    while url:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            track = item.get("track")
            if not track:
                continue
            name = track.get("name", "Unknown")
            artists = track.get("artists", [])
            artist = artists[0].get("name", "Unknown") if artists else "Unknown"
            tracks.append({"name": name, "artist": artist})

        url = data.get("next")  # None quando non ci sono altre pagine

    return tracks


# ---------------------------------------------------------------------------
# Funzione unificata
# ---------------------------------------------------------------------------

def resolve_spotify_url(token: str, url: str) -> tuple[str, str, list[dict]]:
    """Risolve qualsiasi URL Spotify supportato.

    Ritorna (label, nome, lista_tracce) dove label e "Brano"/"Album"/"Playlist".
    """
    kind, item_id = detect_url_type(url)

    if kind == "track":
        name, tracks = get_track_info(token, item_id)
        return "Brano", name, tracks
    elif kind == "album":
        name, tracks = get_album_info(token, item_id)
        return "Album", name, tracks
    else:
        name, tracks = get_playlist_info(token, item_id)
        return "Playlist", name, tracks


# ---------------------------------------------------------------------------
# Fallback senza credenziali (solo per singoli brani)
# ---------------------------------------------------------------------------

class SpotifyAuthRequired(Exception):
    """Sollevata quando un URL Spotify richiede le API keys (album/playlist)."""


_OG_TITLE_RE = re.compile(
    r'<meta\s+property="og:title"\s+content="([^"]+)"', re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta\s+property="og:description"\s+content="([^"]+)"', re.IGNORECASE,
)
# Tag HTML entities che ci interessano nelle og: (Spotify le scrive cosi').
_HTML_ENTITIES = {
    "&amp;": "&", "&#x27;": "'", "&apos;": "'",
    "&quot;": '"', "&lt;": "<", "&gt;": ">",
}


def _decode_entities(s: str) -> str:
    for k, v in _HTML_ENTITIES.items():
        s = s.replace(k, v)
    return s


def resolve_spotify_track_no_auth(url: str) -> tuple[str, str, list[dict]]:
    """Estrae name/artist da un URL Spotify SENZA credenziali API.

    Funziona solo per brani singoli (open.spotify.com/track/<id>): legge
    i meta tag og:title e og:description della pagina pubblica.

    Per album/playlist non c'e' modo affidabile senza JS rendering -> alza
    SpotifyAuthRequired.

    Ritorna ("Brano", name, [{name, artist}]).
    """
    kind, _ = detect_url_type(url)
    if kind != "track":
        raise SpotifyAuthRequired(
            f"I link a {kind} richiedono le credenziali Spotify (gratuite). "
            "Vai in Impostazioni -> Spotify API per configurarle in 2 minuti."
        )

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (MusicTools)"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"Impossibile leggere il brano da Spotify: {e}") from e

    html = resp.text
    title_m = _OG_TITLE_RE.search(html)
    desc_m = _OG_DESC_RE.search(html)
    if not title_m:
        raise ValueError("Risposta inattesa da Spotify (meta og:title mancante).")

    name = _decode_entities(title_m.group(1)).strip()
    artist = ""
    if desc_m:
        # Formato osservato: "Artist Name · Song Title · Song · YYYY"
        # oppure con piu' artisti separati da ", ".
        parts = [_decode_entities(p).strip() for p in desc_m.group(1).split("·")]
        if parts:
            artist = parts[0]

    if not artist:
        raise ValueError(
            "Impossibile estrarre l'artista dal brano Spotify senza API keys. "
            "Configura le credenziali in Impostazioni."
        )

    track = {"name": name, "artist": artist}
    return "Brano", name, [track]


def search_track(token: str, query: str):
    """Cerca un brano su Spotify e ritorna il primo match.

    Ritorna un dict con {id, url, name, artists} oppure None se nessun match.
    Solleva requests.HTTPError su errori server / auth.
    """
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": query, "type": "track", "limit": 1},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("tracks", {}).get("items", [])
    if not items:
        return None
    t = items[0]
    return {
        "id": t.get("id"),
        "url": t.get("external_urls", {}).get("spotify", ""),
        "name": t.get("name", ""),
        "artists": ", ".join(a.get("name", "") for a in t.get("artists", [])),
    }


def search_tracks(token: str, query: str, limit: int = 50) -> list:
    """Cerca brani su Spotify e ritorna una lista di dict.

    Args:
        token: access token Spotify
        query: query libera (titolo, artista, misto)
        limit: max risultati (Spotify cap = 50)

    Returns:
        list[dict] con {id, url, name, artists, album, duration_sec}. Vuota se nessun match.
    """
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": query, "type": "track", "limit": min(limit, 50)},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("tracks", {}).get("items", [])
    return [_track_to_dict(t) for t in items]


def _track_to_dict(t: dict) -> dict:
    """Mappa il track object Spotify sul nostro schema uniforme."""
    return {
        "id": t.get("id", ""),
        "url": t.get("external_urls", {}).get("spotify", ""),
        "name": t.get("name", ""),
        "artists": ", ".join(a.get("name", "") for a in t.get("artists", [])),
        "album": t.get("album", {}).get("name", ""),
        "duration_sec": int(t.get("duration_ms", 0)) // 1000,
    }
