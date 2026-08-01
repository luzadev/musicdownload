# Traxsource Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) o superpowers:executing-plans per eseguire task-by-task.

**Goal:** Nuova tab "Traxsource ▲" in sidebar che carica la Top 100 mensile per genere e scarica i brani riusando pipeline Spotify search → yt-dlp → tag ID3.

**Architecture:** Parallela a Beatport. Bypass CF via `curl_cffi.Session` (session-based, non solo TLS impersonation). HTML scraping con BeautifulSoup su class name stabili. Doppio fetch: `/genre/<id>/<slug>` → estrai link `/title/<id>/top-100-...` → parse 100 track. Cache 15 min in-memory.

**Tech Stack:** Python 3.8+ con `from __future__ import annotations`, `curl_cffi` (già in deps), `beautifulsoup4` (nuova dep). Frontend vanilla JS, riusa classi CSS `.beatport-*`.

**Spec:** `docs/superpowers/specs/2026-08-01-traxsource-charts-design.md`

**Reference implementation:** `core/beatport.py`, `api/bridge.py::beatport_*` metodi, `webui/js/app.js::BeatportUI`. Il pattern è identico — replica con adattamenti al parser HTML.

---

## Note operative

- Branch: **`feat/traxsource-charts`** (già creato, HEAD dopo spec)
- Git author: `git -c user.email=info@djluza.com commit ...` sempre
- Python 3.8: `from __future__ import annotations` in ogni nuovo file
- Non toccare `server/`, `landing/`
- Test infra pytest già presente (61+ test verdi baseline)

---

## Task 1: Setup deps + fixture HTML + genres refresh

**Files:**
- Modify: `requirements.txt`
- Create: `tests/fixtures/traxsource_tech_house_genre.html`
- Create: `tests/fixtures/traxsource_tech_house_top100.html`
- Create: `scripts/refresh_traxsource_genres.py`

- [ ] **Step 1: Aggiungi `beautifulsoup4` a requirements.txt**

Prima del blocco `# --- dev only ---` in `requirements.txt`:
```
beautifulsoup4>=4.12.0
```

Verifica: `python3 -m pip install -r requirements.txt` non deve fallire.

- [ ] **Step 2: Scarica fixture pagina genre (per test discovery URL)**

```bash
python3 -c "
from curl_cffi import requests
s = requests.Session(impersonate='chrome131')
s.get('https://www.traxsource.com/', timeout=15)
r = s.get('https://www.traxsource.com/genre/18/tech-house', timeout=15,
          headers={'Referer': 'https://www.traxsource.com/'})
assert r.status_code == 200 and 'top-100' in r.text.lower(), f'bad genre page (HTTP {r.status_code})'
open('tests/fixtures/traxsource_tech_house_genre.html', 'w').write(r.text)
print('saved genre:', len(r.text), 'bytes')
"
```

Se il file è < 100KB o non contiene `top-100`: STOP + report BLOCKED con status HTTP.

- [ ] **Step 3: Scarica fixture pagina Top 100 (~400KB)**

Prima estrai l'URL Top 100 corrente dal genre fixture:
```bash
python3 -c "
import re
html = open('tests/fixtures/traxsource_tech_house_genre.html').read()
m = re.search(r'href=\"(/title/\d+/top-100-[a-z0-9-]+)\"', html)
assert m, 'Top 100 URL non trovato nella genre page'
print(m.group(1))
" > /tmp/tx_top100_url.txt
cat /tmp/tx_top100_url.txt
```

Poi scarica quella URL:
```bash
python3 -c "
from curl_cffi import requests
url_path = open('/tmp/tx_top100_url.txt').read().strip()
s = requests.Session(impersonate='chrome131')
s.get('https://www.traxsource.com/', timeout=15)
r = s.get('https://www.traxsource.com' + url_path, timeout=15,
          headers={'Referer': 'https://www.traxsource.com/'})
assert r.status_code == 200, f'HTTP {r.status_code}'
n_tracks = r.text.count('data-trid=')
assert n_tracks >= 100, f'solo {n_tracks} track (attesi 100)'
open('tests/fixtures/traxsource_tech_house_top100.html', 'w').write(r.text)
print('saved top100:', len(r.text), 'bytes,', n_tracks, 'track markers')
"
```

- [ ] **Step 4: Verifica shape del track markup nella fixture**

```bash
python3 -c "
import re
html = open('tests/fixtures/traxsource_tech_house_top100.html').read()
# Trova primo blocco track
m = re.search(r'<div data-trid=\"\d+\" class=\"top-item play-trk[^>]*>.{0,1500}', html, re.DOTALL)
print(m.group(0)[:1000] if m else 'NO MATCH')
"
```

Aspettato: markup con `<a class=\"com-title\">`, `<a class=\"com-artists\">`, `<a class=\"com-label\">`, `<div class=\"ttib position\">`, `<img src=\"...52x52/...jpg\">`.

Se qualche selettore è cambiato, ANNOTA e adatta i Task 4-5 di conseguenza.

- [ ] **Step 5: Script refresh genres**

Crea `scripts/refresh_traxsource_genres.py`:

```python
"""Estrae la lista dei generi Traxsource dalla pagina /top.
Uso: python3 scripts/refresh_traxsource_genres.py > /tmp/tx_genres.txt
Poi copia manualmente in core/traxsource.py::GENRES."""

from __future__ import annotations

import re
import sys
from curl_cffi import requests


def main() -> int:
    s = requests.Session(impersonate="chrome131")
    s.get("https://www.traxsource.com/", timeout=15)
    r = s.get("https://www.traxsource.com/top", timeout=15,
              headers={"Referer": "https://www.traxsource.com/"})
    if r.status_code != 200:
        print(f"HTTP {r.status_code}", file=sys.stderr)
        return 1
    # href="/genre/<id>/<slug>"
    hits = re.findall(r'href="/genre/(\d+)/([a-z0-9-]+)"', r.text)
    seen = set()
    for gid, slug in hits:
        if slug in seen:
            continue
        seen.add(slug)
        # Display name = slug con capitalizzazione euristica (l'utente lo raffina a mano)
        name = " ".join(w.capitalize() for w in slug.replace("-", " ").split())
        print(f'    "{slug}": ({gid}, "{name}"),')
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Esegui:
```bash
mkdir -p scripts
python3 scripts/refresh_traxsource_genres.py > /tmp/tx_genres.txt
head -30 /tmp/tx_genres.txt
wc -l /tmp/tx_genres.txt
```

Attesi: 15-25 generi. Salva l'output — serve nel Task 2.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt scripts/refresh_traxsource_genres.py tests/fixtures/traxsource_*.html
git -c user.email=info@djluza.com commit -m "traxsource: fixture HTML + bs4 dep + script refresh generi"
```

Report finale: dimensione fixture, numero track markers nel Top 100, generi estratti (sample), primi 800 char del track markup.

---

## Task 2: GENRES map + TraxsourceTrack + list_genres — TDD

**Files:**
- Create: `core/traxsource.py`
- Create: `tests/test_traxsource.py`

- [ ] **Step 1: Test in `tests/test_traxsource.py`**

```python
"""Test per core.traxsource."""

from __future__ import annotations

import pytest

from core import traxsource


class TestListGenres:
    def test_returns_list_of_dicts(self):
        result = traxsource.list_genres()
        assert isinstance(result, list)
        assert len(result) >= 10
        for g in result:
            assert set(g.keys()) == {"slug", "id", "name"}
            assert isinstance(g["slug"], str) and g["slug"]
            assert isinstance(g["id"], int) and g["id"] > 0
            assert isinstance(g["name"], str) and g["name"]

    def test_sorted_alphabetically_by_name(self):
        result = traxsource.list_genres()
        names = [g["name"] for g in result]
        assert names == sorted(names, key=str.casefold)

    def test_tech_house_present(self):
        result = traxsource.list_genres()
        slugs = [g["slug"] for g in result]
        assert "tech-house" in slugs


class TestTraxsourceTrack:
    def test_frozen(self):
        t = traxsource.TraxsourceTrack(
            position=1, title="X", mix="Y", artists="A", label="L",
            traxsource_id=1, slug="x",
        )
        with pytest.raises(Exception):
            t.title = "Z"

    def test_defaults(self):
        t = traxsource.TraxsourceTrack(
            position=1, title="X", mix="", artists="A", label="",
            traxsource_id=1, slug="x",
        )
        assert t.image_url == ""
        assert t.cover_url_large == ""
```

- [ ] **Step 2: Verifica fail**
```
python3 -m pytest tests/test_traxsource.py -v
```
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementa `core/traxsource.py` minimo**

```python
"""Fetch Top 100 Traxsource per genere.

Approccio: session curl_cffi (bypass CF via cookie) + BeautifulSoup HTML scraping.
Spec: docs/superpowers/specs/2026-08-01-traxsource-charts-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass


# Sostituire il blocco sottostante con l'output di /tmp/tx_genres.txt
GENRES: dict = {
    "afro-house": (33, "Afro House"),
    "amapiano": (37, "Amapiano"),
    "classic-house": (12, "Classic House"),
    "deep-house": (13, "Deep House"),
    "electronica": (5, "Electronica"),
    "electro-house": (11, "Electro House"),
    "funky-jackin-groovy": (15, "Funky / Jackin / Groovy"),
    "house": (1, "House"),
    "melodic-house-techno-progressive-house": (34, "Melodic House / Techno / Progressive House"),
    "minimal-deep-tech": (27, "Minimal / Deep Tech"),
    "progressive-house": (28, "Progressive House"),
    "soulful-house": (24, "Soulful House"),
    "tech-house": (18, "Tech House"),
    "techno-peak-time-driving": (26, "Techno (Peak Time / Driving)"),
    "techno-raw-deep-hypnotic": (32, "Techno (Raw / Deep / Hypnotic)"),
    "trance": (30, "Trance"),
}


@dataclass(frozen=True)
class TraxsourceTrack:
    position: int
    title: str
    mix: str
    artists: str
    label: str
    traxsource_id: int
    slug: str
    image_url: str = ""
    cover_url_large: str = ""


def list_genres() -> list:
    result = [
        {"slug": slug, "id": gid, "name": name}
        for slug, (gid, name) in GENRES.items()
    ]
    result.sort(key=lambda g: g["name"].casefold())
    return result
```

**Se hai l'output completo /tmp/tx_genres.txt:** sostituisci il blocco `GENRES = {...}` con la lista completa dallo script.

- [ ] **Step 4: Verifica PASS**
```
python3 -m pytest tests/test_traxsource.py -v
```
Expected: 5 test PASS.

- [ ] **Step 5: Commit**
```bash
git add core/traxsource.py tests/test_traxsource.py
git -c user.email=info@djluza.com commit -m "traxsource: GENRES + TraxsourceTrack + list_genres"
```

---

## Task 3: Helper parser (_split_title_mix, _format_artists, _large_cover) + exceptions — TDD

**Files:**
- Modify: `core/traxsource.py`
- Modify: `tests/test_traxsource.py`

- [ ] **Step 1: Test in fondo a `tests/test_traxsource.py`**

```python
class TestSplitTitleMix:
    def test_with_parens(self):
        assert traxsource._split_title_mix("Foo (Extended Mix)") == ("Foo", "Extended Mix")

    def test_without_parens(self):
        assert traxsource._split_title_mix("Foo") == ("Foo", "")

    def test_multiple_parens_takes_last(self):
        # es. "Foo (feat. Bar) (Original Mix)" → mix = "Original Mix"
        assert traxsource._split_title_mix("Foo (feat. Bar) (Original Mix)") == ("Foo (feat. Bar)", "Original Mix")

    def test_empty(self):
        assert traxsource._split_title_mix("") == ("", "")


class TestFormatArtists:
    def test_single(self):
        assert traxsource._format_artists(["Kapuchon"]) == "Kapuchon"

    def test_two(self):
        assert traxsource._format_artists(["A", "B"]) == "A & B"

    def test_three(self):
        assert traxsource._format_artists(["A", "B", "C"]) == "A, B & C"

    def test_empty(self):
        assert traxsource._format_artists([]) == ""

    def test_strips_whitespace(self):
        assert traxsource._format_artists(["  A  ", " B "]) == "A & B"


class TestLargeCover:
    def test_substitutes_52x52_with_500x500(self):
        url = "https://www.traxsource.com/scripts/image.php/52x52/abc.jpg"
        assert traxsource._large_cover(url) == "https://www.traxsource.com/scripts/image.php/500x500/abc.jpg"

    def test_no_change_when_no_pattern(self):
        assert traxsource._large_cover("https://example.com/x.jpg") == "https://example.com/x.jpg"

    def test_empty(self):
        assert traxsource._large_cover("") == ""


class TestExceptions:
    def test_exceptions_are_subclasses(self):
        assert issubclass(traxsource.TraxsourceUnreachableError, traxsource.TraxsourceError)
        assert issubclass(traxsource.TraxsourceParseError, traxsource.TraxsourceError)
```

- [ ] **Step 2: Verifica fail**
`python3 -m pytest tests/test_traxsource.py -v` → FAIL sui nuovi.

- [ ] **Step 3: Implementa helper + eccezioni in `core/traxsource.py`**

Aggiungi in fondo al modulo:

```python
import re


class TraxsourceError(Exception):
    """Base per errori Traxsource."""


class TraxsourceUnreachableError(TraxsourceError):
    """Rete / 5xx dopo retry."""


class TraxsourceParseError(TraxsourceError):
    """HTML ricevuto ma non conforme allo schema atteso."""


_MIX_PAREN_RE = re.compile(r"^(.*)\s*\(([^()]+)\)\s*$")
_SIZE_RE = re.compile(r"/\d+x\d+/")


def _split_title_mix(full_title: str) -> tuple:
    """Estrae mix dalle parentesi finali. 'Foo (Extended Mix)' -> ('Foo', 'Extended Mix').
    Se non ci sono parentesi finali, mix = ''."""
    if not full_title:
        return ("", "")
    m = _MIX_PAREN_RE.match(full_title.strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (full_title.strip(), "")


def _format_artists(names: list) -> str:
    """['A', 'B', 'C'] -> 'A, B & C'. Strips whitespace."""
    clean = [n.strip() for n in names if n and n.strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    return ", ".join(clean[:-1]) + " & " + clean[-1]


def _large_cover(url: str) -> str:
    """Sostituisce /NxN/ nel path con /500x500/. Se pattern assente, ritorna invariato."""
    if not url:
        return ""
    return _SIZE_RE.sub("/500x500/", url)
```

- [ ] **Step 4: Verifica PASS**
`python3 -m pytest tests/test_traxsource.py -v`
Expected: ~17 test PASS.

- [ ] **Step 5: Commit**
```bash
git add core/traxsource.py tests/test_traxsource.py
git -c user.email=info@djluza.com commit -m "traxsource: helper _split_title_mix + _format_artists + _large_cover + eccezioni"
```

---

## Task 4: _discover_top100_url + _parse_tracks — TDD

**Files:**
- Modify: `core/traxsource.py`
- Modify: `tests/test_traxsource.py`

- [ ] **Step 1: Test**

Aggiungi:
```python
class TestDiscoverTop100Url:
    def test_extracts_link_from_genre_page(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_genre.html").read_text()
        url = traxsource._discover_top100_url(html)
        assert url.startswith("/title/")
        assert "top-100" in url

    def test_raises_when_no_link(self):
        with pytest.raises(traxsource.TraxsourceParseError, match="Top 100"):
            traxsource._discover_top100_url("<html>nulla</html>")


class TestParseTracks:
    def test_parses_100_tracks(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_top100.html").read_text()
        tracks = traxsource._parse_tracks(html)
        assert len(tracks) == 100

    def test_positions_sequential_1_to_100(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_top100.html").read_text()
        tracks = traxsource._parse_tracks(html)
        positions = [t.position for t in tracks]
        assert positions == list(range(1, 101))

    def test_track_shape(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_top100.html").read_text()
        tracks = traxsource._parse_tracks(html)
        first = tracks[0]
        assert first.title
        assert first.artists
        assert first.traxsource_id > 0
        assert first.slug
        assert first.image_url.startswith("https://")
        assert first.cover_url_large.startswith("https://")
        assert "500x500" in first.cover_url_large

    def test_raises_when_no_tracks(self):
        with pytest.raises(traxsource.TraxsourceParseError, match="track"):
            traxsource._parse_tracks("<html>vuoto</html>")
```

- [ ] **Step 2: Verifica fail**

- [ ] **Step 3: Implementa**

Aggiungi in `core/traxsource.py`:

```python
from bs4 import BeautifulSoup


_TOP100_LINK_RE = re.compile(r'href="(/title/\d+/top-100-[a-z0-9-]+)"')


def _discover_top100_url(genre_html: str) -> str:
    """Estrae il path relativo della playlist Top 100 corrente dalla pagina di un genere."""
    m = _TOP100_LINK_RE.search(genre_html)
    if not m:
        raise TraxsourceParseError("link Top 100 non trovato nella pagina genere")
    return m.group(1)


def _parse_tracks(html: str) -> list:
    """Parsa la pagina Top 100 (title playlist) e ritorna list[TraxsourceTrack]."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.top-item.play-trk")
    if not rows:
        raise TraxsourceParseError("nessuna div.top-item.play-trk trovata")

    out: list = []
    for i, row in enumerate(rows, 1):
        try:
            trid = int(row.get("data-trid") or 0)
            pos_el = row.select_one("div.ttib.position")
            position = i  # fallback su enumerate se pos manca
            if pos_el and pos_el.text.strip().isdigit():
                position = int(pos_el.text.strip())

            title_a = row.select_one("a.com-title")
            if not title_a:
                continue
            full_title = title_a.text.strip()
            title, mix = _split_title_mix(full_title)
            slug = (title_a.get("href") or "").split("/")[-1]

            artist_names = [a.text for a in row.select("a.com-artists")]
            artists = _format_artists(artist_names)

            label_a = row.select_one("a.com-label")
            label = label_a.text.strip() if label_a else ""

            img = row.select_one("img")
            image_url = (img.get("src") or "") if img else ""
            cover_large = _large_cover(image_url)

            out.append(TraxsourceTrack(
                position=position,
                title=title,
                mix=mix,
                artists=artists,
                label=label,
                traxsource_id=trid,
                slug=slug,
                image_url=image_url,
                cover_url_large=cover_large,
            ))
        except Exception as e:
            raise TraxsourceParseError(f"errore parse track[{i}]: {e}") from e
    return out
```

- [ ] **Step 4: Verifica PASS**
Expected: ~23 test verdi totali.

Se `test_parses_100_tracks` fallisce: il selettore CSS è diverso. Ispeziona la fixture (`grep -c 'top-item play-trk' fixture.html`) e adatta il selettore in `_parse_tracks`.

- [ ] **Step 5: Commit**
```bash
git add core/traxsource.py tests/test_traxsource.py
git -c user.email=info@djluza.com commit -m "traxsource: _discover_top100_url + _parse_tracks con BeautifulSoup"
```

---

## Task 5: fetch_top100 con session + retry + cache — TDD

**Files:**
- Modify: `core/traxsource.py`
- Modify: `tests/test_traxsource.py`

- [ ] **Step 1: Test (mock su _session per non chiamare la rete)**

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
    def genre_html(self, fixtures_dir):
        return (fixtures_dir / "traxsource_tech_house_genre.html").read_text()

    @pytest.fixture
    def top100_html(self, fixtures_dir):
        return (fixtures_dir / "traxsource_tech_house_top100.html").read_text()

    def test_success_returns_100_tracks(self, genre_html, top100_html):
        traxsource._cache.clear()
        mock_sess = MagicMock()
        mock_sess.get.side_effect = [
            _mock_response(genre_html, 200),
            _mock_response(top100_html, 200),
        ]
        with patch("core.traxsource._session", return_value=mock_sess):
            tracks = traxsource.fetch_top100("tech-house")
        assert len(tracks) == 100

    def test_invalid_slug_raises_value_error(self):
        with pytest.raises(ValueError, match="slug"):
            traxsource.fetch_top100("not-a-genre")

    def test_5xx_retries_and_raises_unreachable(self):
        traxsource._cache.clear()
        mock_sess = MagicMock()
        mock_sess.get.return_value = _mock_response("", 503)
        with patch("core.traxsource._session", return_value=mock_sess), \
             patch("core.traxsource.time.sleep"):
            with pytest.raises(traxsource.TraxsourceUnreachableError):
                traxsource.fetch_top100("tech-house")
        # 3 tentativi
        assert mock_sess.get.call_count == 3

    def test_cache_hit_within_ttl(self, genre_html, top100_html):
        traxsource._cache.clear()
        mock_sess = MagicMock()
        mock_sess.get.side_effect = [
            _mock_response(genre_html, 200),
            _mock_response(top100_html, 200),
        ]
        with patch("core.traxsource._session", return_value=mock_sess):
            traxsource.fetch_top100("tech-house")
            traxsource.fetch_top100("tech-house")
        # 2 chiamate al primo fetch (genre + top100), 0 al secondo
        assert mock_sess.get.call_count == 2

    def test_force_refresh_bypasses_cache(self, genre_html, top100_html):
        traxsource._cache.clear()
        mock_sess = MagicMock()
        # 4 risposte (2 fetch × 2 richieste ciascuno)
        mock_sess.get.side_effect = [
            _mock_response(genre_html, 200),
            _mock_response(top100_html, 200),
            _mock_response(genre_html, 200),
            _mock_response(top100_html, 200),
        ]
        with patch("core.traxsource._session", return_value=mock_sess):
            traxsource.fetch_top100("tech-house")
            traxsource.fetch_top100("tech-house", force_refresh=True)
        assert mock_sess.get.call_count == 4
```

- [ ] **Step 2: Verifica fail**

- [ ] **Step 3: Implementa in `core/traxsource.py`**

Aggiungi in cima (dopo `import re`):
```python
import time
```

Aggiungi in fondo:

```python
_IMPERSONATE = "chrome131"
_REQUEST_TIMEOUT = 15
_MAX_ATTEMPTS = 3
_BACKOFF_SEC = [1, 3]
_CACHE_TTL_SEC = 15 * 60

_cache: dict = {}
_session_singleton = None


def _session():
    """Ritorna la Session curl_cffi singleton, preriscaldata con GET a /."""
    global _session_singleton
    if _session_singleton is None:
        from curl_cffi import requests as _cffi
        _session_singleton = _cffi.Session(impersonate=_IMPERSONATE)
        try:
            _session_singleton.get("https://www.traxsource.com/", timeout=_REQUEST_TIMEOUT)
        except Exception:
            pass  # cookie CF possono arrivare comunque
    return _session_singleton


def _do_get(session, url: str) -> str:
    """GET con retry + backoff. Include Referer per pagine interne."""
    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = session.get(
                url,
                timeout=_REQUEST_TIMEOUT,
                headers={"Referer": "https://www.traxsource.com/"},
            )
            if resp.status_code >= 500 or resp.status_code == 403:
                raise Exception(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SEC[attempt])
    raise TraxsourceUnreachableError(
        f"Traxsource irraggiungibile dopo {_MAX_ATTEMPTS} tentativi: {last_exc}"
    )


def fetch_top100(slug: str, force_refresh: bool = False) -> list:
    """Fetches Top 100 corrente per il genere.

    1. Verifica slug in GENRES
    2. Fetch pagina genre → _discover_top100_url
    3. Fetch pagina Top 100 → _parse_tracks
    4. Cache 15 min

    Raises:
        ValueError: slug non in GENRES
        TraxsourceUnreachableError: rete/5xx dopo retry
        TraxsourceParseError: HTML non conforme
    """
    if slug not in GENRES:
        raise ValueError(f"slug genere non valido: {slug!r}")

    now = time.time()
    if not force_refresh:
        cached = _cache.get(slug)
        if cached and (now - cached[0]) < _CACHE_TTL_SEC:
            return cached[1]

    gid, _name = GENRES[slug]
    sess = _session()

    genre_url = f"https://www.traxsource.com/genre/{gid}/{slug}"
    genre_html = _do_get(sess, genre_url)
    top100_path = _discover_top100_url(genre_html)

    top100_url = "https://www.traxsource.com" + top100_path
    top100_html = _do_get(sess, top100_url)
    tracks = _parse_tracks(top100_html)

    _cache[slug] = (now, tracks)
    return tracks
```

- [ ] **Step 4: Verifica**
`python3 -m pytest tests/ -v 2>&1 | tail -3`
Expected: ~28 test verdi totali (5 preesistenti + nuovi).

- [ ] **Step 5: Commit**
```bash
git add core/traxsource.py tests/test_traxsource.py
git -c user.email=info@djluza.com commit -m "traxsource: fetch_top100 con session curl_cffi + retry + cache 15min"
```

---

## Task 6: Config bump v1.9.0 + traxsource_last_genre

**Files:** `core/config.py`

- [ ] **Step 1:** Cambia `VERSION = "v1.8.6"` in `VERSION = "v1.9.0"`.
- [ ] **Step 2:** Nel dict `DEFAULTS`, aggiungi dopo `beatport_last_genre`:
```python
    "traxsource_last_genre": "tech-house",
```
- [ ] **Step 3:** Verifica:
```bash
python3 -c "from core.config import load_config, VERSION; c = load_config(); print(VERSION, c.get('traxsource_last_genre'))"
```
Expected: `v1.9.0 tech-house`.
- [ ] **Step 4:** Commit:
```bash
git add core/config.py
git -c user.email=info@djluza.com commit -m "config: v1.9.0 + traxsource_last_genre nei DEFAULTS"
```

---

## Task 7: bridge — 4 metodi Api Traxsource

**Files:** `api/bridge.py`

- [ ] **Step 1: Aggiungi `from core import traxsource` agli import**

Trova la sezione `from core import beatport, spotify_client` e aggiungi `traxsource`:
```python
from core import beatport, spotify_client, traxsource
```

- [ ] **Step 2: Aggiungi 4 metodi + helper in fondo alla classe Api (dopo i metodi beatport)**

Il pattern è identico a beatport_*. Adatta solo i nomi + il calcolo del subfolder (`Traxsource_<genre>` invece di `Beatport_<genre>`) + i campi metadata (album=label per Traxsource, non nome release).

```python
    # ================================================================
    # Traxsource charts
    # ================================================================

    def _traxsource_output_dir(self, out_root: str, genre_name: str) -> Path:
        safe_genre = genre_name.replace("/", "_").replace("\\", "_").strip()
        subfolder = f"Traxsource_{safe_genre}" if safe_genre else "Traxsource"
        return Path(out_root) / subfolder

    def traxsource_genres(self) -> list:
        return traxsource.list_genres()

    def traxsource_fetch_chart(self, slug: str, force_refresh: bool = False) -> dict:
        try:
            cfg = load_config()
            cfg["traxsource_last_genre"] = slug
            save_config(cfg)
        except Exception:
            pass
        try:
            tracks = traxsource.fetch_top100(slug, force_refresh=force_refresh)
        except ValueError as e:
            return {"ok": False, "error": "invalid_genre", "message": str(e)}
        except traxsource.TraxsourceUnreachableError as e:
            return {"ok": False, "error": "unreachable", "message": str(e)}
        except traxsource.TraxsourceParseError as e:
            return {"ok": False, "error": "parse", "message": str(e)}
        return {"ok": True, "tracks": [asdict(t) for t in tracks]}

    def traxsource_check_existing(self, tracks: list, genre_name: str) -> list:
        cfg = load_config()
        out_root = (cfg.get("output_dir") or "").strip()
        if not out_root:
            return [False] * len(tracks)
        out_dir = self._traxsource_output_dir(out_root, genre_name)
        if not out_dir.exists():
            return [False] * len(tracks)
        existing_stems = [p.stem.lower() for p in out_dir.glob("*.mp3")]
        result = []
        for t in tracks:
            title = (t.get("title") or "").lower().strip()
            artists = (t.get("artists") or "")
            first_artist = artists.split(",")[0].split("&")[0].strip().lower()
            if not title or not first_artist:
                result.append(False)
                continue
            result.append(any(
                (title in stem and first_artist in stem)
                for stem in existing_stems
            ))
        return result

    def traxsource_download_selected(self, tracks: list, genre_name: str) -> dict:
        cfg = load_config()
        out_root = (cfg.get("output_dir") or "").strip()
        if not out_root:
            return {"ok": False, "error": "Cartella output non impostata"}
        target = self._traxsource_output_dir(out_root, genre_name)
        subfolder = target.name

        # Costruisci tracks per start_tracks_download + metadata paralleli per il tagger
        import datetime as _dt
        today = _dt.date.today()
        current_month = today.strftime("%Y-%m")

        converted = []
        metadata = []
        for t in tracks:
            title = (t.get("title") or "").strip()
            artists = (t.get("artists") or "").strip()
            if not title:
                continue
            converted.append({"name": title, "artist": artists})
            metadata.append({
                "title": title,
                "artist": artists,
                "album": (t.get("label") or "").strip() or f"Traxsource Top 100 {current_month}",
                "date": current_month,
                "genre": genre_name,
                "cover_url": t.get("cover_url_large") or t.get("image_url") or "",
            })

        if not converted:
            return {"ok": False, "error": "Nessun brano valido"}

        return self.start_tracks_download({
            "tracks": converted,
            "output_dir": out_root,
            "subfolder": subfolder,
            "metadata": metadata,
        })
```

- [ ] **Step 3: Smoke test bridge**
```bash
python3 -c "from api.bridge import Api; a=Api(); print('genres:', len(a.traxsource_genres()))"
python3 -c "from api.bridge import Api; a=Api(); print('empty check:', a.traxsource_check_existing([], 'X'))"
```
Expected: genres ≥10, empty check `[]`.

- [ ] **Step 4: Full pytest**
`python3 -m pytest tests/ -v 2>&1 | tail -3` → no regressioni.

- [ ] **Step 5: Commit**
```bash
git add api/bridge.py
git -c user.email=info@djluza.com commit -m "bridge: 4 metodi Api Traxsource (parallelo Beatport, metadata album=label)"
```

---

## Task 8: UI (HTML + JS + CSS)

**Files:**
- Modify: `webui/index.html`
- Modify: `webui/js/app.js`

Struttura identica a Beatport. Sostituisci `beatport-*` con `traxsource-*` negli ID e replica il modulo JS.

- [ ] **Step 1: HTML — nuova nav-item + section**

Dopo il nav-item Beatport (`data-view="beatport"`), aggiungi:
```html
<button class="nav-item" data-view="traxsource" data-feature="audio">
  <span class="nav-icon">▲</span>
  <span>Traxsource</span>
</button>
```

Dopo `<section id="view-beatport">…</section>`, aggiungi (copia adattata):

```html
<section class="view" id="view-traxsource">
  <header class="hero hero-purple">
    <div class="hero-content">
      <div class="hero-eyebrow purple">TRAXSOURCE</div>
      <h1 class="hero-title">Top 100 Traxsource per genere</h1>
      <p class="hero-subtitle">La classifica mensile ufficiale · Scarica in un click con tag ID3 completi</p>
    </div>
    <div class="hero-deco">▲</div>
  </header>

  <section class="card">
    <div class="beatport-header">
      <label style="display:flex;align-items:center;gap:8px;">
        Genere:
        <select id="traxsource-genre" class="input"></select>
      </label>
      <button id="traxsource-load-btn" class="btn btn-primary pill">▶ Carica Top 100</button>
      <span class="hint-inline">Shift+click per forzare refresh (bypass cache 15min)</span>
    </div>
    <div id="traxsource-status" class="beatport-status"></div>
    <div id="traxsource-output-info" class="beatport-output-info"></div>

    <div class="beatport-table-card" id="traxsource-table-wrap" hidden>
      <div class="beatport-table-wrap">
        <table id="traxsource-table" class="beatport-table">
          <thead>
            <tr>
              <th class="col-check"><input type="checkbox" id="traxsource-select-all" /></th>
              <th class="col-cover"></th>
              <th class="col-pos sortable" data-sort="position">#</th>
              <th class="sortable" data-sort="artists">Artista</th>
              <th class="sortable" data-sort="title">Titolo (Mix)</th>
              <th class="sortable" data-sort="label">Label</th>
              <th class="col-state">Stato</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="beatport-toolbar" id="traxsource-toolbar" hidden>
      <span class="counter" id="traxsource-selected-count">0/0 selezionati</span>
      <button id="traxsource-download-btn" class="btn btn-primary pill" disabled>▶ Scarica selezionati</button>
      <button id="traxsource-stop-btn" class="btn btn-danger pill" hidden>■ Interrompi</button>
    </div>
  </section>

  <section class="log-card">
    <div class="section-label">LOG</div>
    <div id="traxsource-log" class="log"></div>
  </section>
</section>
```

- [ ] **Step 2: JS — modulo TraxsourceUI**

Copia intera l'IIFE `BeatportUI` da `webui/js/app.js` (dalla riga `const BeatportUI = (function () {` fino al `})();` di chiusura) e replica come `TraxsourceUI` **dopo YoutubeUI**. Poi sostituisci sistematicamente:

- `beatport` → `traxsource` (tutti gli ID, chiavi API, nomi config)
- `Beatport` → `Traxsource` (nomi visibili nei log/status)
- Nella renderTable: le colonne sono diverse — sostituisci il rendering di "Titolo (Mix)" per Traxsource (già così), aggiungi colonna Label:
  ```javascript
  const tdLabel = document.createElement("td");
  tdLabel.textContent = t.label || "";
  tr.appendChild(tdLabel);
  ```
  E rimuovi la colonna Durata (Traxsource non ha duration nel markup).
- Nel `updateOutputInfo`, cartella `Traxsource_<genre>` invece di `Beatport/<genre>`.

**Aggiungi `traxsource` a `logEls`:**
```javascript
  traxsource: () => document.getElementById("traxsource-log"),
```

**Aggiungi bootstrap:**
Trova `await BeatportUI.init();` in `init()` principale (~riga 508), aggiungi dopo:
```javascript
  await TraxsourceUI.init();
```

- [ ] **Step 3: Verifiche**
```bash
node --check webui/js/app.js
python3 -m pytest tests/ 2>&1 | tail -3
python3 -c "from api.bridge import Api; a=Api(); print(len(a.traxsource_genres()))"
```
Expected: JS OK, tutti test verdi, ≥10 generi.

- [ ] **Step 4: Commit (2 separati)**
```bash
git add webui/index.html
git -c user.email=info@djluza.com commit -m "ui: markup tab Traxsource"
git add webui/js/app.js
git -c user.email=info@djluza.com commit -m "ui: TraxsourceUI (init, loadChart, render, download)"
```

---

## Task 9: Test finale + release v1.9.0

- [ ] **Step 1:** `python3 -m pytest tests/ -v` → tutti verdi (61 + ~13 Traxsource = ~74)
- [ ] **Step 2:** Test manuale end-to-end (vedi spec sez. "Test manuale end-to-end")
- [ ] **Step 3:** `/tmp/notes-v1.9.0.md` con descrizione feature
- [ ] **Step 4:** Merge branch, tag `v1.9.0`, push. STOP prima del push per conferma utente (protocollo release del repo — vedi memory `musictools-release-flow`).
- [ ] **Step 5:** CI watch + apply notes + upload builds server + insert DB (flusso standard).

## Se qualcosa va storto

- **Cloudflare block persistente su session:** aumenta la pausa dopo GET `/`, o aggiungi header `Sec-Fetch-*` a mano. Se ancora bloccato: rotare `impersonate` (`chrome`, `chrome124`, `safari17_2`) e vedere quale passa
- **CSS class name cambiati:** BeautifulSoup fallisce silenzioso su selettori inesistenti → `_parse_tracks` solleva `TraxsourceParseError("nessuna div.top-item.play-trk trovata")`. Ispeziona `tests/fixtures/traxsource_tech_house_top100.html` per il vero markup e aggiorna il selettore
- **Meno di 100 track parsati:** verifica che la pagina Top 100 non abbia paginazione (Traxsource storicamente carica tutto server-side, ma se cambia serve una seconda GET)
