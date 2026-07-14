# Music Search (Spotify + YouTube) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2 nuove tab in MusicTools ("🟢 Spotify" e "▶ YouTube") per cercare brani per titolo/artista e scaricarli. Spotify ha toggle "Solo artista" per discografia completa. YouTube è per mix DJ/unreleased/bootleg che Spotify non ha.

**Architecture:** Estensione `core/spotify_client.py` + nuovo `core/youtube_search.py` + 6 metodi in `api/bridge.py` + 2 tab UI in `webui/`. Riuso completo del pipeline download esistente (`start_tracks_download` per Spotify, nuovo `start_urls_download` per YouTube). Zero cambi server.

**Tech Stack:** Python 3.8+ (con `from __future__ import annotations`), `requests` (già in deps), `yt-dlp` via subprocess (già in bundle). `pytest` + `responses` + `unittest.mock` per test. Vanilla JS + HTML/CSS lato UI.

**Spec:** `docs/superpowers/specs/2026-07-14-music-search-design.md`

---

## Note operative

- **Branch:** `feat/music-search` (già creato, HEAD: `91aa1bd`)
- **Git author:** ogni commit deve usare `git -c user.email=info@djluza.com commit ...`
- **Test:** riusare pattern e infra dei test Beatport (`tests/`, `pytest`)
- **Python 3.8 compat:** ogni nuovo file `.py` inizia con `from __future__ import annotations`
- **Non toccare:** `server/`, `landing/`, `build_macos.py`, `build_windows.py`

---

## Task 1: `search_tracks(token, query, limit)` — TDD

**Files:**
- Modify: `core/spotify_client.py`
- Modify: `tests/test_spotify_client.py`

- [ ] **Step 1: Aggiungi test in `tests/test_spotify_client.py`**

Aggiungi in fondo al file:

```python
class TestSearchTracks:
    @responses.activate
    def test_returns_list_of_tracks(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={
                "tracks": {
                    "items": [
                        {
                            "id": f"id{i}",
                            "name": f"Track {i}",
                            "artists": [{"name": "Solomun"}],
                            "album": {"name": "Album X"},
                            "duration_ms": 300000 + i * 1000,
                            "external_urls": {"spotify": f"https://open.spotify.com/track/id{i}"},
                        }
                        for i in range(50)
                    ]
                }
            },
            status=200,
        )
        result = spotify_client.search_tracks("t", "solomun", limit=50)
        assert isinstance(result, list)
        assert len(result) == 50
        first = result[0]
        assert first["id"] == "id0"
        assert first["name"] == "Track 0"
        assert first["artists"] == "Solomun"
        assert first["album"] == "Album X"
        assert first["duration_sec"] == 300
        assert first["url"] == "https://open.spotify.com/track/id0"

    @responses.activate
    def test_multiple_artists_joined_with_comma(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": [{
                "id": "x", "name": "n",
                "artists": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
                "album": {"name": "Alb"},
                "duration_ms": 60000,
                "external_urls": {"spotify": "u"},
            }]}},
            status=200,
        )
        result = spotify_client.search_tracks("t", "q", limit=1)
        assert result[0]["artists"] == "A, B, C"

    @responses.activate
    def test_empty_query_returns_empty_list(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        result = spotify_client.search_tracks("t", "no-match", limit=50)
        assert result == []

    @responses.activate
    def test_query_params_include_limit(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        spotify_client.search_tracks("t", "q", limit=25)
        params = responses.calls[0].request.params
        assert params["q"] == "q"
        assert params["type"] == "track"
        assert params["limit"] == "25"
```

- [ ] **Step 2: Verifica fail**
Run: `python3 -m pytest tests/test_spotify_client.py::TestSearchTracks -v`
Expected: FAIL con `AttributeError: module 'core.spotify_client' has no attribute 'search_tracks'`

- [ ] **Step 3: Aggiungi `search_tracks` a `core/spotify_client.py`**

Aggiungi in fondo al file (dopo `search_track`):

```python
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
```

- [ ] **Step 4: Verifica**
Run: `python3 -m pytest tests/test_spotify_client.py -v`
Expected: 8 test PASS (4 existing + 4 new)

- [ ] **Step 5: Commit**
```bash
git add core/spotify_client.py tests/test_spotify_client.py
git -c user.email=info@djluza.com commit -m "spotify: search_tracks() free-form con limit configurabile"
```

---

## Task 2: `search_artist_discography(token, artist_name)` — TDD

**Files:**
- Modify: `core/spotify_client.py`
- Modify: `tests/test_spotify_client.py`

- [ ] **Step 1: Test in `tests/test_spotify_client.py`**

Aggiungi in fondo:

```python
class TestSearchArtistDiscography:
    @responses.activate
    def test_exact_name_match_beats_popular(self):
        # 3 candidati: uno esatto (case-insensitive), altri popolari
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [
                {"id": "pop", "name": "Solomun Tribute", "popularity": 90},
                {"id": "exact", "name": "SOLOMUN", "popularity": 60},
                {"id": "unrelated", "name": "Other", "popularity": 70},
            ]}},
            status=200,
        )
        # Mock top-tracks vuoto per non allungare il test
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/exact/top-tracks",
            json={"tracks": []},
            status=200,
        )
        # Mock albums vuoto
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/exact/albums",
            json={"items": []},
            status=200,
        )
        result = spotify_client.search_artist_discography("t", "Solomun")
        assert result == []
        # Verifica che sia stato chiamato l'artista "exact", non "pop"
        top_tracks_calls = [c for c in responses.calls if "/top-tracks" in c.request.url]
        assert len(top_tracks_calls) == 1
        assert "/exact/top-tracks" in top_tracks_calls[0].request.url

    @responses.activate
    def test_falls_back_to_most_popular_if_no_exact_match(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [
                {"id": "a1", "name": "Solomun Fanpage", "popularity": 30},
                {"id": "a2", "name": "Solomun Live", "popularity": 80},
            ]}},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/a2/top-tracks",
            json={"tracks": []},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/a2/albums",
            json={"items": []},
            status=200,
        )
        spotify_client.search_artist_discography("t", "solomun")
        top_tracks_calls = [c for c in responses.calls if "/top-tracks" in c.request.url]
        assert "/a2/top-tracks" in top_tracks_calls[0].request.url

    @responses.activate
    def test_raises_when_no_artist_found(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": []}},
            status=200,
        )
        with pytest.raises(ValueError, match="Artista"):
            spotify_client.search_artist_discography("t", "asdgjhkasdgj")

    @responses.activate
    def test_combines_top_tracks_and_album_tracks(self):
        # 1 artista esatto
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [{"id": "artX", "name": "artX", "popularity": 50}]}},
            status=200,
        )
        # 3 top-tracks
        top_tracks_data = {"tracks": [
            {
                "id": f"t{i}", "name": f"Top{i}",
                "artists": [{"name": "artX"}],
                "album": {"name": "AlbTop"},
                "duration_ms": 200000,
                "external_urls": {"spotify": f"u{i}"},
            } for i in range(3)
        ]}
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/artX/top-tracks",
            json=top_tracks_data,
            status=200,
        )
        # 2 album
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/artX/albums",
            json={"items": [
                {"id": "alb1", "name": "Album 1"},
                {"id": "alb2", "name": "Album 2"},
            ]},
            status=200,
        )
        # album 1: 2 tracce
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/albums/alb1/tracks",
            json={"items": [
                {
                    "id": f"a1t{i}", "name": f"Alb1Track{i}",
                    "artists": [{"name": "artX"}],
                    "duration_ms": 180000,
                    "external_urls": {"spotify": f"a1u{i}"},
                } for i in range(2)
            ]},
            status=200,
        )
        # album 2: 1 traccia
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/albums/alb2/tracks",
            json={"items": [
                {
                    "id": "a2t0", "name": "Alb2Track0",
                    "artists": [{"name": "artX"}],
                    "duration_ms": 240000,
                    "external_urls": {"spotify": "a2u0"},
                }
            ]},
            status=200,
        )
        with patch("core.spotify_client.time.sleep"):  # no wait
            result = spotify_client.search_artist_discography("t", "artX")
        # 3 top + 2 alb1 + 1 alb2 = 6
        assert len(result) == 6
        titles = {r["name"] for r in result}
        assert "Top0" in titles
        assert "Alb1Track0" in titles
        assert "Alb2Track0" in titles

    @responses.activate
    def test_dedupe_across_top_and_album(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [{"id": "aX", "name": "aX", "popularity": 50}]}},
            status=200,
        )
        # Stesso track name+artist in top-tracks e in album (id diverso)
        common = {
            "name": "Same Song",
            "artists": [{"name": "aX"}],
            "album": {"name": "OG Album"},
            "duration_ms": 200000,
            "external_urls": {"spotify": "u"},
        }
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/aX/top-tracks",
            json={"tracks": [{**common, "id": "top-id"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/aX/albums",
            json={"items": [{"id": "alb", "name": "OG"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/albums/alb/tracks",
            json={"items": [{**common, "id": "alb-id"}]},
            status=200,
        )
        with patch("core.spotify_client.time.sleep"):
            result = spotify_client.search_artist_discography("t", "aX")
        assert len(result) == 1
```

Aggiungi import in cima al file test (se non presente):
```python
from unittest.mock import patch
```

- [ ] **Step 2: Verifica fail**
Run: `python3 -m pytest tests/test_spotify_client.py::TestSearchArtistDiscography -v`
Expected: FAIL

- [ ] **Step 3: Implementa `search_artist_discography` in `core/spotify_client.py`**

Aggiungi in cima al file (se non presente):
```python
import time
```

Poi in fondo al file:

```python
def search_artist_discography(token: str, artist_name: str) -> list:
    """Trova l'artista esatto (o il più popolare tra i match) e ritorna
    tutti i suoi brani: top tracks + tracce di ogni album/single.
    Deduplica per (name.lower().strip(), first_artist.lower().strip()).

    Raises:
        ValueError: se nessun artista trovato per il nome dato.
    """
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Cerca artista
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        headers=headers,
        params={"q": artist_name, "type": "artist", "limit": 5},
        timeout=15,
    )
    resp.raise_for_status()
    candidates = resp.json().get("artists", {}).get("items", [])
    if not candidates:
        raise ValueError(f"Artista '{artist_name}' non trovato")

    # Match esatto (case-insensitive) se possibile, altrimenti più popolare
    query_lower = artist_name.lower().strip()
    exact = [c for c in candidates if c.get("name", "").lower().strip() == query_lower]
    if exact:
        artist = exact[0]
    else:
        artist = max(candidates, key=lambda c: c.get("popularity", 0))
    artist_id = artist["id"]

    collected: list = []

    # 2. Top tracks
    r_top = requests.get(
        f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks",
        headers=headers,
        params={"market": "IT"},
        timeout=15,
    )
    r_top.raise_for_status()
    for t in r_top.json().get("tracks", []):
        collected.append(_track_to_dict(t))

    # 3. Albums (album + single)
    r_alb = requests.get(
        f"https://api.spotify.com/v1/artists/{artist_id}/albums",
        headers=headers,
        params={"include_groups": "album,single", "limit": 50, "market": "IT"},
        timeout=15,
    )
    r_alb.raise_for_status()
    albums = r_alb.json().get("items", [])

    # 4. Per ogni album, tracce (album/track object non ha "album" sub-field,
    # gliela aggiungiamo esplicitamente)
    for alb in albums:
        alb_id = alb.get("id")
        alb_name = alb.get("name", "")
        if not alb_id:
            continue
        time.sleep(0.1)  # rate limit interno
        r_at = requests.get(
            f"https://api.spotify.com/v1/albums/{alb_id}/tracks",
            headers=headers,
            params={"limit": 50},
            timeout=15,
        )
        r_at.raise_for_status()
        for t in r_at.json().get("items", []):
            t = dict(t)
            # Album tracks non hanno "album" nested; iniettiamo il nome
            t.setdefault("album", {"name": alb_name})
            collected.append(_track_to_dict(t))

    # 5. Dedupe
    seen: set = set()
    unique: list = []
    for t in collected:
        key = (t["name"].lower().strip(), t["artists"].split(",")[0].lower().strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    return unique
```

- [ ] **Step 4: Verifica**
Run: `python3 -m pytest tests/test_spotify_client.py -v`
Expected: 13 test PASS (4 preesistenti + 4 search_tracks + 5 search_artist_discography)

- [ ] **Step 5: Commit**
```bash
git add core/spotify_client.py tests/test_spotify_client.py
git -c user.email=info@djluza.com commit -m "spotify: search_artist_discography con dedupe top-tracks+album"
```

---

## Task 3: `core/youtube_search.py` — TDD

**Files:**
- Create: `core/youtube_search.py`
- Create: `tests/test_youtube_search.py`

- [ ] **Step 1: Test in `tests/test_youtube_search.py`**

Crea il file:

```python
"""Test per core.youtube_search."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from core import youtube_search


def _mock_ytdlp_result(entries: list) -> MagicMock:
    """Mock subprocess.CompletedProcess con JSON stub."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({"entries": entries})
    result.stderr = ""
    return result


class TestSearchYoutube:
    def test_parses_entries(self):
        entries = [
            {
                "id": "abc123",
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "Kapuchon - Hot Sauce (Official Video)",
                "uploader": "Kapuchon Official",
                "duration": 336,
            },
            {
                "id": "def456",
                "url": "https://www.youtube.com/watch?v=def456",
                "title": "Solomun @ Cocoricò 2024",
                "uploader": "Cocoricò",
                "duration": 3600,
            },
        ]
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=_mock_ytdlp_result(entries)):
            result = youtube_search.search_youtube("kapuchon hot sauce", limit=50)
        assert len(result) == 2
        assert result[0]["title"] == "Kapuchon - Hot Sauce (Official Video)"
        assert result[0]["channel"] == "Kapuchon Official"
        assert result[0]["duration_sec"] == 336
        assert result[0]["url"] == "https://www.youtube.com/watch?v=abc123"

    def test_empty_entries_returns_empty(self):
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=_mock_ytdlp_result([])):
            result = youtube_search.search_youtube("no-match", limit=50)
        assert result == []

    def test_raises_when_ytdlp_missing(self):
        with patch("core.youtube_search.find_ytdlp", return_value=None):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                youtube_search.search_youtube("q", limit=50)

    def test_command_uses_ytsearch_with_limit(self):
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=_mock_ytdlp_result([])) as mock_run:
            youtube_search.search_youtube("solomun", limit=30)
        args = mock_run.call_args.args[0]  # positional list
        assert args[0] == "/fake/yt-dlp"
        # Trova l'argomento ytsearchN:query
        search_arg = [a for a in args if a.startswith("ytsearch")]
        assert search_arg == ["ytsearch30:solomun"]

    def test_timeout_raises_runtime_error(self):
        import subprocess as sp
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", side_effect=sp.TimeoutExpired("yt-dlp", 30)):
            with pytest.raises(RuntimeError, match="[Tt]imeout"):
                youtube_search.search_youtube("q", limit=50)

    def test_nonzero_exit_raises(self):
        bad = MagicMock()
        bad.returncode = 1
        bad.stdout = ""
        bad.stderr = "some yt-dlp error"
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=bad):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                youtube_search.search_youtube("q", limit=50)
```

- [ ] **Step 2: Verifica fail**
Run: `python3 -m pytest tests/test_youtube_search.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'core.youtube_search'`

- [ ] **Step 3: Implementa `core/youtube_search.py`**

Crea:

```python
"""Ricerca su YouTube via yt-dlp (subprocess, flat playlist metadata)."""

from __future__ import annotations

import json
import subprocess

from core.paths import find_ytdlp, subprocess_flags


_TIMEOUT_SEC = 30


def search_youtube(query: str, limit: int = 50) -> list:
    """Cerca su YouTube (ytsearchN:query) e ritorna metadata "flat" (senza scaricare).

    Args:
        query: testo di ricerca libero
        limit: numero massimo di risultati (default 50)

    Returns:
        list[dict] con {id, url, title, channel, duration_sec}. Vuota se nessun match.

    Raises:
        RuntimeError: se yt-dlp non disponibile, timeout, o exit non-zero.
    """
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise RuntimeError("yt-dlp non trovato nel bundle / PATH")

    cmd = [
        ytdlp,
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        f"ytsearch{limit}:{query}",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            **subprocess_flags(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Timeout ricerca YouTube ({_TIMEOUT_SEC}s)") from e

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"yt-dlp error: {' | '.join(tail) or 'unknown'}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"yt-dlp output non-JSON: {e}") from e

    entries = data.get("entries") or []
    result: list = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        video_id = e.get("id") or ""
        url = e.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        result.append({
            "id": video_id,
            "url": url,
            "title": e.get("title") or "",
            "channel": e.get("uploader") or e.get("channel") or "",
            "duration_sec": int(e.get("duration") or 0),
        })
    return result
```

**Nota:** `subprocess_flags()` è un helper esistente in `core/paths.py` che restituisce kwargs come `creationflags` su Windows per nascondere la console. Verifica: `grep subprocess_flags core/paths.py`. Se firma diversa, adatta.

- [ ] **Step 4: Verifica**
Run: `python3 -m pytest tests/test_youtube_search.py -v`
Expected: 6 test PASS

- [ ] **Step 5: Commit**
```bash
git add core/youtube_search.py tests/test_youtube_search.py
git -c user.email=info@djluza.com commit -m "youtube: search_youtube via yt-dlp ytsearchN + parse JSON"
```

---

## Task 4: Downloader supporto URL diretti + helper bridge

**Files:**
- Modify: `core/downloader.py` (potenzialmente — verifica prima)
- Modify: `api/bridge.py` (aggiunta helper)

- [ ] **Step 1: Verifica se `download_playlist` accetta già URL diretti**

Ispeziona `core/downloader.py`:
```bash
sed -n '118,200p' core/downloader.py
```

Cerca: la funzione fa `_search_youtube(query, ...)` per ogni track. Se accetta come input `[{url: "https://..."}]` e salta la search quando `url` è presente, riusiamo. Altrimenti dobbiamo aggiungere una funzione parallela.

- [ ] **Step 2A (se `download_playlist` NON supporta URL diretti): aggiungi `download_urls`**

In `core/downloader.py`, aggiungi in fondo:

```python
def download_urls(
    urls: list,
    titles: list,
    output_dir: str,
    bitrate: str = "320K",
    cookies_path: str = None,
    progress_callback=None,
) -> None:
    """Scarica direttamente da URL YouTube (bypassa search).

    Args:
        urls: lista URL YouTube (parallela a titles)
        titles: lista titoli video (per logging/dedupe)
        output_dir: cartella destinazione
        bitrate: qualita audio (default 320K)
        cookies_path: file cookies opzionale
        progress_callback: callback(idx, total, title, status, pct)
    """
    from pathlib import Path
    reset_stop()
    total = len(urls)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    done_file = out_path / ".downloaded_tracks"
    done_set = _load_done_set(done_file)
    ytdlp = find_ytdlp()

    for i, (url, title) in enumerate(zip(urls, titles)):
        if is_stopped():
            if progress_callback:
                progress_callback(i, total, "", "stopped", 0)
            return

        key = title or url
        if key in done_set:
            if progress_callback:
                progress_callback(i, total, key, "skipped", 100)
            continue

        if progress_callback:
            progress_callback(i, total, key, "downloading", 0)

        # Riusa la stessa logica di download del pipeline esistente
        # (chiama il worker download interno o replica i flag yt-dlp).
        # Vedi `_download_single_url` in questo file oppure la funzione
        # equivalente usata da download_playlist.
        try:
            _download_single_url(ytdlp, url, str(out_path), bitrate, cookies_path)
            _mark_done(done_file, key)
            if progress_callback:
                progress_callback(i, total, key, "done", 100)
        except Exception as e:
            if progress_callback:
                progress_callback(i, total, key, f"error: {e}", 0)

    if progress_callback:
        progress_callback(total, total, "", "completed", 100)
```

**Nota:** `_download_single_url` non esiste ancora — devi identificare la funzione interna che `download_playlist` chiama per il singolo download e (a) esporla come helper riusabile, oppure (b) estrarla in una nuova funzione. Ispeziona il corpo di `download_playlist` (righe 143+) per vedere il codice che va estratto.

**Alternativa più semplice:** invece di estrarre, chiama direttamente `subprocess.run([ytdlp, "-x", "--audio-format", "mp3", "--audio-quality", bitrate, "-o", <template>, url], ...)` con lo stesso set di flag usato da `download_playlist`. Copia i flag da lì.

- [ ] **Step 2B (se `download_playlist` supporta già URL diretti): salta Step 2A e passa a Step 3**

- [ ] **Step 3: Aggiungi helper `start_urls_download` a `api/bridge.py`**

Trova il metodo `start_tracks_download` (linea ~511) e aggiungi subito dopo:

```python
    def start_urls_download(self, payload: dict) -> dict:
        """Analogo a start_tracks_download ma accetta {urls, titles, output_dir, subfolder}.
        Usato dal flusso YouTube search (URL già noti, no search)."""
        if self._any_job_running():
            return {"ok": False, "error": "Un download gia in corso"}

        urls = payload.get("urls") or []
        titles = payload.get("titles") or []
        output_dir = (payload.get("output_dir") or "").strip()
        subfolder = (payload.get("subfolder") or "").strip()
        if not urls:
            return {"ok": False, "error": "Nessuna URL fornita"}
        if len(urls) != len(titles):
            return {"ok": False, "error": "urls e titles devono avere stessa lunghezza"}
        if not output_dir:
            return {"ok": False, "error": "Cartella output non impostata"}

        if subfolder:
            safe = subfolder.replace("/", "_").replace("\\", "_").strip()
            if safe:
                output_dir = os.path.join(output_dir, safe)

        gate = self._gate("audio")
        if gate:
            return gate

        self._download_thread = threading.Thread(
            target=self._urls_worker,
            args=(list(urls), list(titles), output_dir),
            daemon=True,
        )
        self._download_thread.start()
        return {"ok": True}

    def _urls_worker(self, urls: list, titles: list, output_dir: str) -> None:
        # Replica il pattern di _tracks_worker ma usa download_urls
        from core.downloader import download_urls
        reset_download_stop()
        cfg = load_config()
        bitrate = cfg.get("bitrate", "320K")
        cookies_path = cfg.get("cookies_path", "")
        view = "download"

        self._log(view, f"[INFO] URL list: {len(urls)} da scaricare da YouTube")
        self._log(view, f"[INFO] Destinazione: {output_dir}")

        _last = [0.0]
        _THROTTLE = 0.10

        def progress_cb(idx, total, title, status, pct):
            if status == "downloading":
                import time
                now = time.monotonic()
                if now - _last[0] < _THROTTLE:
                    return
                _last[0] = now

            payload_evt = {
                "idx": idx, "total": total, "track": title,
                "status": status, "pct": pct,
                "url_idx": 0, "url_total": 1,
            }
            if status == "searching":
                self._log(view, f"[CERCA] {title}")
            elif status == "skipped":
                self._log(view, f"[SKIP] {title} (gia scaricato)")
                payload_evt["overall"] = min((idx + 1) / total, 1.0) if total else 1
            elif status == "downloading":
                payload_evt["overall"] = min((idx / total) + (pct / 100 / total), 1.0) if total else 0
            elif status == "done":
                self._log(view, f"[OK] {title}")
                payload_evt["overall"] = min((idx + 1) / total, 1.0) if total else 1
            elif status == "stopped":
                self._log(view, "[INFO] Download interrotto.")
            elif status == "completed":
                payload_evt["overall"] = 1.0
                self._log(view, "[INFO] Download completato!")
            elif status.startswith("error"):
                self._log(view, f"[ERRORE] {title}: {status}")

            self._emit("download:progress", payload_evt)

        download_urls(urls, titles, output_dir, bitrate, cookies_path, progress_cb)
        self._emit("download:done", {"ok": True})
```

- [ ] **Step 4: Smoke test bridge**

```bash
python3 -c "from api.bridge import Api; a = Api(); print(a.start_urls_download({'urls':[],'titles':[],'output_dir':''}))"
```
Expected: `{'ok': False, 'error': 'Nessuna URL fornita'}` (validazione OK)

- [ ] **Step 5: Full regression**

Run: `python3 -m pytest tests/ -v`
Expected: 19 test PASS (4 spotify + 6 youtube_search + 9 nuovi search_tracks e discography)

Attenzione: il conto reale dipende dal totale Beatport già presente su questo branch — quindi conta i test come "nessuna regressione, tutti verdi".

- [ ] **Step 6: Commit**
```bash
git add core/downloader.py api/bridge.py
git -c user.email=info@djluza.com commit -m "downloader+bridge: supporto download da URL diretti (YouTube search flow)"
```

---

## Task 5: Config — VERSION v1.8.1 + 3 nuovi campi DEFAULTS

**Files:** `core/config.py`

- [ ] **Step 1: Bump VERSION**

In `core/config.py`, cambia:
```python
VERSION = "v1.8.0"
```
in:
```python
VERSION = "v1.8.1"
```

- [ ] **Step 2: Aggiungi 3 campi in DEFAULTS**

Trova il blocco `# ---- Beatport ----` e aggiungi subito dopo (prima di `# ---- Licenza ----`):

```python
    # ---- Music Search (Spotify + YouTube) ----
    "spotify_search_last_query": "",
    "spotify_search_artist_mode": False,
    "youtube_search_last_query": "",
```

- [ ] **Step 3: Verifica**
```bash
python3 -c "from core.config import load_config, VERSION; c = load_config(); print(VERSION, c.get('spotify_search_last_query',''), c.get('spotify_search_artist_mode'), c.get('youtube_search_last_query',''))"
```
Expected: `v1.8.1  False ` (i valori sono default)

- [ ] **Step 4: Commit**
```bash
git add core/config.py
git -c user.email=info@djluza.com commit -m "config: v1.8.1 + 3 campi DEFAULTS per music search"
```

---

## Task 6: `api/bridge.py` — 6 metodi Api per Spotify + YouTube

**Files:** `api/bridge.py`

- [ ] **Step 1: Ispeziona pattern esistente Beatport**

```bash
grep -n "beatport_" api/bridge.py | head -10
```

Nota il pattern usato da `beatport_genres`, `beatport_fetch_chart`, `beatport_check_existing`, `beatport_download_selected` — replichiamo il layout.

- [ ] **Step 2: Aggiungi in fondo a `class Api` (dopo i metodi Beatport)**

```python
    # ================================================================
    # Music Search — Spotify + YouTube
    # ================================================================

    def _music_output_dir(self, out_root: str, source: str) -> Path:
        """Cartella target per Spotify/YouTube search. Coerente col pattern
        `start_tracks_download` (subfolder singolo, no nested)."""
        safe = source.replace("/", "_").replace("\\", "_").strip()
        return Path(out_root) / safe

    # ---- Spotify ----

    def spotify_search(self, query: str, artist_mode: bool = False) -> dict:
        """Cerca su Spotify. Free-form (limit 50) o artist-mode (discografia)."""
        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "empty_query", "message": "Query vuota"}

        # Salva stato
        try:
            cfg = load_config()
            cfg["spotify_search_last_query"] = query
            cfg["spotify_search_artist_mode"] = bool(artist_mode)
            save_config(cfg)
        except Exception:
            pass

        cid = (load_config().get("client_id") or "").strip()
        secret = (load_config().get("client_secret") or "").strip()
        if not cid or not secret:
            return {"ok": False, "error": "no_creds", "message": "Credenziali Spotify mancanti"}

        try:
            token = spotify_client.get_access_token(cid, secret)
        except Exception as e:
            return {"ok": False, "error": "auth", "message": str(e)}

        try:
            if artist_mode:
                tracks = spotify_client.search_artist_discography(token, query)
            else:
                tracks = spotify_client.search_tracks(token, query, limit=50)
        except ValueError as e:
            return {"ok": False, "error": "artist_not_found", "message": str(e)}
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code == 429:
                return {"ok": False, "error": "rate_limit", "message": "Spotify limitante — attendi qualche secondo"}
            return {"ok": False, "error": "server", "message": f"Spotify HTTP {code}"}
        except Exception as e:
            return {"ok": False, "error": "unknown", "message": str(e)}

        return {"ok": True, "tracks": tracks}

    def spotify_check_existing(self, tracks: list) -> list:
        """True per ogni track già presente in output_dir/Spotify/."""
        cfg = load_config()
        out_root = (cfg.get("output_dir") or "").strip()
        if not out_root:
            return [False] * len(tracks)
        out_dir = self._music_output_dir(out_root, "Spotify")
        if not out_dir.exists():
            return [False] * len(tracks)
        existing_stems = [p.stem.lower() for p in out_dir.glob("*.mp3")]
        result = []
        for t in tracks:
            title = (t.get("name") or "").lower().strip()
            artists = (t.get("artists") or "")
            first_artist = artists.split(",")[0].strip().lower()
            if not title or not first_artist:
                result.append(False)
                continue
            result.append(any((title in stem and first_artist in stem) for stem in existing_stems))
        return result

    def spotify_search_download(self, tracks: list) -> dict:
        """Scarica i track Spotify selezionati (name+artist → YouTube search)."""
        cfg = load_config()
        out_root = (cfg.get("output_dir") or "").strip()
        if not out_root:
            return {"ok": False, "error": "Cartella output non impostata"}

        target = self._music_output_dir(out_root, "Spotify")
        subfolder = target.name

        converted = []
        for t in tracks:
            title = (t.get("name") or "").strip()
            artists = (t.get("artists") or "").strip()
            if not title:
                continue
            converted.append({"name": title, "artist": artists})

        if not converted:
            return {"ok": False, "error": "Nessun brano valido"}

        return self.start_tracks_download({
            "tracks": converted,
            "output_dir": out_root,
            "subfolder": subfolder,
        })

    # ---- YouTube ----

    def youtube_search(self, query: str) -> dict:
        """Cerca 50 risultati su YouTube via yt-dlp."""
        from core import youtube_search as yts

        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "empty_query", "message": "Query vuota"}

        try:
            cfg = load_config()
            cfg["youtube_search_last_query"] = query
            save_config(cfg)
        except Exception:
            pass

        try:
            results = yts.search_youtube(query, limit=50)
        except RuntimeError as e:
            return {"ok": False, "error": "ytdlp", "message": str(e)}
        except Exception as e:
            return {"ok": False, "error": "unknown", "message": str(e)}

        return {"ok": True, "tracks": results}

    def youtube_check_existing(self, tracks: list) -> list:
        """True per ogni track già presente in output_dir/YouTube/. Match sul titolo video."""
        cfg = load_config()
        out_root = (cfg.get("output_dir") or "").strip()
        if not out_root:
            return [False] * len(tracks)
        out_dir = self._music_output_dir(out_root, "YouTube")
        if not out_dir.exists():
            return [False] * len(tracks)
        existing_stems = [p.stem.lower() for p in out_dir.glob("*.mp3")]
        result = []
        for t in tracks:
            title = (t.get("title") or "").lower().strip()
            if not title:
                result.append(False)
                continue
            # Match: se il titolo del video è contenuto (o viceversa) in un filename esistente
            result.append(any(
                (title in stem or stem in title)
                for stem in existing_stems
            ))
        return result

    def youtube_search_download(self, tracks: list) -> dict:
        """Scarica direttamente gli URL YouTube selezionati (no re-search)."""
        cfg = load_config()
        out_root = (cfg.get("output_dir") or "").strip()
        if not out_root:
            return {"ok": False, "error": "Cartella output non impostata"}

        target = self._music_output_dir(out_root, "YouTube")
        subfolder = target.name

        urls: list = []
        titles: list = []
        for t in tracks:
            url = (t.get("url") or "").strip()
            title = (t.get("title") or "").strip()
            if not url or not title:
                continue
            urls.append(url)
            titles.append(title)

        if not urls:
            return {"ok": False, "error": "Nessun URL valido"}

        return self.start_urls_download({
            "urls": urls,
            "titles": titles,
            "output_dir": out_root,
            "subfolder": subfolder,
        })
```

Verifica gli import in cima al file: `spotify_client`, `requests` — devono essere già presenti. Se `requests` manca, aggiungilo. Se `spotify_client` è importato come `from core import spotify_client` verifica coerenza.

- [ ] **Step 3: Smoke test**
```bash
python3 -c "
from api.bridge import Api
a = Api()
print('spotify_search empty:', a.spotify_search(''))
print('youtube_search empty:', a.youtube_search(''))
print('spotify_check empty tracks:', a.spotify_check_existing([]))
print('youtube_check empty tracks:', a.youtube_check_existing([]))
"
```
Expected: gli errori `empty_query` per le search, `[]` per check_existing.

- [ ] **Step 4: Full pytest**
Run: `python3 -m pytest tests/ -v`
Expected: nessuna regressione, tutti verdi.

- [ ] **Step 5: Commit**
```bash
git add api/bridge.py
git -c user.email=info@djluza.com commit -m "bridge: 6 metodi Api per music search (Spotify + YouTube)"
```

---

## Task 7: UI — 2 nuove tab (HTML + JS + CSS) in un unico blocco

Combinato Task 7-9 dello spec in un unico task perché tutto UI, stesso pattern del `BeatportUI`.

**Files:**
- Modify: `webui/index.html`
- Modify: `webui/js/app.js`
- Modify: `webui/css/style.css`

- [ ] **Step 1: Recon rapido pattern esistente Beatport**

```bash
grep -n 'data-view="beatport"\|view-beatport\|BeatportUI' webui/index.html webui/js/app.js | head -20
```

Il subagent Beatport ha usato: `.nav-item[data-view="beatport"][data-feature="audio"]`, `<section id="view-beatport" class="view">`, modulo `BeatportUI` in JS con `init/loadChart/renderTable/updateSelectionCount/startDownload`. Replica lo stesso pattern per `spotify` e `youtube`.

- [ ] **Step 2: HTML — nuove nav-item + 2 sezioni**

In `webui/index.html`, dopo il `nav-item` di Beatport (`data-view="beatport"`), aggiungi:

```html
<a class="nav-item" data-view="spotify" data-feature="audio" href="#">
  <span class="ico">🟢</span><span>Spotify</span>
</a>
<a class="nav-item" data-view="youtube" data-feature="audio" href="#">
  <span class="ico">▶</span><span>YouTube</span>
</a>
```

Dopo `<section id="view-beatport">...</section>`, aggiungi:

```html
<section id="view-spotify" class="view">
  <div class="hero hero-indigo">
    <div class="hero-content">
      <span class="hero-eyebrow indigo">RICERCA SPOTIFY</span>
      <h1>Cerca brani su Spotify</h1>
      <p>Digita un artista, un titolo, o entrambi. Attiva "Solo artista" per scaricare tutta la discografia.</p>
    </div>
  </div>

  <section class="card">
    <div class="beatport-header">
      <input type="text" id="spotify-query" class="input pill" placeholder="Es: Solomun, Hot Sauce, Kapuchon Hot Sauce…" style="flex:1"/>
      <label style="display:flex;gap:6px;align-items:center;">
        <input type="checkbox" id="spotify-artist-mode"/>
        <span>Solo artista</span>
      </label>
      <button id="spotify-search-btn" class="btn btn-primary pill">🔎 Cerca</button>
    </div>
    <div id="spotify-output-info" class="beatport-output-info"></div>
    <div id="spotify-status" class="beatport-status"></div>

    <div class="beatport-table-card" id="spotify-table-wrap" hidden>
      <table class="beatport-table" id="spotify-table">
        <thead><tr>
          <th class="col-check"><input type="checkbox" id="spotify-select-all" checked/></th>
          <th class="col-pos">#</th>
          <th>Artista</th>
          <th>Titolo</th>
          <th>Album</th>
          <th class="col-dur">Durata</th>
          <th class="col-state"></th>
        </tr></thead>
        <tbody id="spotify-tbody"></tbody>
      </table>
    </div>

    <div class="beatport-toolbar" id="spotify-toolbar" hidden>
      <span class="counter" id="spotify-selected-count">0/0 selezionati</span>
      <button id="spotify-download-btn" class="btn btn-primary pill" disabled>⬇ Scarica selezionati</button>
      <button id="spotify-stop-btn" class="btn btn-danger pill" hidden>■ Interrompi</button>
    </div>
  </section>

  <section class="log-card">
    <div class="section-label">LOG</div>
    <div id="spotify-log" class="log"></div>
  </section>
</section>

<section id="view-youtube" class="view">
  <div class="hero hero-indigo">
    <div class="hero-content">
      <span class="hero-eyebrow indigo">RICERCA YOUTUBE</span>
      <h1>Cerca video su YouTube</h1>
      <p>Perfetto per mix DJ, unreleased, bootleg e brani non presenti su Spotify.</p>
    </div>
  </div>

  <section class="card">
    <div class="beatport-header">
      <input type="text" id="youtube-query" class="input pill" placeholder="Es: Solomun Cocoricò 2024, Kapuchon Hot Sauce remix…" style="flex:1"/>
      <button id="youtube-search-btn" class="btn btn-primary pill">🔎 Cerca</button>
    </div>
    <div id="youtube-output-info" class="beatport-output-info"></div>
    <div id="youtube-status" class="beatport-status"></div>

    <div class="beatport-table-card" id="youtube-table-wrap" hidden>
      <table class="beatport-table" id="youtube-table">
        <thead><tr>
          <th class="col-check"><input type="checkbox" id="youtube-select-all" checked/></th>
          <th class="col-pos">#</th>
          <th>Titolo video</th>
          <th>Canale</th>
          <th class="col-dur">Durata</th>
          <th class="col-state"></th>
        </tr></thead>
        <tbody id="youtube-tbody"></tbody>
      </table>
    </div>

    <div class="beatport-toolbar" id="youtube-toolbar" hidden>
      <span class="counter" id="youtube-selected-count">0/0 selezionati</span>
      <button id="youtube-download-btn" class="btn btn-primary pill" disabled>⬇ Scarica selezionati</button>
      <button id="youtube-stop-btn" class="btn btn-danger pill" hidden>■ Interrompi</button>
    </div>
  </section>

  <section class="log-card">
    <div class="section-label">LOG</div>
    <div id="youtube-log" class="log"></div>
  </section>
</section>
```

Adatta le classi CSS se il subagent Beatport ha usato nomi leggermente diversi (`beatport-table-card` vs `beatport-table-wrap`) — controlla il markup esistente.

- [ ] **Step 3: JS — moduli SpotifyUI e YoutubeUI in `webui/js/app.js`**

Dopo `BeatportUI`, aggiungi (in fondo, prima del bootstrap `// Boot`):

```javascript
// =====================================================================
// Spotify search
// =====================================================================
const SpotifyUI = (() => {
  const state = { tracks: [], existing: [], downloading: false };

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  }

  function _fmtDuration(sec) {
    const m = Math.floor((sec || 0) / 60), s = (sec || 0) % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function updateSelectionCount() {
    const boxes = document.querySelectorAll("#spotify-tbody input[type=checkbox]");
    const total = boxes.length;
    const selected = [...boxes].filter(b => b.checked).length;
    document.getElementById("spotify-selected-count").textContent = `${selected}/${total} selezionati`;
    const btn = document.getElementById("spotify-download-btn");
    btn.disabled = selected === 0;
    btn.textContent = `⬇ Scarica selezionati (${selected})`;
    const sa = document.getElementById("spotify-select-all");
    sa.checked = selected === total && total > 0;
    sa.indeterminate = selected > 0 && selected < total;
  }

  function renderTable() {
    const tbody = document.getElementById("spotify-tbody");
    tbody.innerHTML = "";
    state.tracks.forEach((t, i) => {
      const already = state.existing[i];
      const tr = document.createElement("tr");
      tr.dataset.idx = i;
      if (already) tr.classList.add("already-downloaded");
      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" data-idx="${i}" ${already ? "" : "checked"}/></td>
        <td class="col-pos">${i + 1}</td>
        <td>${_escape(t.artists)}</td>
        <td>${_escape(t.name)}</td>
        <td>${_escape(t.album)}</td>
        <td class="col-dur">${_fmtDuration(t.duration_sec)}</td>
        <td class="col-state">${already ? "<span style='color:var(--green)'>✓ scaricato</span>" : ""}</td>
      `;
      tr.querySelector("input[type=checkbox]").addEventListener("change", updateSelectionCount);
      tbody.appendChild(tr);
    });
    updateSelectionCount();
  }

  async function doSearch() {
    const q = document.getElementById("spotify-query").value.trim();
    if (!q) return;
    const artistMode = document.getElementById("spotify-artist-mode").checked;
    const status = document.getElementById("spotify-status");
    const wrap = document.getElementById("spotify-table-wrap");
    const toolbar = document.getElementById("spotify-toolbar");
    status.textContent = "Ricerca in corso…";
    status.className = "beatport-status loading";
    wrap.hidden = true;
    toolbar.hidden = true;

    let res;
    try {
      res = await window.pywebview.api.spotify_search(q, artistMode);
    } catch (e) {
      status.textContent = `Errore: ${e}`;
      status.className = "beatport-status error";
      return;
    }
    if (!res.ok) {
      const messages = {
        empty_query: "Inserisci una query di ricerca.",
        no_creds: "Credenziali Spotify mancanti. Vai su Impostazioni.",
        auth: "Impossibile autenticarsi con Spotify. Verifica le credenziali.",
        artist_not_found: res.message,
        rate_limit: res.message,
        server: res.message,
      };
      status.textContent = messages[res.error] || res.message || "Errore sconosciuto";
      status.className = "beatport-status error";
      return;
    }

    state.tracks = res.tracks || [];
    if (state.tracks.length === 0) {
      status.textContent = `Nessun brano trovato per "${q}".`;
      status.className = "beatport-status";
      return;
    }
    try {
      state.existing = await window.pywebview.api.spotify_check_existing(state.tracks);
    } catch { state.existing = state.tracks.map(() => false); }

    status.textContent = "";
    document.getElementById("spotify-output-info").textContent = "Cartella output: MUSICA/Spotify/";
    renderTable();
    wrap.hidden = false;
    toolbar.hidden = false;
  }

  async function startDownload() {
    const selected = [...document.querySelectorAll("#spotify-tbody input[type=checkbox]:checked")]
      .map(b => state.tracks[parseInt(b.dataset.idx)]);
    if (!selected.length) return;

    state.downloading = true;
    document.getElementById("spotify-download-btn").disabled = true;
    document.getElementById("spotify-stop-btn").hidden = false;
    document.getElementById("spotify-log").innerHTML = "";

    try {
      await window.pywebview.api.spotify_search_download(selected);
    } catch (e) {
      appendLog("spotify", `Errore: ${e}`);
    }
  }

  async function stopDownload() {
    try { await window.pywebview.api.stop_download(); } catch {}
  }

  async function init() {
    const cfg = state?.config || (window.state?.config) || {};
    try {
      const q = cfg.spotify_search_last_query;
      const am = cfg.spotify_search_artist_mode;
      if (q) document.getElementById("spotify-query").value = q;
      if (am) document.getElementById("spotify-artist-mode").checked = true;
    } catch { /* ignora */ }

    document.getElementById("spotify-search-btn").addEventListener("click", doSearch);
    document.getElementById("spotify-query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch();
    });
    document.getElementById("spotify-select-all").addEventListener("change", (e) => {
      document.querySelectorAll("#spotify-tbody input[type=checkbox]").forEach(b => b.checked = e.target.checked);
      updateSelectionCount();
    });
    document.getElementById("spotify-download-btn").addEventListener("click", startDownload);
    document.getElementById("spotify-stop-btn").addEventListener("click", stopDownload);

    // Wrap bridge handlers per mostrare log/progress su questa tab durante download
    const origLog = bridgeHandlers["log"];
    bridgeHandlers["log"] = (payload) => {
      if (origLog) origLog(payload);
      if (state.downloading && payload?.view === "download") {
        appendLog("spotify", payload.msg);
      }
    };
    const origDone = bridgeHandlers["download:done"];
    bridgeHandlers["download:done"] = (payload) => {
      if (origDone) origDone(payload);
      if (state.downloading) {
        state.downloading = false;
        document.getElementById("spotify-download-btn").disabled = false;
        document.getElementById("spotify-stop-btn").hidden = true;
        // Refresh existing
        window.pywebview.api.spotify_check_existing(state.tracks).then(r => {
          state.existing = r;
          renderTable();
        }).catch(() => {});
      }
    };
  }

  return { init };
})();

// =====================================================================
// YouTube search
// =====================================================================
const YoutubeUI = (() => {
  const state = { tracks: [], existing: [], downloading: false };

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  }
  function _fmtDuration(sec) {
    const m = Math.floor((sec || 0) / 60), s = (sec || 0) % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  function updateSelectionCount() {
    const boxes = document.querySelectorAll("#youtube-tbody input[type=checkbox]");
    const total = boxes.length;
    const selected = [...boxes].filter(b => b.checked).length;
    document.getElementById("youtube-selected-count").textContent = `${selected}/${total} selezionati`;
    const btn = document.getElementById("youtube-download-btn");
    btn.disabled = selected === 0;
    btn.textContent = `⬇ Scarica selezionati (${selected})`;
    const sa = document.getElementById("youtube-select-all");
    sa.checked = selected === total && total > 0;
    sa.indeterminate = selected > 0 && selected < total;
  }
  function renderTable() {
    const tbody = document.getElementById("youtube-tbody");
    tbody.innerHTML = "";
    state.tracks.forEach((t, i) => {
      const already = state.existing[i];
      const tr = document.createElement("tr");
      tr.dataset.idx = i;
      if (already) tr.classList.add("already-downloaded");
      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" data-idx="${i}" ${already ? "" : "checked"}/></td>
        <td class="col-pos">${i + 1}</td>
        <td>${_escape(t.title)}</td>
        <td>${_escape(t.channel)}</td>
        <td class="col-dur">${_fmtDuration(t.duration_sec)}</td>
        <td class="col-state">${already ? "<span style='color:var(--green)'>✓ scaricato</span>" : ""}</td>
      `;
      tr.querySelector("input[type=checkbox]").addEventListener("change", updateSelectionCount);
      tbody.appendChild(tr);
    });
    updateSelectionCount();
  }
  async function doSearch() {
    const q = document.getElementById("youtube-query").value.trim();
    if (!q) return;
    const status = document.getElementById("youtube-status");
    const wrap = document.getElementById("youtube-table-wrap");
    const toolbar = document.getElementById("youtube-toolbar");
    status.textContent = "Ricerca su YouTube in corso…";
    status.className = "beatport-status loading";
    wrap.hidden = true;
    toolbar.hidden = true;

    let res;
    try { res = await window.pywebview.api.youtube_search(q); }
    catch (e) { status.textContent = `Errore: ${e}`; status.className = "beatport-status error"; return; }

    if (!res.ok) {
      status.textContent = res.message || "Errore sconosciuto";
      status.className = "beatport-status error";
      return;
    }
    state.tracks = res.tracks || [];
    if (state.tracks.length === 0) {
      status.textContent = `Nessun video trovato per "${q}".`;
      status.className = "beatport-status";
      return;
    }
    try { state.existing = await window.pywebview.api.youtube_check_existing(state.tracks); }
    catch { state.existing = state.tracks.map(() => false); }

    status.textContent = "";
    document.getElementById("youtube-output-info").textContent = "Cartella output: MUSICA/YouTube/";
    renderTable();
    wrap.hidden = false;
    toolbar.hidden = false;
  }
  async function startDownload() {
    const selected = [...document.querySelectorAll("#youtube-tbody input[type=checkbox]:checked")]
      .map(b => state.tracks[parseInt(b.dataset.idx)]);
    if (!selected.length) return;
    state.downloading = true;
    document.getElementById("youtube-download-btn").disabled = true;
    document.getElementById("youtube-stop-btn").hidden = false;
    document.getElementById("youtube-log").innerHTML = "";
    try { await window.pywebview.api.youtube_search_download(selected); }
    catch (e) { appendLog("youtube", `Errore: ${e}`); }
  }
  async function stopDownload() {
    try { await window.pywebview.api.stop_download(); } catch {}
  }
  async function init() {
    const cfg = state?.config || (window.state?.config) || {};
    try {
      const q = cfg.youtube_search_last_query;
      if (q) document.getElementById("youtube-query").value = q;
    } catch { /* ignora */ }

    document.getElementById("youtube-search-btn").addEventListener("click", doSearch);
    document.getElementById("youtube-query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch();
    });
    document.getElementById("youtube-select-all").addEventListener("change", (e) => {
      document.querySelectorAll("#youtube-tbody input[type=checkbox]").forEach(b => b.checked = e.target.checked);
      updateSelectionCount();
    });
    document.getElementById("youtube-download-btn").addEventListener("click", startDownload);
    document.getElementById("youtube-stop-btn").addEventListener("click", stopDownload);

    const origLog = bridgeHandlers["log"];
    bridgeHandlers["log"] = (payload) => {
      if (origLog) origLog(payload);
      if (state.downloading && payload?.view === "download") {
        appendLog("youtube", payload.msg);
      }
    };
    const origDone = bridgeHandlers["download:done"];
    bridgeHandlers["download:done"] = (payload) => {
      if (origDone) origDone(payload);
      if (state.downloading) {
        state.downloading = false;
        document.getElementById("youtube-download-btn").disabled = false;
        document.getElementById("youtube-stop-btn").hidden = true;
        window.pywebview.api.youtube_check_existing(state.tracks).then(r => {
          state.existing = r;
          renderTable();
        }).catch(() => {});
      }
    };
  }
  return { init };
})();
```

- [ ] **Step 4: Registra `logEls` per le nuove tab**

Cerca in `app.js` la mappa `logEls = { download: ..., video: ..., upgrade: ... }` (probabile linea ~250-300). Aggiungi:

```javascript
  spotify: document.getElementById("spotify-log"),
  youtube: document.getElementById("youtube-log"),
```

Verifica che `appendLog("spotify", msg)` e `appendLog("youtube", msg)` funzionino grazie a questa registrazione.

- [ ] **Step 5: Aggancia le init al bootstrap**

Trova dove `await BeatportUI.init();` è chiamato in fondo alla funzione `init()` del bootstrap, e aggiungi subito dopo:

```javascript
  await SpotifyUI.init();
  await YoutubeUI.init();
```

- [ ] **Step 6: CSS — piccole estensioni in `webui/css/style.css`**

Le classi Beatport (`.beatport-header`, `.beatport-table`, `.beatport-toolbar`, `.beatport-status`, ecc.) sono riusate — non serve aggiungere CSS a meno che qualche cosa non renda bene. Verifica visivamente.

Se serve una differenziazione visiva (es. barra colore per Spotify verde, YouTube rosso), aggiungi variant classes. Optional per v1.8.1.

- [ ] **Step 7: Verifiche pre-commit**

```bash
node --check webui/js/app.js  # syntax check
python3 -m pytest tests/ -v   # no regression
python3 -c "from api.bridge import Api; a=Api(); print(a.spotify_search(''))"
```

- [ ] **Step 8: Commit (3 separati per pulizia)**
```bash
git add webui/index.html
git -c user.email=info@djluza.com commit -m "ui: markup tab Spotify + YouTube search"

git add webui/js/app.js
git -c user.email=info@djluza.com commit -m "ui: SpotifyUI + YoutubeUI (search, table, download, log)"

# CSS solo se hai aggiunto qualcosa
git status webui/css/ >/dev/null 2>&1 && [ -n "$(git diff --name-only webui/css/)" ] && {
  git add webui/css/*.css
  git -c user.email=info@djluza.com commit -m "ui: piccole estensioni CSS per tab Spotify+YouTube"
}
```

---

## Task 8: Manual test + release notes + tag + push + server DB update

**Files:** `/tmp/notes-v1.8.1.md`

- [ ] **Step 1: Full test suite finale**
```bash
python3 -m pytest tests/ -v
```
Expected: tutti verdi, zero regressioni.

- [ ] **Step 2: Test manuale end-to-end**

Segui la spec sez. "Test manuale end-to-end". 12 casi in tutto (6 Spotify + 5 YouTube + 1 riavvio).

Se qualcosa fallisce: BLOCKED, torna al task pertinente.

- [ ] **Step 3: Note release**

Crea `/tmp/notes-v1.8.1.md`:

```markdown
# MusicTools v1.8.1

## Novità

**Nuove tab Spotify e YouTube 🔎** — cerca brani per titolo o artista.

- **Spotify:** cerca brani via API ufficiale. Toggle "Solo artista" per ottenere tutta la discografia (top tracks + tutti gli album/single, deduplicati).
- **YouTube:** cerca video via yt-dlp (fino a 50 risultati). Perfetto per mix DJ, unreleased, bootleg e brani non presenti su Spotify.
- Entrambe le tab hanno anteprima con checkbox e riconoscimento file già scaricati.
- File in `MUSICA/Spotify/` e `MUSICA/YouTube/`.

## Bug fix

Nessuno in questa release.
```

- [ ] **Step 4: Merge + tag + push**
```bash
git checkout main
git merge --no-ff feat/music-search -m "Merge feat/music-search: MusicTools v1.8.1"
# Se l'autore risulta sbagliato:
git -c user.email=info@djluza.com commit --amend --author="luciano <info@djluza.com>" --no-edit
git tag v1.8.1
git push origin main
git push origin v1.8.1
```

- [ ] **Step 5: Monitor CI + apply release notes**
```bash
# Trova il databaseId del run appena partito
RUN_ID=$(gh run list --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status && gh release edit v1.8.1 --notes-file /tmp/notes-v1.8.1.md
```

- [ ] **Step 6: Popola server `releases` table**

```bash
mkdir -p /tmp/release-v1.8.1
gh release download v1.8.1 -D /tmp/release-v1.8.1
cd /tmp/release-v1.8.1
MAC_SHA=$(shasum -a 256 MusicTools-macOS.dmg | awk '{print $1}')
WIN_SHA=$(shasum -a 256 MusicTools-Windows.zip | awk '{print $1}')
MAC_SIZE=$(stat -f %z MusicTools-macOS.dmg)
WIN_SIZE=$(stat -f %z MusicTools-Windows.zip)

ssh musictools@musictools.djluza.com "mkdir -p ~/builds/v1.8.1"
scp MusicTools-macOS.dmg MusicTools-Windows.zip musictools@musictools.djluza.com:~/builds/v1.8.1/

ssh musictools@musictools.djluza.com "cd ~/api && node -e '
import(\"node:fs\").then(({ default: fs }) => {
  fs.readFileSync(\".env\", \"utf-8\").split(\"\n\").forEach((l) => {
    const m = l.match(/^([A-Z_]+)=(.*)\$/);
    if (m) process.env[m[1]] = m[2];
  });
  import(\"./src/db.js\").then(async ({ query }) => {
    const notes = \"Nuove tab Spotify e YouTube per cercare brani per titolo o artista. Toggle solo artista su Spotify per scaricare tutta la discografia.\";
    const now = Math.floor(Date.now()/1000);
    await query(\"INSERT INTO releases (version, platform, file_path, size_bytes, sha256, notes, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)\",
      [\"v1.8.1\", \"macos\", \"v1.8.1/MusicTools-macOS.dmg\", ${MAC_SIZE}, \"${MAC_SHA}\", notes, now]);
    await query(\"INSERT INTO releases (version, platform, file_path, size_bytes, sha256, notes, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)\",
      [\"v1.8.1\", \"windows\", \"v1.8.1/MusicTools-Windows.zip\", ${WIN_SIZE}, \"${WIN_SHA}\", notes, now]);
    console.log(\"inserted 2 rows\");
    process.exit(0);
  });
});
'"

rm -rf /tmp/release-v1.8.1
```

- [ ] **Step 7: Verifica endpoint update**
```bash
curl -s "https://musictools.djluza.com/api/latest?platform=macos&current=v1.7.15" | python3 -m json.tool
```
Expected: `"version": "v1.8.1"`

---

## Riepilogo test attesi

- `tests/test_spotify_client.py`: **13 test** (4 pre-esistenti + 4 search_tracks + 5 search_artist_discography)
- `tests/test_youtube_search.py`: **6 test** (nuovi)
- `tests/test_beatport.py`: invariato (21 test)
- **Totale:** 40 test verdi
- Test manuali end-to-end passati

## Se qualcosa va storto

- **Spotify rate limit su artist mode** (troppi album chiamati): aumenta `time.sleep(0.1)` a 0.2s in `search_artist_discography`
- **yt-dlp lento** (`ytsearch50:` timeout 30s): abbassa `limit` a 25 o alza `_TIMEOUT_SEC` a 60
- **subprocess_flags() firma diversa da `**kwargs`**: adatta in `search_youtube` (potrebbe essere un dict standalone o un decorator)
- **`start_urls_download` conflitto con `_any_job_running`**: se avvii un download YouTube mentre uno Spotify è in corso, blocca. Corretto — è il comportamento voluto (un solo download attivo alla volta).
