# Beatport Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungi una tab "🎧 Beatport" a MusicTools che carica le Top 100 per genere dal sito Beatport, permette selezione via checkbox e scarica i brani riusando il downloader esistente (Spotify search → yt-dlp → .mp3).

**Architecture:** Nuovo modulo `core/beatport.py` (parser stateless con cache in-memory), 4 nuovi metodi in `main.py` (bridge JS↔Python via pywebview), nuova sezione UI in `webui/`. Parsing dati Beatport via estrazione JSON `__NEXT_DATA__` embeddato in ogni pagina Next.js. Zero cambi lato server, zero migration.

**Tech Stack:** Python 3.11+, `requests`, `re`, `json`, `dataclasses`, `pathlib` (già in requirements). `pytest` + `responses` come nuove dev-deps. Frontend: vanilla JS + HTML/CSS (nessun framework, coerente col resto dell'app).

**Spec di riferimento:** `docs/superpowers/specs/2026-07-14-beatport-charts-design.md`

---

## Note operative

- **Author email git:** usa `git -c user.email=info@djluza.com commit …` per ogni commit di questo piano (non modificare il config globale)
- **Branch:** lavora su `feat/beatport-charts` per isolare. `git checkout -b feat/beatport-charts` prima della Task 0
- **Framework di test:** questo repo non ha ancora `tests/`. Le Task 0 e 1 lo impostano
- **Non modificare** `server/`, `landing/`, `build_macos.py`, `build_windows.py` — questa feature è additive lato client
- **⚠ Cloudflare:** Beatport è dietro Cloudflare Managed Challenge — `requests` puro riceve 403. La feature usa **`curl_cffi`** (TLS fingerprint impersonation di Chrome) che bypassa CF. Verificato funzionante il 2026-07-14 con `impersonate="chrome131"` → HTTP 200, ~885KB, `__NEXT_DATA__` presente. Task 1 e 6 sono aggiornate di conseguenza.

---

## Task 0: Setup branch, tests dir, dev dependencies

**Files:**
- Create: `tests/__init__.py` (vuoto)
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Crea branch**

```bash
cd /Users/luciano/Downloads/Progetti2026/MusicDownload
git checkout -b feat/beatport-charts
```

- [ ] **Step 2: Aggiungi test deps a requirements.txt**

Aggiungi in fondo al file:

```
# --- dev only ---
pytest>=8.0.0
responses>=0.25.0
freezegun>=1.4.0
```

- [ ] **Step 3: Installa deps**

Run: `python3 -m pip install -r requirements.txt`
Expected: pytest, responses, freezegun installati senza errori

- [ ] **Step 4: Crea tests/__init__.py vuoto**

```bash
mkdir -p tests/fixtures
touch tests/__init__.py
```

- [ ] **Step 5: Crea tests/conftest.py**

```python
"""Fixtures pytest condivise."""
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
```

- [ ] **Step 6: Verifica pytest gira (0 test)**

Run: `python3 -m pytest tests/ -v`
Expected: `no tests ran in 0.XXs`, exit code 5 (nessun test) — è ok

- [ ] **Step 7: Commit**

```bash
git add tests/__init__.py tests/conftest.py requirements.txt
git -c user.email=info@djluza.com commit -m "test: setup pytest infra per feature Beatport"
```

---

## Task 1: HTML fixture reale + genres list script

**Files:**
- Create: `scripts/refresh_beatport_genres.py`
- Create: `tests/fixtures/beatport_melodic_top100.html`
- Modify: `requirements.txt` (aggiungi `curl_cffi>=0.9.0` come runtime dep)

- [ ] **Step 0: Aggiungi `curl_cffi` a requirements.txt come runtime dep**

Beatport è dietro Cloudflare Managed Challenge — `requests` puro riceve 403. Serve `curl_cffi` che impersona il TLS fingerprint di Chrome.

Modifica `requirements.txt` — aggiungi prima del blocco `# --- dev only ---`:

```
curl_cffi>=0.9.0
```

Installa: `python3 -m pip install -r requirements.txt`

- [ ] **Step 1: Scarica una pagina Beatport reale come fixture (via curl_cffi)**

```bash
python3 -c "
from curl_cffi import requests
r = requests.get(
    'https://www.beatport.com/genre/melodic-house-techno/90/top-100',
    impersonate='chrome131',
    timeout=15,
)
assert r.status_code == 200, f'HTTP {r.status_code}'
with open('tests/fixtures/beatport_melodic_top100.html', 'w') as f:
    f.write(r.text)
print('saved', len(r.text), 'bytes')
"
```

Verifica: `ls -la tests/fixtures/beatport_melodic_top100.html` → file > 500KB (atteso ~885KB).
Se è < 100KB o lo script fallisce: **STOP e chiedi supporto** (potrebbe essere cambiata la protezione CF).

- [ ] **Step 2: Verifica che `__NEXT_DATA__` sia presente**

Run: `grep -c '__NEXT_DATA__' tests/fixtures/beatport_melodic_top100.html`
Expected: `1` (esattamente un match)

Se `0`: pagina non è Next.js-served (Beatport ha cambiato tech). Interrompi e chiedi conferma design.

- [ ] **Step 3: Ispeziona lo schema JSON (una tantum, non automatizzato)**

```bash
python3 -c "
import re, json
html = open('tests/fixtures/beatport_melodic_top100.html').read()
m = re.search(r'<script id=\"__NEXT_DATA__\"[^>]*>(.+?)</script>', html, re.DOTALL)
data = json.loads(m.group(1))
# Naviga: props > pageProps > dehydratedState > queries > [i] > state > data > results
queries = data['props']['pageProps']['dehydratedState']['queries']
for i, q in enumerate(queries):
    d = q.get('state', {}).get('data', {})
    if isinstance(d, dict) and 'results' in d:
        results = d['results']
        if isinstance(results, list) and len(results) >= 50:
            print(f'queries[{i}]: {len(results)} results')
            print('  sample keys:', list(results[0].keys())[:15])
"
```

Aspettato output tipo:
```
queries[N]: 100 results
  sample keys: ['id', 'name', 'mix_name', 'artists', 'length_ms', 'chart_position', ...]
```

Se le chiavi non sono `id`, `name`, `mix_name`, `artists`, `length_ms` (o simili): adatta i selettori nelle Task 4-5 di conseguenza — annotali qui prima di proseguire.

- [ ] **Step 4: Crea script per enumerare i generi (opzionale, run manuale)**

```python
# scripts/refresh_beatport_genres.py
"""Estrae lo slug + numeric id di tutti i generi Beatport dalla pagina indice.
Uso: python3 scripts/refresh_beatport_genres.py > /tmp/genres.txt
Poi copia manualmente in core/beatport.py::GENRES."""

from __future__ import annotations

import re
import json
import sys
from curl_cffi import requests


def main() -> int:
    resp = requests.get(
        "https://www.beatport.com/genres",
        impersonate="chrome131",
        timeout=15,
    )
    resp.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL)
    if not m:
        print("__NEXT_DATA__ non trovato", file=sys.stderr)
        return 1
    data = json.loads(m.group(1))
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    for q in queries:
        d = q.get("state", {}).get("data", {})
        if isinstance(d, dict) and "results" in d and isinstance(d["results"], list):
            for g in d["results"]:
                if "slug" in g and "id" in g and "name" in g:
                    print(f'    "{g["slug"]}": ({g["id"]}, "{g["name"]}"),')
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Genera la mappa completa dei generi**

```bash
mkdir -p scripts
# crea il file dal blocco sopra
python3 scripts/refresh_beatport_genres.py > /tmp/genres_output.txt
head -5 /tmp/genres_output.txt
wc -l /tmp/genres_output.txt
```

Expected: ~30 righe nel formato `    "slug": (id, "Name"),`. Salva questo output — servirà nella Task 2.

Se lo script fallisce (bot detection): usa manualmente per ora la lista parziale nel Task 2 e apri issue separato per completarla.

- [ ] **Step 6: Commit**

```bash
git add scripts/refresh_beatport_genres.py tests/fixtures/beatport_melodic_top100.html
git -c user.email=info@djluza.com commit -m "beatport: fixture HTML per test + script refresh generi"
```

---

## Task 2: GENRES map + list_genres() — TDD

**Files:**
- Create: `core/beatport.py`
- Create: `tests/test_beatport.py`

- [ ] **Step 1: Scrivi test per list_genres()**

Crea `tests/test_beatport.py`:

```python
"""Test per core.beatport."""

import pytest

from core import beatport


class TestListGenres:
    def test_returns_list_of_dicts(self):
        result = beatport.list_genres()
        assert isinstance(result, list)
        assert len(result) >= 10  # almeno 10 generi
        for g in result:
            assert set(g.keys()) == {"slug", "id", "name"}
            assert isinstance(g["slug"], str) and g["slug"]
            assert isinstance(g["id"], int) and g["id"] > 0
            assert isinstance(g["name"], str) and g["name"]

    def test_sorted_alphabetically_by_name(self):
        result = beatport.list_genres()
        names = [g["name"] for g in result]
        assert names == sorted(names, key=str.casefold)

    def test_melodic_house_techno_present(self):
        result = beatport.list_genres()
        slugs = [g["slug"] for g in result]
        assert "melodic-house-techno" in slugs
```

- [ ] **Step 2: Verifica che i test falliscano**

Run: `python3 -m pytest tests/test_beatport.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'core.beatport'`

- [ ] **Step 3: Implementa core/beatport.py minimo**

```python
"""Fetch Top 100 Beatport per genere.

Approccio: estrai il JSON `__NEXT_DATA__` dal HTML della pagina Next.js.
Vedi docs/superpowers/specs/2026-07-14-beatport-charts-design.md.
"""

from __future__ import annotations


# Mappa slug URL Beatport → (numeric_id, display_name)
# Enumerata via scripts/refresh_beatport_genres.py (vedi Task 1).
# Sostituisci il blocco qui sotto con l'output completo di quello script.
GENRES: dict[str, tuple[int, str]] = {
    "afro-house": (89, "Afro House"),
    "deep-house": (12, "Deep House"),
    "drum-bass": (1, "Drum & Bass"),
    "dubstep": (18, "Dubstep"),
    "house": (5, "House"),
    "indie-dance": (37, "Indie Dance"),
    "melodic-house-techno": (90, "Melodic House & Techno"),
    "minimal-deep-tech": (14, "Minimal / Deep Tech"),
    "organic-house-downtempo": (93, "Organic House / Downtempo"),
    "progressive-house": (15, "Progressive House"),
    "tech-house": (11, "Tech House"),
    "techno-peak-time-driving": (6, "Techno (Peak Time / Driving)"),
    "techno-raw-deep-hypnotic": (92, "Techno (Raw / Deep / Hypnotic)"),
    "trance": (7, "Trance"),
}


def list_genres() -> list[dict]:
    """Ritorna [{slug, id, name}, ...] ordinato alfabeticamente per name."""
    result = [
        {"slug": slug, "id": gid, "name": name}
        for slug, (gid, name) in GENRES.items()
    ]
    result.sort(key=lambda g: g["name"].casefold())
    return result
```

**Se hai la lista completa dallo script della Task 1:** sostituisci il blocco `GENRES = {…}` con l'output completo. Il test `test_returns_list_of_dicts` accetta ≥10 generi, quindi la lista parziale sopra è già valida.

- [ ] **Step 4: Verifica test passano**

Run: `python3 -m pytest tests/test_beatport.py -v`
Expected: 3 test PASS

- [ ] **Step 5: Commit**

```bash
git add core/beatport.py tests/test_beatport.py
git -c user.email=info@djluza.com commit -m "beatport: GENRES + list_genres() con test"
```

---

## Task 3: BeatportTrack dataclass — TDD

**Files:**
- Modify: `core/beatport.py`
- Modify: `tests/test_beatport.py`

- [ ] **Step 1: Aggiungi test per BeatportTrack**

Aggiungi in fondo a `tests/test_beatport.py`:

```python
class TestBeatportTrack:
    def test_display_format(self):
        t = beatport.BeatportTrack(
            position=1,
            title="Hot Sauce",
            mix="Extended",
            artists="Kapuchon, Miss Monique & GLZ",
            duration_sec=336,
            beatport_id=12345,
        )
        assert t.display == "Kapuchon, Miss Monique & GLZ – Hot Sauce (Extended) (5:36)"

    def test_display_pads_seconds(self):
        t = beatport.BeatportTrack(
            position=1, title="X", mix="Y", artists="A",
            duration_sec=65, beatport_id=1,
        )
        assert t.display.endswith("(1:05)")

    def test_spotify_query(self):
        t = beatport.BeatportTrack(
            position=1,
            title="Hot Sauce",
            mix="Extended",
            artists="Kapuchon, Miss Monique & GLZ",
            duration_sec=336,
            beatport_id=12345,
        )
        assert t.spotify_query == "Kapuchon, Miss Monique & GLZ Hot Sauce"

    def test_is_frozen(self):
        t = beatport.BeatportTrack(
            position=1, title="X", mix="Y", artists="A",
            duration_sec=1, beatport_id=1,
        )
        with pytest.raises(Exception):
            t.title = "Z"  # frozen=True impedisce mutazione
```

- [ ] **Step 2: Verifica fail**

Run: `python3 -m pytest tests/test_beatport.py::TestBeatportTrack -v`
Expected: FAIL con `AttributeError: module 'core.beatport' has no attribute 'BeatportTrack'`

- [ ] **Step 3: Aggiungi la dataclass a core/beatport.py**

In cima a `core/beatport.py`, prima di `GENRES`, aggiungi:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class BeatportTrack:
    position: int
    title: str
    mix: str          # es. "Extended Mix", "Original Mix", ""
    artists: str      # es. "A, B & C" già formattato
    duration_sec: int
    beatport_id: int

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
```

- [ ] **Step 4: Verifica test passano**

Run: `python3 -m pytest tests/test_beatport.py -v`
Expected: 7 test PASS

- [ ] **Step 5: Commit**

```bash
git add core/beatport.py tests/test_beatport.py
git -c user.email=info@djluza.com commit -m "beatport: BeatportTrack dataclass con display + spotify_query"
```

---

## Task 4: Estrazione `__NEXT_DATA__` + eccezioni — TDD

**Files:**
- Modify: `core/beatport.py`
- Modify: `tests/test_beatport.py`

- [ ] **Step 1: Aggiungi test per parser interno**

Aggiungi in fondo a `tests/test_beatport.py`:

```python
class TestExtractNextData:
    def test_extracts_json_from_valid_html(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        data = beatport._extract_next_data(html)
        assert isinstance(data, dict)
        assert "props" in data

    def test_missing_script_raises(self):
        with pytest.raises(beatport.BeatportParseError, match="__NEXT_DATA__ non trovato"):
            beatport._extract_next_data("<html><body>nulla</body></html>")

    def test_malformed_json_raises(self):
        broken = '<script id="__NEXT_DATA__" type="application/json">{not: valid}</script>'
        with pytest.raises(beatport.BeatportParseError, match="JSON malformato"):
            beatport._extract_next_data(broken)
```

- [ ] **Step 2: Verifica fail**

Run: `python3 -m pytest tests/test_beatport.py::TestExtractNextData -v`
Expected: FAIL

- [ ] **Step 3: Implementa eccezioni + `_extract_next_data`**

Aggiungi a `core/beatport.py` (dopo gli import):

```python
import json
import re


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
```

- [ ] **Step 4: Verifica test passano**

Run: `python3 -m pytest tests/test_beatport.py -v`
Expected: 10 test PASS

- [ ] **Step 5: Commit**

```bash
git add core/beatport.py tests/test_beatport.py
git -c user.email=info@djluza.com commit -m "beatport: estrazione __NEXT_DATA__ + eccezioni tipizzate"
```

---

## Task 5: Walk JSON → list[BeatportTrack] — TDD

**Files:**
- Modify: `core/beatport.py`
- Modify: `tests/test_beatport.py`

- [ ] **Step 1: Aggiungi test parser tracce**

⚠️ **Prima di scrivere questo test rileggi l'output della Task 1 Step 3** — le chiavi effettive del JSON Beatport potrebbero differire. Il test qui sotto assume `id`, `name`, `mix_name`, `artists` (list of `{name}`), `length_ms`. Se sono diverse, adatta sia il test che l'implementazione coerentemente.

Aggiungi in fondo a `tests/test_beatport.py`:

```python
class TestParseTracks:
    def test_extracts_100_tracks(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        data = beatport._extract_next_data(html)
        tracks = beatport._parse_tracks(data)
        assert len(tracks) == 100

    def test_positions_are_sequential_1_to_100(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        tracks = beatport._parse_tracks(beatport._extract_next_data(html))
        positions = [t.position for t in tracks]
        assert positions == list(range(1, 101))

    def test_track_shape(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        tracks = beatport._parse_tracks(beatport._extract_next_data(html))
        first = tracks[0]
        assert isinstance(first, beatport.BeatportTrack)
        assert first.title
        assert first.artists
        assert first.duration_sec > 0
        assert first.beatport_id > 0

    def test_schema_missing_results_raises(self):
        with pytest.raises(beatport.BeatportParseError, match="results"):
            beatport._parse_tracks({"props": {"pageProps": {}}})
```

- [ ] **Step 2: Verifica fail**

Run: `python3 -m pytest tests/test_beatport.py::TestParseTracks -v`
Expected: FAIL

- [ ] **Step 3: Implementa `_parse_tracks`**

Aggiungi a `core/beatport.py`:

```python
def _find_tracks_results(data: dict) -> list[dict]:
    """Cerca dentro le queries dehydrated il primo `results` che ha almeno 50 elementi
    e la shape di una track (chiave `id` presente)."""
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError) as e:
        raise BeatportParseError(f"schema JSON inatteso (queries mancanti): {e}") from e

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


def _parse_tracks(data: dict) -> list[BeatportTrack]:
    """Trasforma i track dict di Beatport in BeatportTrack ordinati per posizione."""
    raw = _find_tracks_results(data)
    out: list[BeatportTrack] = []
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
            )
        except (TypeError, ValueError) as e:
            raise BeatportParseError(f"track[{i}] shape inattesa: {e}") from e
        out.append(track)
    return out
```

**Se le chiavi effettive del JSON (visto in Task 1 Step 3) sono diverse:** adatta `item.get("name")`, `item.get("mix_name")`, `item.get("artists")`, `item.get("length_ms")`, `item.get("id")` di conseguenza.

- [ ] **Step 4: Verifica test passano**

Run: `python3 -m pytest tests/test_beatport.py -v`
Expected: 14 test PASS

Se `test_track_shape` fallisce con `duration_sec == 0`: la chiave della durata non è `length_ms` — controlla nell'output Task 1 Step 3 e correggi.

- [ ] **Step 5: Commit**

```bash
git add core/beatport.py tests/test_beatport.py
git -c user.email=info@djluza.com commit -m "beatport: parse JSON → list[BeatportTrack]"
```

---

## Task 6: fetch_top100 con HTTP, retry, cache — TDD

**Files:**
- Modify: `core/beatport.py`
- Modify: `tests/test_beatport.py`

- [ ] **Step 1: Aggiungi test per fetch_top100 (mock su curl_cffi)**

`responses` non funziona con `curl_cffi` — usa `unittest.mock.patch` sul modulo importato.

Aggiungi in fondo a `tests/test_beatport.py`:

```python
from unittest.mock import patch, MagicMock

from freezegun import freeze_time


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    def _raise():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")
    resp.raise_for_status = _raise
    return resp


class TestFetchTop100:
    @pytest.fixture
    def fixture_html(self, fixtures_dir):
        return (fixtures_dir / "beatport_melodic_top100.html").read_text()

    def test_success_returns_100_tracks(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            tracks = beatport.fetch_top100("melodic-house-techno")
        assert len(tracks) == 100

    def test_invalid_slug_raises_value_error(self):
        with pytest.raises(ValueError, match="slug"):
            beatport.fetch_top100("not-a-real-genre")

    def test_5xx_retries_and_raises_unreachable(self):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response("", 503)
            with patch("core.beatport.time.sleep"):  # skip backoff nei test
                with pytest.raises(beatport.BeatportUnreachableError):
                    beatport.fetch_top100("melodic-house-techno")
            assert mock_get.call_count == 3  # 1 + 2 retry

    def test_cache_hit_within_ttl(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            beatport.fetch_top100("melodic-house-techno")
            beatport.fetch_top100("melodic-house-techno")
            assert mock_get.call_count == 1  # seconda call servita da cache

    def test_cache_expires_after_ttl(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            with freeze_time("2026-01-01 10:00:00") as frozen:
                beatport.fetch_top100("melodic-house-techno")
                frozen.tick(delta=beatport._CACHE_TTL_SEC + 1)
                beatport.fetch_top100("melodic-house-techno")
            assert mock_get.call_count == 2

    def test_force_refresh_bypasses_cache(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            beatport.fetch_top100("melodic-house-techno")
            beatport.fetch_top100("melodic-house-techno", force_refresh=True)
            assert mock_get.call_count == 2

    def test_uses_chrome_impersonation(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            beatport.fetch_top100("melodic-house-techno")
            # verifica che venga passato impersonate="chrome..."
            call_kwargs = mock_get.call_args.kwargs
            assert "impersonate" in call_kwargs
            assert call_kwargs["impersonate"].startswith("chrome")
```

- [ ] **Step 2: Verifica fail**

Run: `python3 -m pytest tests/test_beatport.py::TestFetchTop100 -v`
Expected: FAIL

- [ ] **Step 3: Implementa fetch_top100 + cache + retry (via curl_cffi)**

Aggiungi a `core/beatport.py`:

```python
import time

# curl_cffi bypassa Cloudflare Managed Challenge tramite TLS impersonation.
# Import aliased così i test possono fare patch("core.beatport._cffi_requests.get").
from curl_cffi import requests as _cffi_requests


_IMPERSONATE = "chrome131"  # aggiorna se CF rompe il fingerprint
_REQUEST_TIMEOUT = 15
_MAX_ATTEMPTS = 3
_BACKOFF_SEC = [1, 3]  # attese fra tentativo 1→2 e 2→3
_CACHE_TTL_SEC = 15 * 60

# Cache in-memory: slug → (timestamp_epoch, list[BeatportTrack])
_cache: dict[str, tuple[float, list[BeatportTrack]]] = {}


def _url_for(slug: str) -> str:
    gid, _ = GENRES[slug]
    return f"https://www.beatport.com/genre/{slug}/{gid}/top-100"


def _do_get(url: str) -> str:
    """GET con retry e backoff. Solleva BeatportUnreachableError su fallimento definitivo."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = _cffi_requests.get(
                url,
                impersonate=_IMPERSONATE,
                timeout=_REQUEST_TIMEOUT,
            )
            if resp.status_code >= 500 or resp.status_code == 403:
                # 403 = Cloudflare challenge non superata → retry
                raise Exception(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SEC[attempt])
    raise BeatportUnreachableError(f"Beatport irraggiungibile dopo {_MAX_ATTEMPTS} tentativi: {last_exc}")


def fetch_top100(slug: str, force_refresh: bool = False) -> list[BeatportTrack]:
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
```

- [ ] **Step 4: Verifica test passano**

Run: `python3 -m pytest tests/test_beatport.py -v`
Expected: 21 test PASS

Nota: il test `test_5xx_retries_and_raises_unreachable` fa 3 richieste con backoff 1s+3s → dura ~4s. Ok.

- [ ] **Step 5: Commit**

```bash
git add core/beatport.py tests/test_beatport.py
git -c user.email=info@djluza.com commit -m "beatport: fetch_top100 con HTTP + retry + cache 15min"
```

---

## Task 7: Aggiungi search_track() a spotify_client.py — TDD

**Files:**
- Modify: `core/spotify_client.py`
- Create: `tests/test_spotify_client.py`

Il modulo `core/spotify_client.py` esiste ma **non ha** una funzione `search_track()` pubblica. La aggiungiamo.

- [ ] **Step 1: Scrivi test per search_track**

Crea `tests/test_spotify_client.py`:

```python
"""Test per core.spotify_client.search_track()."""

import pytest
import responses

from core import spotify_client


class TestSearchTrack:
    @responses.activate
    def test_returns_track_dict_when_found(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={
                "tracks": {
                    "items": [
                        {
                            "id": "abc123",
                            "name": "Hot Sauce",
                            "artists": [{"name": "Kapuchon"}],
                            "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
                        }
                    ]
                }
            },
            status=200,
        )
        result = spotify_client.search_track("fake-token", "Kapuchon Hot Sauce")
        assert result is not None
        assert result["id"] == "abc123"
        assert result["url"] == "https://open.spotify.com/track/abc123"

    @responses.activate
    def test_returns_none_when_no_results(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        result = spotify_client.search_track("fake-token", "no-match")
        assert result is None

    @responses.activate
    def test_sends_bearer_token(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        spotify_client.search_track("my-token", "q")
        assert responses.calls[0].request.headers["Authorization"] == "Bearer my-token"

    @responses.activate
    def test_query_params_correct(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        spotify_client.search_track("t", "Kapuchon Hot Sauce")
        params = responses.calls[0].request.params
        assert params["q"] == "Kapuchon Hot Sauce"
        assert params["type"] == "track"
        assert params["limit"] == "1"
```

- [ ] **Step 2: Verifica fail**

Run: `python3 -m pytest tests/test_spotify_client.py -v`
Expected: FAIL con `AttributeError: module 'core.spotify_client' has no attribute 'search_track'`

- [ ] **Step 3: Aggiungi search_track a core/spotify_client.py**

Aggiungi in fondo a `core/spotify_client.py`:

```python
def search_track(token: str, query: str) -> dict | None:
    """Cerca un brano su Spotify e ritorna il primo match.

    Ritorna un dict con almeno {id, url, name, artists} oppure None se nessun match.
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
```

- [ ] **Step 4: Verifica test passano**

Run: `python3 -m pytest tests/test_spotify_client.py -v`
Expected: 4 test PASS

- [ ] **Step 5: Commit**

```bash
git add core/spotify_client.py tests/test_spotify_client.py
git -c user.email=info@djluza.com commit -m "spotify: aggiunto search_track() per feature Beatport"
```

---

## Task 8: Config — nuovo campo beatport_last_genre + version bump

**Files:**
- Modify: `core/config.py`

- [ ] **Step 1: Aggiungi campo ai DEFAULTS + version bump**

Modifica `core/config.py`:

Cambia:
```python
VERSION = "v1.7.15"
```
in:
```python
VERSION = "v1.8.0"
```

Nel dict `DEFAULTS`, dopo `"theme": "dark",` aggiungi:
```python
    # ---- Beatport ----
    "beatport_last_genre": "melodic-house-techno",  # ultimo genere Top 100 caricato
```

- [ ] **Step 2: Verifica carica di default**

```bash
python3 -c "from core.config import load_config; print(load_config()['beatport_last_genre'])"
```
Expected: `melodic-house-techno` (o il valore già in config.json se lo hai già)

- [ ] **Step 3: Commit**

```bash
git add core/config.py
git -c user.email=info@djluza.com commit -m "config: v1.8.0 + beatport_last_genre nei DEFAULTS"
```

---

## Task 9: main.py — nuovi metodi Api per bridge JS↔Python

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Ispeziona la classe Api esistente**

Run: `grep -n "class Api\|def [a-z]" main.py | head -40`

Individua dove si definiscono i metodi esposti a JS (probabile `class Api:` o `class WebviewApi:`), come vengono emessi i log/progress al frontend, e come funziona il pattern di stop.

Annota qui:
- Nome classe API: ______
- Metodo per emettere log al JS: ______ (es. `self.window.evaluate_js(...)` o simile)
- Come viene passata `output_dir`: ______

- [ ] **Step 2: Aggiungi import in cima a main.py**

```python
from dataclasses import asdict
from pathlib import Path

from core import beatport, spotify_client
```

Se `beatport` e `spotify_client` sono già importati diversamente (es. `from core.spotify_client import get_access_token`), aggiungili senza duplicare.

- [ ] **Step 3: Aggiungi metodo beatport_genres**

Nella classe Api, aggiungi:

```python
    def beatport_genres(self) -> list[dict]:
        """Ritorna la lista dei generi disponibili per il dropdown."""
        return beatport.list_genres()
```

- [ ] **Step 4: Aggiungi metodo beatport_fetch_chart**

```python
    def beatport_fetch_chart(self, slug: str, force_refresh: bool = False) -> dict:
        """Fetches la Top 100 per il genere. Ritorna {ok, tracks} o {ok:False, error, message}."""
        # Salva ultimo genere per la prossima apertura
        try:
            cfg = load_config()
            cfg["beatport_last_genre"] = slug
            save_config(cfg)
        except Exception:
            pass  # non bloccare per errori di salvataggio config

        try:
            tracks = beatport.fetch_top100(slug, force_refresh=force_refresh)
        except ValueError as e:
            return {"ok": False, "error": "invalid_genre", "message": str(e)}
        except beatport.BeatportUnreachableError as e:
            return {"ok": False, "error": "unreachable", "message": str(e)}
        except beatport.BeatportParseError as e:
            return {"ok": False, "error": "parse", "message": str(e)}

        return {"ok": True, "tracks": [asdict(t) for t in tracks]}
```

`load_config` e `save_config` sono già importati da `core.config` — verifica.

- [ ] **Step 5: Aggiungi metodo beatport_check_existing**

```python
    def beatport_check_existing(self, tracks: list[dict], genre_name: str) -> list[bool]:
        """Per ogni track ritorna True se esiste già un file .mp3 corrispondente
        nella cartella output di quel genere."""
        cfg = load_config()
        out_dir = Path(cfg["output_dir"]) / "Beatport" / genre_name
        if not out_dir.exists():
            return [False] * len(tracks)

        # Usa lo stesso naming del downloader esistente: "Artista - Titolo.mp3"
        # (verifica il pattern reale ispezionando core/downloader.py)
        existing = {p.stem for p in out_dir.glob("*.mp3")}
        result = []
        for t in tracks:
            expected_stem = f"{t['artists']} - {t['title']}"
            # Match esatto o fuzzy prefisso (il downloader può aggiungere " (Extended)" ecc.)
            found = any(expected_stem in name or name.startswith(expected_stem) for name in existing)
            result.append(found)
        return result
```

**Nota:** l'esatto naming pattern lo produce il downloader esistente. Verifica in `core/downloader.py` come si chiamano i file di output (potrebbe usare `%(title)s` di yt-dlp). Se diverso, adatta `expected_stem`.

- [ ] **Step 6: Aggiungi metodo beatport_download_selected**

```python
    def beatport_download_selected(self, tracks: list[dict], genre_name: str) -> None:
        """Scarica i brani selezionati riusando il flusso Spotify search → downloader."""
        from core import downloader  # locale per evitare circular imports

        cfg = load_config()
        out_dir = Path(cfg["output_dir"]) / "Beatport" / genre_name
        out_dir.mkdir(parents=True, exist_ok=True)

        client_id = cfg.get("client_id", "").strip()
        client_secret = cfg.get("client_secret", "").strip()
        if not client_id or not client_secret:
            self._emit_log("✗ Credenziali Spotify mancanti — vai su Impostazioni")
            return

        try:
            token = spotify_client.get_access_token(client_id, client_secret)
        except Exception as e:
            self._emit_log(f"✗ Errore auth Spotify: {e}")
            return

        downloader.reset_stop()
        total = len(tracks)
        for i, t in enumerate(tracks, 1):
            if downloader._stop_event.is_set():
                self._emit_log(f"[{i}/{total}] Interrotto dall'utente")
                return

            query = f"{t['artists']} {t['title']}"
            self._emit_log(f"[{i}/{total}] Cerco su Spotify: {query}")
            try:
                found = spotify_client.search_track(token, query)
            except Exception as e:
                self._emit_log(f"[{i}/{total}] ✗ Errore Spotify: {e}")
                continue

            if not found:
                self._emit_log(f"[{i}/{total}] ✗ Non trovato su Spotify")
                continue

            self._emit_log(f"[{i}/{total}] Download da YouTube: {found['name']}")
            try:
                downloader.download_from_spotify_url(  # nome esatto lo verifichi
                    found["url"],
                    output_dir=str(out_dir),
                    on_progress=self._emit_progress,
                )
                self._emit_log(f"[{i}/{total}] ✓ {t['title']}")
            except Exception as e:
                self._emit_log(f"[{i}/{total}] ✗ Download fallito: {e}")
```

**⚠️ Da adattare:**
- `self._emit_log(...)` e `self._emit_progress(...)`: sostituisci coi metodi reali usati dagli altri tab per pushare log/progress al JS (visti nella Task 9 Step 1)
- `downloader.download_from_spotify_url(...)`: sostituisci con il nome effettivo della funzione pubblica del downloader (ispeziona `core/downloader.py`)

- [ ] **Step 7: Smoke test manuale del bridge**

Avvia l'app e apri la console browser (menu View del webview):

```javascript
window.pywebview.api.beatport_genres().then(console.log)
```
Expected: array di 14+ oggetti `{slug, id, name}`

```javascript
window.pywebview.api.beatport_fetch_chart("melodic-house-techno").then(console.log)
```
Expected: `{ok: true, tracks: [ … 100 oggetti … ]}`

Se fallisce: leggi il messaggio, sistema il metodo Python, riavvia l'app.

- [ ] **Step 8: Commit**

```bash
git add main.py
git -c user.email=info@djluza.com commit -m "main: 4 metodi Api per feature Beatport"
```

---

## Task 10: UI — HTML tab + section

**Files:**
- Modify: `webui/index.html`

- [ ] **Step 1: Trova la tab bar e i pattern esistenti**

Run: `grep -n 'data-tab\|class=".*tab' webui/index.html | head -30`

Individua:
- La `<nav>` o `<div>` con i pulsanti tab
- Il pattern per una `<section class="tab-panel">`
- Le classi CSS usate per il layout dei bottoni download / progress log

- [ ] **Step 2: Aggiungi bottone tab**

Trova la nav tab bar e aggiungi (nello stesso stile degli altri):

```html
<button class="tab-btn" data-tab="beatport">🎧 Beatport</button>
```

L'ordine: mettilo dopo la tab "Video" o dove ha più senso nel flow.

- [ ] **Step 3: Aggiungi la section del pannello**

Aggiungi in fondo alle altre `<section class="tab-panel">` (adatta le classi CSS ai pattern esistenti):

```html
<section id="tab-beatport" class="tab-panel" hidden>
  <div class="beatport-header">
    <label>
      Genere:
      <select id="beatport-genre"></select>
    </label>
    <button id="beatport-load-btn" class="btn btn-primary">Carica Top 100</button>
    <small class="beatport-hint">Shift+click su "Carica" per forzare il refresh (ignora cache 15 min).</small>
  </div>

  <div id="beatport-status" class="beatport-status"></div>

  <div id="beatport-output-info" class="beatport-output-info"></div>

  <table id="beatport-table" class="beatport-table" hidden>
    <thead>
      <tr>
        <th class="col-check"><input type="checkbox" id="beatport-select-all" checked></th>
        <th class="col-pos">#</th>
        <th class="col-artists">Artista</th>
        <th class="col-title">Titolo (Mix)</th>
        <th class="col-dur">Durata</th>
        <th class="col-state"></th>
      </tr>
    </thead>
    <tbody id="beatport-tbody"></tbody>
  </table>

  <div id="beatport-toolbar" class="beatport-toolbar" hidden>
    <span id="beatport-selected-count">0/0 selezionati</span>
    <button id="beatport-download-btn" class="btn btn-primary" disabled>⬇ Scarica selezionati</button>
    <button id="beatport-stop-btn" class="btn btn-ghost" hidden>■ Interrompi</button>
  </div>

  <div id="beatport-log" class="log-area"></div>
</section>
```

Nota: `hidden` sui blocchi che compaiono solo dopo il primo load. Le classi CSS: se l'app usa un tema custom, usa le classi già presenti (`btn-primary`, `log-area`, ecc. — verifica).

- [ ] **Step 4: Smoke test visivo**

Avvia l'app. Clicca la tab 🎧 Beatport → il dropdown appare vuoto, il bottone c'è. Nulla di funzionale ancora — è solo layout.

- [ ] **Step 5: Commit**

```bash
git add webui/index.html
git -c user.email=info@djluza.com commit -m "ui: markup tab Beatport (dropdown, tabella, toolbar)"
```

---

## Task 11: UI — JS init + populate genre dropdown

**Files:**
- Modify: `webui/js/app.js`

- [ ] **Step 1: Trova il bootstrap JS esistente**

Run: `grep -n "pywebview\|DOMContentLoaded\|initTab" webui/js/app.js | head -20`

Individua:
- Come si aspetta l'API pywebview pronta (probabile `window.addEventListener('pywebviewready', …)`)
- Il pattern di init delle altre tab

- [ ] **Step 2: Aggiungi modulo Beatport in fondo a webui/js/app.js**

```javascript
// =====================================================================
// Beatport tab
// =====================================================================

const BeatportUI = {
  state: {
    genres: [],
    currentSlug: null,
    currentGenreName: null,
    tracks: [],
    existing: [],   // parallelo a tracks, boolean già-scaricato
  },

  async init() {
    // Popola dropdown
    const sel = document.getElementById("beatport-genre");
    try {
      this.state.genres = await window.pywebview.api.beatport_genres();
    } catch (e) {
      console.error("beatport_genres failed", e);
      return;
    }
    sel.innerHTML = "";
    for (const g of this.state.genres) {
      const opt = document.createElement("option");
      opt.value = g.slug;
      opt.textContent = g.name;
      sel.appendChild(opt);
    }
    // Ripristina ultimo genere selezionato dal config
    try {
      const cfg = await window.pywebview.api.get_config();  // adatta al nome reale
      if (cfg && cfg.beatport_last_genre) {
        sel.value = cfg.beatport_last_genre;
      }
    } catch { /* ignora */ }

    // Bind eventi
    document.getElementById("beatport-load-btn")
      .addEventListener("click", (e) => this.loadChart(e.shiftKey));
    document.getElementById("beatport-select-all")
      .addEventListener("change", (e) => this.toggleAll(e.target.checked));
    document.getElementById("beatport-download-btn")
      .addEventListener("click", () => this.startDownload());
    document.getElementById("beatport-stop-btn")
      .addEventListener("click", () => this.stopDownload());
  },
};
```

**Nota:** `window.pywebview.api.get_config()` è il nome ipotetico — usa il metodo reale con cui gli altri tab leggono il config (grep per `get_config\|load_config\|api\\..*config`).

- [ ] **Step 3: Aggancia BeatportUI.init() al bootstrap dell'app**

Trova dove le altre tab si inizializzano (dopo `pywebviewready` o dopo il ready DOM) e aggiungi:

```javascript
BeatportUI.init();
```

- [ ] **Step 4: Smoke test**

Avvia l'app, apri tab Beatport. Il dropdown deve essere popolato con i generi. Se selezioni e riavvii, il genere selezionato deve essere ricordato.

- [ ] **Step 5: Commit**

```bash
git add webui/js/app.js
git -c user.email=info@djluza.com commit -m "ui: init Beatport tab + populate genre dropdown"
```

---

## Task 12: UI — loadChart + render tabella

**Files:**
- Modify: `webui/js/app.js`

- [ ] **Step 1: Aggiungi metodi loadChart e renderTable a BeatportUI**

Aggiungi al `BeatportUI` (dopo `init`):

```javascript
  async loadChart(forceRefresh) {
    const sel = document.getElementById("beatport-genre");
    const slug = sel.value;
    const name = sel.options[sel.selectedIndex].text;
    if (!slug) return;

    this.state.currentSlug = slug;
    this.state.currentGenreName = name;

    const statusEl = document.getElementById("beatport-status");
    const tableEl = document.getElementById("beatport-table");
    const toolbarEl = document.getElementById("beatport-toolbar");

    statusEl.textContent = "Caricamento Top 100…";
    statusEl.className = "beatport-status loading";
    tableEl.hidden = true;
    toolbarEl.hidden = true;

    let res;
    try {
      res = await window.pywebview.api.beatport_fetch_chart(slug, forceRefresh);
    } catch (e) {
      statusEl.textContent = "Errore imprevisto: " + e;
      statusEl.className = "beatport-status error";
      return;
    }

    if (!res.ok) {
      const messages = {
        invalid_genre: "Genere non valido.",
        unreachable: "Beatport irraggiungibile. Riprova.",
        parse: "Impossibile leggere la classifica (Beatport ha cambiato struttura?).",
      };
      statusEl.textContent = messages[res.error] || res.message;
      statusEl.className = "beatport-status error";
      return;
    }

    this.state.tracks = res.tracks;
    try {
      this.state.existing = await window.pywebview.api.beatport_check_existing(res.tracks, name);
    } catch {
      this.state.existing = res.tracks.map(() => false);
    }

    statusEl.textContent = "";
    document.getElementById("beatport-output-info").textContent =
      `Cartella output: MUSICA/Beatport/${name}/`;
    this.renderTable();
    tableEl.hidden = false;
    toolbarEl.hidden = false;
  },

  renderTable() {
    const tbody = document.getElementById("beatport-tbody");
    tbody.innerHTML = "";
    for (let i = 0; i < this.state.tracks.length; i++) {
      const t = this.state.tracks[i];
      const already = this.state.existing[i];
      const tr = document.createElement("tr");
      tr.dataset.index = i;
      if (already) tr.classList.add("already-downloaded");

      const mm = Math.floor(t.duration_sec / 60);
      const ss = String(t.duration_sec % 60).padStart(2, "0");
      const mixSuffix = t.mix ? ` (${t.mix})` : "";

      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" ${already ? "" : "checked"}></td>
        <td class="col-pos">${t.position}</td>
        <td class="col-artists">${this._escape(t.artists)}</td>
        <td class="col-title">${this._escape(t.title)}${this._escape(mixSuffix)}</td>
        <td class="col-dur">${mm}:${ss}</td>
        <td class="col-state">${already ? "✓ già scaricato" : ""}</td>
      `;
      tr.querySelector("input[type=checkbox]")
        .addEventListener("change", () => this.updateSelectionCount());
      tbody.appendChild(tr);
    }
    this.updateSelectionCount();
  },

  _escape(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  },
```

- [ ] **Step 2: Smoke test**

Avvia l'app, seleziona un genere, clicca "Carica Top 100" → dopo 1-3s appare la tabella con 100 righe. Log console per debug se serve.

- [ ] **Step 3: Commit**

```bash
git add webui/js/app.js
git -c user.email=info@djluza.com commit -m "ui: Beatport loadChart + render tabella"
```

---

## Task 13: UI — selezione + counter + download

**Files:**
- Modify: `webui/js/app.js`

- [ ] **Step 1: Aggiungi metodi selection + download a BeatportUI**

```javascript
  updateSelectionCount() {
    const boxes = document.querySelectorAll("#beatport-tbody input[type=checkbox]");
    const total = boxes.length;
    const selected = [...boxes].filter(b => b.checked).length;
    document.getElementById("beatport-selected-count").textContent =
      `${selected}/${total} selezionati`;
    const btn = document.getElementById("beatport-download-btn");
    btn.disabled = selected === 0;
    btn.textContent = `⬇ Scarica selezionati (${selected})`;
    // Sync select-all header checkbox (indeterminate se mix)
    const sa = document.getElementById("beatport-select-all");
    sa.checked = selected === total && total > 0;
    sa.indeterminate = selected > 0 && selected < total;
  },

  toggleAll(checked) {
    document.querySelectorAll("#beatport-tbody input[type=checkbox]")
      .forEach(b => { b.checked = checked; });
    this.updateSelectionCount();
  },

  async startDownload() {
    const boxes = document.querySelectorAll("#beatport-tbody input[type=checkbox]");
    const selected = [];
    boxes.forEach((b, i) => {
      if (b.checked) selected.push(this.state.tracks[i]);
    });
    if (!selected.length) return;

    document.getElementById("beatport-download-btn").disabled = true;
    document.getElementById("beatport-stop-btn").hidden = false;
    document.getElementById("beatport-log").innerHTML = "";

    try {
      await window.pywebview.api.beatport_download_selected(selected, this.state.currentGenreName);
    } catch (e) {
      this._appendLog("Errore imprevisto: " + e);
    }

    document.getElementById("beatport-download-btn").disabled = false;
    document.getElementById("beatport-stop-btn").hidden = true;
    // Ricontrolla i file esistenti per aggiornare la tabella
    try {
      this.state.existing = await window.pywebview.api.beatport_check_existing(
        this.state.tracks, this.state.currentGenreName);
      this.renderTable();
    } catch { /* ignora */ }
  },

  async stopDownload() {
    try {
      await window.pywebview.api.request_stop();  // adatta al nome reale
    } catch (e) {
      console.warn("stop failed", e);
    }
  },

  _appendLog(msg) {
    const log = document.getElementById("beatport-log");
    const line = document.createElement("div");
    line.textContent = msg;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  },
```

**Nota:** `window.pywebview.api.request_stop()` è il nome ipotetico. Usa quello reale con cui gli altri tab interrompono i download.

- [ ] **Step 2: Aggancia i log Python al JS**

Nel main.py, `_emit_log` deve chiamare qualcosa tipo `self.window.evaluate_js(f'BeatportUI._appendLog({json.dumps(msg)})')`. Verifica come le altre tab pushano log e replica lo stesso pattern.

**Alternativa più pulita:** se le altre tab usano già un event bus / area log condivisa, riusa quello e non serve aggiungere codice qui.

- [ ] **Step 3: Smoke test end-to-end**

1. Apri app → tab Beatport
2. Seleziona un genere
3. Carica Top 100
4. Deseleziona tutto tranne 3 brani (i primi 3 non ancora nel tuo folder)
5. Clicca "Scarica selezionati (3)"
6. Il log deve stampare progressi per ogni brano
7. Al termine: file .mp3 in `MUSICA/Beatport/<Nome Genere>/`
8. Ricarica la classifica → i 3 brani appaiono ora con "✓ già scaricato"

- [ ] **Step 4: Commit**

```bash
git add webui/js/app.js main.py
git -c user.email=info@djluza.com commit -m "ui: selezione + download Beatport con log live"
```

---

## Task 14: CSS styling

**Files:**
- Modify: `webui/css/*.css` (probabilmente `webui/css/style.css` — verifica)

- [ ] **Step 1: Ispeziona il CSS esistente**

Run: `ls webui/css/; grep -l "tab-panel\|log-area\|btn-primary" webui/css/*.css`

Individua il file principale.

- [ ] **Step 2: Aggiungi stili Beatport in fondo**

```css
/* ============ Beatport tab ============ */

.beatport-header {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  padding: 12px 0;
  border-bottom: 1px solid var(--border, rgba(255,255,255,.08));
}

.beatport-hint {
  color: var(--muted, #888);
  margin-left: auto;
  font-size: 0.85em;
}

.beatport-status {
  padding: 12px 0;
}
.beatport-status.loading { color: var(--muted, #888); }
.beatport-status.error   { color: var(--danger, #c33); font-weight: 600; }

.beatport-output-info {
  padding: 6px 0;
  font-size: 0.85em;
  color: var(--muted, #888);
}

.beatport-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 12px;
}
.beatport-table thead th {
  text-align: left;
  padding: 8px;
  border-bottom: 2px solid var(--border, rgba(255,255,255,.15));
  font-size: 0.85em;
  color: var(--muted, #888);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.beatport-table tbody td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border, rgba(255,255,255,.05));
}
.beatport-table tbody tr:hover {
  background: var(--row-hover, rgba(255,255,255,.03));
}
.beatport-table tbody tr.already-downloaded {
  color: var(--muted, #666);
}
.beatport-table .col-check { width: 32px; }
.beatport-table .col-pos   { width: 40px; text-align: right; color: var(--muted, #888); }
.beatport-table .col-dur   { width: 60px; text-align: right; }
.beatport-table .col-state { width: 120px; font-size: 0.85em; color: var(--muted, #888); }

.beatport-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid var(--border, rgba(255,255,255,.08));
  margin-top: 12px;
}
.beatport-toolbar #beatport-selected-count {
  margin-right: auto;
  color: var(--muted, #888);
  font-size: 0.9em;
}
```

**Se l'app non usa CSS variables (`var(--…)`)**: sostituisci coi colori concreti già in uso (grep per `#` nei css esistenti).

- [ ] **Step 3: Smoke test visivo**

Avvia app, apri tab Beatport, carica una classifica. Verifica: tabella leggibile, header sticky (opzionale), rows "già scaricato" più tenui, toolbar allineata.

- [ ] **Step 4: Commit**

```bash
git add webui/css/*.css
git -c user.email=info@djluza.com commit -m "ui: stili tab Beatport"
```

---

## Task 15: Test suite finale + release notes + tag

**Files:**
- Create: `/tmp/notes-v1.8.0.md`

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -v
```
Expected: TUTTI verdi (21+ test Beatport + 4 Spotify search = 25+)

- [ ] **Step 2: Test end-to-end manuale (obbligatorio prima del tag)**

Segui lo script della spec, sezione "Test manuale end-to-end":

1. Avvia MusicTools, apri tab Beatport
2. Seleziona "Melodic House & Techno" → click "Carica Top 100" → tabella in <3s
3. Deseleziona 90 brani, lascia i primi 10 → click "Scarica selezionati (10)"
4. Verifica file `.mp3` in `{output_dir}/Beatport/Melodic House & Techno/`
5. Ricarica lo stesso genere → cache hit (verificabile con log python o dev-tools)
6. Cambia genere → nuova fetch
7. Avvia un download di 20 brani → premi "Interrompi" a metà → si ferma dopo il brano corrente
8. Riavvia app → dropdown ricorda l'ultimo genere

Se qualunque passo fallisce: torna alla Task pertinente, non tagliare.

- [ ] **Step 3: Scrivi le release notes**

Crea `/tmp/notes-v1.8.0.md`:

```markdown
# MusicTools v1.8.0

## Novità

**Nuova tab Beatport 🎧** — carica direttamente da Beatport le classifiche
Top 100 per genere musicale e scarica i brani in un click.

- 14+ generi disponibili (Melodic House & Techno, Techno, Deep House,
  Tech House, Progressive, Trance, Drum & Bass, e altri)
- Anteprima completa con checkbox per scegliere cosa scaricare
- Riconoscimento automatico dei brani già scaricati
- Riuso del downloader esistente Spotify → YouTube
- Ultimo genere ricordato tra le sessioni

## Bug fix

Nessuno in questa release.
```

- [ ] **Step 4: Merge branch (se hai lavorato su feat/beatport-charts)**

```bash
git checkout main
git merge --no-ff feat/beatport-charts -m "Merge feat/beatport-charts: v1.8.0"
```

- [ ] **Step 5: Tag e push**

```bash
git tag v1.8.0
git push origin main
git push origin v1.8.0
```

- [ ] **Step 6: Verifica CI**

Vai su GitHub Actions, verifica che il build v1.8.0 completi verde su macOS + Windows. La CI applicherà automaticamente le note release da `/tmp/notes-v1.8.0.md` (per il flusso release standard del repo).

- [ ] **Step 7: Aggiorna VERSION nel README (se il repo lo cita)**

Run: `grep -rn "v1.7" README.md landing/ 2>/dev/null | head -5`
Se ci sono riferimenti alla versione precedente, aggiornali con un commit separato.

---

## Riepilogo test attesi

Al termine di questo piano dovresti avere:

- `tests/test_beatport.py`: **21+ test** (list_genres, BeatportTrack, extract_next_data, parse_tracks, fetch_top100)
- `tests/test_spotify_client.py`: **4 test** (search_track)
- Test manuali end-to-end passati
- Nuova tab Beatport funzionante nell'app buildata

## Se qualcosa va storto

- **`__NEXT_DATA__` schema cambiato**: ri-esegui Task 1 Step 3, aggiorna Task 5 di conseguenza, rigenera la fixture HTML
- **Spotify rate-limit** durante download massivi: la libreria yt-dlp gestisce già il throttling; se Spotify search 429, aggiungi `time.sleep(0.2)` fra iterazioni in `beatport_download_selected`
- **Bot detection Beatport**: se le richieste iniziano a fallire in produzione (dopo aver funzionato in test), rotate lo User-Agent in `core/beatport.py::_BEATPORT_UA` e/o aggiungi `Cookie` header estratto da una sessione browser reale (solo come misura d'emergenza)
