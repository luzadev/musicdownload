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
