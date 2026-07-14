# Beatport Charts — Design Spec

- **Data:** 2026-07-14
- **Autore:** LuZa + Claude
- **Stato:** Approvato, pronto per implementation plan
- **Target release:** MusicTools v1.8.0

## Obiettivo

Aggiungere una nuova tab all'app desktop MusicTools che permetta di:

1. Scegliere un genere musicale da un elenco di ~30 generi Beatport
2. Caricare la classifica **Top 100** ufficiale di quel genere dal sito Beatport
3. Visualizzare i 100 brani in tabella con checkbox per scegliere quali scaricare
4. Scaricare i brani selezionati riusando il flusso esistente Spotify search → yt-dlp

Sostituisce il lavoro manuale attuale (l'utente copia/incolla la Top 100 in un file `.txt` che poi passa al downloader).

## Non-goals

Esplicitamente **fuori scope** in questa versione:

- Preview audio dei brani (snippet Beatport sono DRM protetti)
- Chart diverse dalla Top 100 (Hype 100, DJ Charts, weekly picks) — rinviato a v2
- Ricerca / filtro nella tabella (100 righe si scorrono senza)
- Refresh automatico della classifica
- Esportazione della lista come file `.txt`
- Auto-update della mappa dei generi (resta hardcoded, aggiornata a ogni release)
- Beatport account / login / preferiti utente

## Approccio scelto — Parse `__NEXT_DATA__`

Beatport è costruito su Next.js. Ogni pagina di classifica include un tag `<script id="__NEXT_DATA__" type="application/json">…</script>` con il payload completo della pagina in JSON strutturato: id, artist, title, mix, duration, chart position, label, key, BPM. Il parser:

1. `GET https://www.beatport.com/genre/<slug>/<id>/top-100` con User-Agent browser
2. `re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html)` per estrarre il JSON
3. `json.loads` + walk fino ai 100 track object
4. Mappa in dataclass `BeatportTrack`

**Vantaggi:** dati strutturati, robusto ai cambi di layout CSS, un solo GET per 100 brani.

**Alternative scartate:**
- BeautifulSoup su CSS class → i class name Next.js sono hash generati, si rompono a ogni build Beatport
- API interna `api.beatport.com` → richiede OAuth token, User-Agent specifici, ToS espressamente vietano l'uso non autorizzato → rischio ban

## Architettura

### Nuovi moduli

#### `core/beatport.py` (nuovo)

```python
from dataclasses import dataclass
from typing import Optional

GENRES: dict[str, tuple[int, str]] = {
    "melodic-house-techno": (90, "Melodic House & Techno"),
    "techno-peak-time-driving": (6, "Techno (Peak Time / Driving)"),
    "techno-raw-deep-hypnotic": (92, "Techno (Raw / Deep / Hypnotic)"),
    "deep-house": (12, "Deep House"),
    "tech-house": (11, "Tech House"),
    "progressive-house": (15, "Progressive House"),
    "house": (5, "House"),
    "afro-house": (89, "Afro House"),
    "organic-house-downtempo": (93, "Organic House / Downtempo"),
    "trance": (7, "Trance"),
    "drum-bass": (1, "Drum & Bass"),
    "dubstep": (18, "Dubstep"),
    "minimal-deep-tech": (14, "Minimal / Deep Tech"),
    "indie-dance": (37, "Indie Dance"),
    # NOTA: la mappa completa (~30 slug/id) va enumerata in fase di
    # implementazione recuperando gli slug + numeric id dalla pagina
    # https://www.beatport.com/genres — lo script che li estrae va
    # committato in `scripts/refresh_beatport_genres.py` per potervi
    # rifare la refresh a mano quando Beatport aggiunge/rimuove generi.
}

@dataclass(frozen=True)
class BeatportTrack:
    position: int
    title: str
    mix: str
    artists: str          # "A, B & C" già formattato
    duration_sec: int
    beatport_id: int

    @property
    def display(self) -> str:
        """Formato compatibile con i file .txt esistenti:
        'Artista – Titolo (Mix) (M:SS)'"""
        m, s = divmod(self.duration_sec, 60)
        return f"{self.artists} – {self.title} ({self.mix}) ({m}:{s:02d})"

    @property
    def spotify_query(self) -> str:
        return f"{self.artists} {self.title}"


class BeatportError(Exception): pass
class BeatportUnreachableError(BeatportError): pass
class BeatportParseError(BeatportError): pass


def fetch_top100(slug: str, force_refresh: bool = False) -> list[BeatportTrack]:
    """Fetches Top 100 per il genere. Cache in-memory 15 min.
    Solleva ValueError se slug non valido, BeatportUnreachableError su rete,
    BeatportParseError su schema cambiato."""
    ...

def list_genres() -> list[dict]:
    """Ritorna [{slug, id, name}, ...] ordinato alfabeticamente per name."""
    ...
```

Cache in-memory: `dict[slug, tuple[timestamp, list[BeatportTrack]]]`, TTL 900s.

Retry: 2 tentativi con backoff 1s, 3s.

User-Agent: `"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"` (aggiornato per release).

#### `main.py` — nuove API pywebview esposte al JS

```python
class Api:
    # …esistenti

    def beatport_genres(self) -> list[dict]:
        return beatport.list_genres()

    def beatport_fetch_chart(self, slug: str, force_refresh: bool = False) -> dict:
        try:
            tracks = beatport.fetch_top100(slug, force_refresh=force_refresh)
            return {"ok": True, "tracks": [asdict(t) for t in tracks]}
        except ValueError as e:
            return {"ok": False, "error": "invalid_genre", "message": str(e)}
        except BeatportUnreachableError as e:
            return {"ok": False, "error": "unreachable", "message": str(e)}
        except BeatportParseError as e:
            return {"ok": False, "error": "parse", "message": str(e)}

    def beatport_check_existing(self, tracks: list[dict], genre_name: str) -> list[bool]:
        """Ritorna una lista di boolean: True se il file esiste già in output_dir/Beatport/<Genre>/."""
        ...

    def beatport_download_selected(
        self,
        tracks: list[dict],
        genre_name: str,
    ) -> None:
        """Loop: per ogni track, spotify search → downloader.
        Emette log/progress sugli stessi eventi degli altri download."""
        ...
```

### Riuso codice esistente

- `core/spotify_client.py`: usa `search_track(query) -> Optional[str]` per ottenere lo Spotify URI (o il track object). **Da verificare in fase di implementazione** se il metodo esiste già come funzione pubblica riutilizzabile — se no, estrai la logica di search dal path esistente `download_from_spotify_url` in una funzione pubblica dedicata (refactor mirato, no cambi di comportamento per gli altri consumatori).
- `core/downloader.py`: usa il path Spotify URI → yt-dlp esistente. `request_stop()` / `reset_stop()` già disponibili.
- `webui/js/app.js`: riusa il pattern log/progress già in uso per le altre tab.
- `core/config.py`: aggiunge un solo nuovo campo `beatport_last_genre: str` ai DEFAULTS.

### Frontend

**Nuova tab in `webui/index.html`:**

```html
<button data-tab="beatport" class="tab-btn">🎧 Beatport</button>
<section id="tab-beatport" class="tab-panel">
  <div class="beatport-header">
    <label>Genere:
      <select id="beatport-genre"></select>
    </label>
    <button id="beatport-load">Carica Top 100</button>
    <div id="beatport-output-info"></div>
  </div>

  <div id="beatport-status"></div>

  <table id="beatport-table" hidden>
    <thead>
      <tr>
        <th><input type="checkbox" id="beatport-select-all"></th>
        <th>#</th><th>Artista</th><th>Titolo</th><th>Durata</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <div class="beatport-toolbar" hidden>
    <span id="beatport-selected-count">0/0 selezionati</span>
    <button id="beatport-download">⬇ Scarica selezionati</button>
    <button id="beatport-stop" hidden>■ Interrompi</button>
  </div>

  <div id="beatport-log" class="log-area"></div>
</section>
```

**JavaScript in `webui/js/app.js`:** funzioni `beatportInit()`, `beatportLoadChart()`, `beatportRenderTable(tracks)`, `beatportUpdateSelection()`, `beatportStartDownload()`. Stato locale: `let currentChart = { slug, name, tracks: [] }`.

### Persistenza

- Ultimo genere selezionato → `config.beatport_last_genre`
- File scaricati → rilevati con `os.path.exists()` sul filename generato dal downloader (stesso pattern degli altri tab)
- Cache classifica → solo in-memory, si perde a restart (voluto)

### Percorso output

`{output_dir}/Beatport/{Genre Display Name}/`

Es. `/Users/luciano/MUSICA/Beatport/Melodic House & Techno/Kapuchon - Hot Sauce (Extended).mp3`

## Data flow

```
[JS] User seleziona genere, click "Carica Top 100"
  ↓
[JS] api.beatport_fetch_chart("melodic-house-techno")
  ↓
[PY] core/beatport.fetch_top100():
    ├─ Cache hit (< 15 min)? → ritorna cached
    └─ GET Beatport, estrai __NEXT_DATA__, parse, mappa in BeatportTrack[]
  ↓
[JS] Riceve lista, chiama api.beatport_check_existing() per pre-deselezionare i già-scaricati
  ↓
[JS] Renderizza tabella
  ↓
[JS] User seleziona/deseleziona, click "Scarica selezionati"
  ↓
[JS] api.beatport_download_selected(tracks_selected, genre_name)
  ↓
[PY] Loop su tracks:
    ├─ emit log "[i/N] Cerco su Spotify: <artista – titolo>"
    ├─ spotify_uri = spotify_client.search_track(track.spotify_query)
    ├─ Se None: emit ✗, continua
    ├─ emit log "[i/N] Download da YouTube…"
    ├─ downloader.download_from_spotify_uri(uri, output_dir=<beatport-subdir>)
    ├─ emit log "[i/N] ✓" o "[i/N] ✗ <motivo>"
    └─ Se stop_event.is_set(): break
```

## Matrice errori & recovery

| Errore | Dove | Cosa succede |
|---|---|---|
| Beatport 5xx / timeout | fetch_top100 | Retry ×2 con backoff 1s, 3s. Poi solleva `BeatportUnreachableError`. UI: banner rosso "Beatport irraggiungibile. Riprova." con retry |
| `__NEXT_DATA__` mancante / schema cambiato | fetch_top100 | Dump primi 500 char HTML in `~/Library/Logs/MusicTools/beatport-<ts>.log`, solleva `BeatportParseError`. UI: banner arancione "Impossibile leggere la classifica. Segnala il bug." |
| Genere non valido | fetch_top100 | `ValueError` early, nessuna richiesta di rete |
| Spotify search no match | download loop | Log riga singola, marca riga tabella ✗ "non trovato", continua |
| Spotify creds mancanti | download loop, primo brano | Interrompe subito, banner giallo con link a tab Impostazioni |
| yt-dlp fallisce | download loop | Log riga singola ✗, continua con il resto |
| Cartella output non scrivibile | pre-check prima del loop | Errore + banner rosso, non parte |
| User preme Stop | download loop | `stop_event.set()`, si ferma dopo il brano corrente |
| Cache stale | fetch_top100 | Shift+click su "Carica" invalida (`force_refresh=True`); comunque expira dopo 15 min |

## Rispetto Beatport / rate limiting

- Un solo GET per classifica (100 brani in un JSON)
- Cache 15 min → max 4 richieste/ora anche con click ripetuti
- User-Agent browser, no scraping massivo
- Zero rischio ban IP in uso normale

## Licenza / piani

La feature è un audio download a tutti gli effetti → il `daily_limit` del piano si applica automaticamente (ogni brano scaricato conta come 1). Il piano `basic` con limite 10/giorno può scaricare al massimo 10 brani dalla Top 100. **Nessuna nuova feature-flag in `server/src/plans.js`.** Il gating avviene già nel downloader esistente.

## Testing

### Unit tests — `tests/test_beatport.py`

Nessuna rete durante i test. Fixture: snapshot HTML reale della pagina Beatport in `tests/fixtures/beatport_melodic_top100.html`.

| Test | Verifica |
|---|---|
| `test_parse_next_data_extracts_100_tracks` | Il parser trova esattamente 100 track dall'HTML fixture |
| `test_track_shape` | Ogni track ha position, title, mix, artists, duration_sec, beatport_id |
| `test_positions_sequential` | Posizioni 1..100 senza buchi |
| `test_display_format_matches_txt_files` | `BeatportTrack.display` produce esattamente il formato dei file `.txt` attuali |
| `test_parse_missing_next_data_raises` | HTML senza `<script id="__NEXT_DATA__">` → `BeatportParseError` |
| `test_parse_malformed_json_raises` | `__NEXT_DATA__` con JSON rotto → `BeatportParseError` |
| `test_parse_schema_change_raises` | JSON valido ma senza `results[]` → `BeatportParseError` con contesto |
| `test_cache_hit_second_call` | 2 chiamate ravvicinate → una sola richiesta HTTP simulata |
| `test_cache_expires_after_15min` | Freeze time + 16min → nuova richiesta |
| `test_force_refresh_bypasses_cache` | `force_refresh=True` ignora cache anche fresca |
| `test_invalid_genre_slug_early_error` | Slug non in `GENRES` → `ValueError` senza toccare la rete |

### Test HTTP mockato

`responses` (o `httpx` mock) per verificare timeout, retry policy, User-Agent inviato.

### Test manuale end-to-end (obbligatorio prima del release)

1. Avvia MusicTools, apri tab Beatport
2. Seleziona "Melodic House & Techno" → click "Carica Top 100" → tabella si popola in <3s
3. Deseleziona 90 brani, lascia i primi 10 → click "Scarica selezionati (10)"
4. Verifica file .mp3 in `{output_dir}/Beatport/Melodic House & Techno/`, metadata Spotify complete
5. Ricarica lo stesso genere → cache hit (nessuna nuova request osservabile in dev tools)
6. Cambia genere → nuova fetch
7. Interrompi a metà download → si ferma pulito dopo il brano corrente
8. Riavvia app → dropdown ricorda l'ultimo genere

## Rollout

1. Branch `feat/beatport-charts` (opzionale — la feature è additive, zero rischi per il resto)
2. Bump `core/config.py` VERSION → `v1.8.0`
3. Note release in `/tmp/notes-v1.8.0.md`:
   > **Nuova tab Beatport 🎧** — carica le Top 100 per genere direttamente da Beatport e scarica i brani in un click. 30+ generi disponibili.
4. Commit + tag `v1.8.0` → CI builda macOS + Windows come da flusso standard
5. Zero cambi lato server (`~/api/`), zero migration DB

## Struttura file impattati

**Nuovi:**
- `core/beatport.py`
- `tests/test_beatport.py`
- `tests/fixtures/beatport_melodic_top100.html`

**Modificati:**
- `main.py` — 4 nuovi metodi `Api.beatport_*`
- `core/config.py` — VERSION bump + campo `beatport_last_genre` in DEFAULTS
- `core/spotify_client.py` — espone `search_track()` come funzione pubblica se non lo è già
- `webui/index.html` — nuovo tab button + section
- `webui/js/app.js` — funzioni `beatport*`
- `webui/css/*.css` — stile tabella e toolbar (riuso classi esistenti dove possibile)
- `requirements.txt` — nessuna nuova dipendenza runtime (`requests` è già presente per gli altri client HTTP; `__NEXT_DATA__` si estrae con `re.search` + `json.loads`, no BeautifulSoup necessario). Solo dev dep: `responses` per i test HTTP mockati se non già presente
