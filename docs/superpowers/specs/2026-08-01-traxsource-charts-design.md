# Traxsource Charts — Design Spec

- **Data:** 2026-08-01
- **Autore:** LuZa + Claude
- **Stato:** Approvato, pronto per implementation plan
- **Target release:** MusicTools v1.9.0

## Obiettivo

Nuova tab "▲ Traxsource" nell'app che permette di:

1. Scegliere un genere musicale da un elenco di ~15 generi Traxsource
2. Caricare la **Top 100** ufficiale del mese corrente per quel genere
3. Anteprima checkbox + download riusando il pipeline esistente (Spotify search → yt-dlp → tag ID3 + cover)

Sostituisce l'attività manuale di copiare/incollare tracklist Traxsource.

## Non-goals

- Chart diverse dalla Top 100 (Must Have, Just Added, ecc.)
- Ricerca artista/label specifica su Traxsource
- Preview audio (Traxsource ha DRM)
- Duration tracks (non è nell'HTML della lista; sarebbe una richiesta extra per track)
- Login/account Traxsource

## Ricognizione tecnica (fatta 2026-08-01)

- **Cloudflare Managed Challenge attivo** su tutte le pagine tranne home e /top. Bypass: session-based con `curl_cffi.Session(impersonate='chrome131')`, prima GET a `/`, poi le pagine sensibili con `Referer: https://www.traxsource.com/`.
- **Non è Next.js** → no `__NEXT_DATA__`. HTML server-rendered.
- **Struttura URL:**
  - Genre index: `/genre/<id>/<slug>` — es. `/genre/18/tech-house`. Contiene solo 10 top track più altri widget
  - Top 100 corrente: `/title/<title_id>/top-100-<genre>-of-<month>-<year>` — es. `/title/2847986/top-100-tech-house-of-july-2026`. Contiene 100 track completi in un unico documento (~394KB)
  - **Il title_id cambia ogni mese.** Non è hardcodabile. Va scoperto dinamicamente
- **Discovery Top 100 URL:** nella pagina `/genre/<id>/<slug>` c'è (almeno un) `<a href="/title/<id>/top-100-<slug>-of-<month>-<year>">`. Estrai col regex `href="(/title/\d+/top-100-[a-z0-9-]+)"`
- **Track markup (stabile):**
  ```html
  <div data-trid="14842066" class="top-item play-trk ptk-14842066">
    <div class="ttib position">1</div>
    <div class="image"><img src="https://.../52x52/HASH.jpg" /></div>
    <div class="ttib info">
      <a href="/track/14842066/badman-sound-extended-mix" class="com-title">Badman Sound (Extended Mix)</a>
      <a href="/artist/92248/hannah-wants" class="com-artists">Hannah Wants</a>,
      <a href="/artist/321517/trace" class="com-artists">Trace</a>
      <a href="/label/325/nervous" class="com-label">Nervous</a>
    </div>
  </div>
  ```
  Class names sono stabili (semantici, non generati da bundler).
- **Cover art:** URL contiene la size (`/52x52/`). Sostituendo con `/500x500/` si ottiene la versione grande per tagging ID3.

## Approccio scelto

- Session `curl_cffi` con `impersonate='chrome131'`. Cookie CF conservati automaticamente. Preriscaldamento con GET a `/` al primo utilizzo.
- Parser: `BeautifulSoup4` con selettori CSS puliti — `div.top-item.play-trk` per righe, `a.com-title` per titolo, `a.com-artists` per artisti, `a.com-label` per label, `div.ttib.position` per rank, `img` per cover URL.
- Regex sul titolo per estrarre "mix name" tra parentesi: `Song Title (Extended Mix)` → title="Song Title", mix="Extended Mix".
- Cache in-memory 15 min per la lista, come Beatport.
- Genere → (numeric_id, slug, display_name) map hardcoded (estratti dalla home /top).

**Alternative scartate:**
- `requests` puro: bloccato da CF, verificato
- API interna Traxsource: non esistono API pubbliche gratuite documentate; reverse engineering rischio ban
- Playwright: overkill (~100MB dep) quando session + BeautifulSoup basta

## Architettura

### Nuovo modulo `core/traxsource.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Mappa slug → (numeric_id, display_name)
# Verificati 2026-08-01 dalla home /top di Traxsource
GENRES: dict = {
    "afro-house": (33, "Afro House"),
    "afro-latin-brazilian": (23, "Afro / Latin / Brazilian"),
    "amapiano": (37, "Amapiano"),
    "bass-club": (25, "Bass / Club"),
    "breaks-uk-bass": (14, "Breaks / UK Bass"),
    "classic-house": (12, "Classic House"),
    "deep-house": (13, "Deep House"),
    "dj-tools": (16, "DJ Tools"),
    "downtempo-nu-disco-indie-dance": (22, "Downtempo / Nu Disco / Indie Dance"),
    "electronica": (5, "Electronica"),
    "electro-house": (11, "Electro House"),
    "funky-jackin-groovy": (15, "Funky / Jackin / Groovy"),
    "garage": (29, "Garage"),
    "house": (1, "House"),
    "lounge-chill-out": (10, "Lounge / Chill Out"),
    "melodic-house-techno-progressive-house": (34, "Melodic House / Techno / Progressive House"),
    "minimal-deep-tech": (27, "Minimal / Deep Tech"),
    "organic-house-downtempo": (36, "Organic House / Downtempo"),
    "progressive-house": (28, "Progressive House"),
    "r-and-b-hip-hop": (6, "R&B / Hip Hop"),
    "soulful-house": (24, "Soulful House"),
    "tech-house": (18, "Tech House"),
    "techno-peak-time-driving": (26, "Techno (Peak Time / Driving)"),
    "techno-raw-deep-hypnotic": (32, "Techno (Raw / Deep / Hypnotic)"),
    "trance": (30, "Trance"),
    "world-reggae": (21, "World / Reggae"),
}
# NOTA: la mappa è enumerata in fase di implementazione fetchando /top con curl_cffi
# e cercando href="/genre/<id>/<slug>". Vedi Task 1 del plan.


@dataclass(frozen=True)
class TraxsourceTrack:
    position: int
    title: str
    mix: str
    artists: str        # "A, B & C" formattato
    label: str
    traxsource_id: int
    slug: str
    image_url: str = ""    # URL thumbnail (per UI)
    cover_url_large: str = ""  # URL cover 500x500 (per tagging)


class TraxsourceError(Exception): pass
class TraxsourceUnreachableError(TraxsourceError): pass
class TraxsourceParseError(TraxsourceError): pass


def list_genres() -> list:
    """Ritorna [{slug, id, name}, ...] ordinato alfabeticamente per name."""


def fetch_top100(slug: str, force_refresh: bool = False) -> list[TraxsourceTrack]:
    """Fetches Top 100 corrente per il genere.

    1. Scopre l'URL della playlist Top 100 del mese via GET /genre/<id>/<slug>
    2. Fetch della playlist /title/<id>/top-100-...
    3. Parse HTML con BeautifulSoup
    4. Cache in-memory 15 min

    Raises:
        ValueError se slug non in GENRES
        TraxsourceUnreachableError su rete/5xx dopo retry
        TraxsourceParseError su HTML non conforme (title link non trovato, meno di 50 track, ecc.)
    """
```

**Internals:**
- `_session()` singleton — inizializza `curl_cffi.Session(impersonate='chrome131')` e fa GET a `/` una volta per riscaldare CF cookies. Riusata per tutte le fetch successive.
- `_discover_top100_url(session, slug) → str` — fetcha `/genre/<id>/<slug>`, regex per il link Top 100
- `_parse_tracks(html) → list[TraxsourceTrack]` — BeautifulSoup, itera `div.top-item.play-trk`, estrae campi
- `_split_title_mix(full_title) → (title, mix)` — parsa `"Foo (Extended Mix)"` → `("Foo", "Extended Mix")`. Se no parentesi, mix = "".
- `_format_artists(anchors) → str` — join `[a.text for a in anchors]` con formattazione "A, B & C"
- `_large_cover(url) → str` — sostituisce `/52x52/` con `/500x500/` nel path

**Retry + timeout:** riusa gli stessi pattern di `core/beatport.py`: 3 tentativi con backoff [1, 3]s, timeout 15s.

### Nuovi metodi in `api/bridge.py`

Paralleli ai metodi Beatport (stesso schema):

- `traxsource_genres() → list[dict]`
- `traxsource_fetch_chart(slug, force_refresh) → {ok, tracks} | {ok:false, error, message}` — salva anche `traxsource_last_genre` in config
- `traxsource_check_existing(tracks, genre_name) → list[bool]` — check in `<output_dir>/Traxsource_<genre>/`
- `traxsource_download_selected(tracks, genre_name) → dict` — costruisce metadata (title/artist/album=label/date=YYYY-MM/genre=display_name/cover_url) e chiama `start_tracks_download` riusando il pipeline con tagging ID3

**Metadata per il tagger:**
- title, artist: dai campi track
- album: label Traxsource (best proxy — non c'è "album" per singole tracce)
- date: mese/anno corrente (dato che la Top 100 è mensile)
- genre: display_name del genere
- cover_url: `cover_url_large` (500x500)

### Frontend

Nuova tab in sidebar dopo YouTube (o Beatport):
```html
<button class="nav-item" data-view="traxsource" data-feature="audio">
  <span class="nav-icon">▲</span><span>Traxsource</span>
</button>
```

Section `#view-traxsource` con struttura identica a Beatport (dropdown genere + Carica Top 100 + tabella + toolbar + log). Riusa tutte le classi `.beatport-*` per lo stile.

Modulo `TraxsourceUI` in `webui/js/app.js` — copia diretta di `BeatportUI` con selettori cambiati (`traxsource-*` invece di `beatport-*`) e chiamate API alle nuove funzioni.

**Ordinamento colonne** (sortable) e **cover art** già supportati riusando la stessa struttura tabella + modulo helper `_sortPairs`/`_bindSortableHeaders`/`_updateSortArrows` esistenti.

### Persistenza

Nuovo campo in `core/config.py::DEFAULTS`:
```python
"traxsource_last_genre": "tech-house",
```

### Dipendenze

- `beautifulsoup4` — nuova dep runtime. Aggiungere in `requirements.txt`. Serve `--collect-data bs4` in build_windows.py + build_macos.py? Verificare — bs4 di solito no.

## Testing

**Unit tests `tests/test_traxsource.py` (senza rete, con fixture HTML):**

Serve una fixture HTML reale della pagina Top 100 (~400KB). Task 1 la genera con `curl_cffi` come fatto per Beatport (`beatport_melodic_top100.html`).

| Test | Verifica |
|---|---|
| `test_list_genres_shape` | Lista dict con {slug, id, name}, ordinati |
| `test_parse_top100_extracts_100_tracks` | Fixture HTML → 100 track |
| `test_parse_positions_sequential` | 1..100 senza buchi |
| `test_parse_track_shape` | Ogni track ha title, artists, label, cover URLs non vuoti |
| `test_split_title_mix_with_parens` | `"Foo (Extended Mix)"` → `("Foo", "Extended Mix")` |
| `test_split_title_mix_no_parens` | `"Foo"` → `("Foo", "")` |
| `test_format_artists_multi` | `["A", "B", "C"]` → `"A, B & C"` |
| `test_large_cover_url_substitution` | `.../52x52/x.jpg` → `.../500x500/x.jpg` |
| `test_discover_top100_url_returns_playlist_link` | HTML genre stub → estrae `/title/N/top-100-...` |
| `test_fetch_top100_invalid_slug_raises_value_error` | slug non in GENRES → ValueError early |

Mock HTTP con `unittest.mock.patch("core.traxsource._session")` (patch della session singleton).

**Test manuale end-to-end:**
1. Avvia app → tab Traxsource
2. Selezione "Tech House" → Carica Top 100 → tabella 100 righe in <5s
3. Verifica cover art (thumbnail nella tabella)
4. Deseleziona 90, tieni 10 → Scarica selezionati
5. File in `MUSICA/Traxsource_Tech House/` con tag ID3 completi (title, artist, album=label, genre=Tech House, cover 500x500)
6. Ricarica stesso genere → cache hit
7. Riavvio → ultimo genere ricordato

## Rollout

1. Branch `feat/traxsource-charts`
2. Bump `core/config.py::VERSION` → `v1.9.0` (minor: nuova tab visibile)
3. Note release `/tmp/notes-v1.9.0.md`
4. Merge → tag → CI → server DB update (stesso flusso di sempre)

## Struttura file impattati

**Nuovi:**
- `core/traxsource.py` (~250 LOC)
- `tests/test_traxsource.py` (~200 LOC)
- `tests/fixtures/traxsource_tech_house_top100.html` (~400KB)
- `scripts/refresh_traxsource_genres.py` (~50 LOC, opzionale)

**Modificati:**
- `requirements.txt` — `beautifulsoup4>=4.12.0`
- `build_windows.py` + `build_macos.py` — verificare se serve `--collect-data bs4`
- `core/config.py` — VERSION bump + `traxsource_last_genre`
- `api/bridge.py` — 4 metodi Api `traxsource_*` (~150 LOC)
- `webui/index.html` — nav-item + section (~90 LOC)
- `webui/js/app.js` — modulo `TraxsourceUI` (~250 LOC, copia BeatportUI adattata)

## Considerazioni operative

- **Fragility scraping:** i class name di Traxsource (`com-title`, `com-artists`, `top-item`, ecc.) sono usati anche nel JS del sito → stabili nel tempo. Rischio: se Traxsource migra a un framework nuovo (React/Next), parser va rifatto.
- **Rate limiting:** un solo GET per la genre + un GET per la playlist Top 100 = 2 richieste per caricare la chart. Cache 15 min. Zero rischio ban in uso normale.
- **Legal:** stesso perimetro di Beatport — lettura di pagine pubbliche, no ToS violation esplicito.
- **Comparabilità con Beatport:** un utente power potrebbe usare entrambe le tab per triangolare le release del mese. UX consistente = curva apprendimento zero.
