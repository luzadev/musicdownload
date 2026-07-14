# Music Search (Spotify + YouTube) — Design Spec

- **Data:** 2026-07-14
- **Autore:** LuZa + Claude
- **Stato:** Approvato, pronto per implementation plan
- **Target release:** MusicTools v1.8.1

## Obiettivo

Aggiungere due tab distinte all'app che permettano di **cercare brani/artisti/parole libere** e scaricarli:

1. **Tab 🟢 Spotify** — ricerca via Spotify API (canonica, metadata pulita). Toggle "Solo artista" per ottenere tutta la discografia di un artista invece della ricerca libera.
2. **Tab ▶ YouTube** — ricerca diretta via `yt-dlp ytsearch:` (grezza, senza distinzione artista/album, ma copre mix DJ, unreleased, bootleg, live, video-only content).

Il download in entrambi i casi riusa la pipeline esistente (`start_tracks_download` in `api/bridge.py`) con licenza gate `_gate("audio")`.

## Non-goals

- Un'unica tab "Cerca" con radio Spotify/YouTube (scartato: UX molto diversa per le due sorgenti)
- Ricerca combinata Spotify+YouTube in un'unica lista (nessuna deduplica cross-source affidabile)
- Playlist temporanee salvabili
- Preview audio
- Filtri per genere/anno/BPM (non richiesto, YAGNI)
- Ricerca album, artisti, playlist su Spotify (limitata a track)
- Autocomplete / suggestions come digiti

## Approcci scelti

### Spotify

- Free-form search: `GET /v1/search?q=<query>&type=track&limit=50`
  - Ritorna fino a 50 track ordinati per rilevanza/popolarità (default Spotify)
  - Query può essere qualsiasi cosa: titolo, artista, "artista - titolo", parola singola
- Artist-mode (toggle attivo):
  1. `GET /v1/search?q=<query>&type=artist&limit=5` → prendi il match con `name.lower() == query.lower()` altrimenti il più popolare
  2. `GET /v1/artists/{id}/top-tracks?market=IT` → ~10 top track
  3. `GET /v1/artists/{id}/albums?include_groups=album,single&limit=50&market=IT` → lista album
  4. Per ogni album (max 50): `GET /v1/albums/{id}/tracks?limit=50` → tracce
  5. Deduplica su `(name.lower().strip() + '|' + first_artist.lower().strip())`
  6. Rate limit interno: `time.sleep(0.1)` tra chiamate `/albums/{id}/tracks`
  7. Total: ~100-500 track per artista prolifico

**Vantaggi:** metadata pulita, download pipeline già rodata (Spotify→YouTube via yt-dlp).

### YouTube

- `yt-dlp --flat-playlist --dump-single-json "ytsearch50:<query>"` → JSON con `entries[]`
- Per ogni entry: `{title, uploader/channel, duration, id, url}`
- Nessuna modalità artista (YouTube search non ha channel-exact disambiguation affidabile)

**Vantaggi:** trova ciò che Spotify non ha (mix, unreleased, bootleg, live).

## Architettura

### Nuovi moduli / estensioni

#### `core/spotify_client.py` (estensione)

```python
def search_tracks(token: str, query: str, limit: int = 50) -> list:
    """Ricerca free-form. Ritorna list[dict] con {id, url, name, artists, album, duration_sec}."""

def search_artist_discography(token: str, artist_name: str) -> list:
    """Trova l'artista esatto e ritorna tutti i suoi brani (top tracks + tracce da album/singles).
    Deduplica per (title, first_artist) normalizzato. Solleva ValueError se nessun artista trovato."""
```

Nota: la funzione `search_track` (singolare) aggiunta in Task 7 di Beatport resta com'è per retro-compatibilità. La nuova `search_tracks` (plurale, con limit) è quella usata da questa feature.

#### `core/youtube_search.py` (nuovo)

```python
def search_youtube(query: str, limit: int = 50) -> list:
    """Cerca su YouTube via `yt-dlp ytsearchN:query`.
    Ritorna list[dict] con {id, url, title, channel, duration_sec}."""
```

Riusa `find_ytdlp()` e `subprocess_flags()` da `core/paths.py`. Timeout subprocess 30s.

#### `api/bridge.py` — nuovi metodi

- `spotify_search(query: str, artist_mode: bool) → dict` — salva query+toggle in config, poi chiama la funzione giusta e ritorna `{ok, tracks}` o `{ok:false, error, message}`
- `spotify_search_download(tracks: list) → dict` — wrapper del pattern Beatport: converte in `[{name, artist}]` e chiama `start_tracks_download` con `subfolder="Spotify"`
- `youtube_search(query: str) → dict` — salva query in config, chiama `core.youtube_search`, ritorna `{ok, tracks}`
- `youtube_search_download(tracks: list) → dict` — chiama nuovo helper `start_urls_download` (see below) con URL YouTube e `subfolder="YouTube"`

#### `api/bridge.py` — nuovo helper (se non c'è già)

- `start_urls_download(payload: dict) → dict` — analogo a `start_tracks_download` ma accetta `{urls: [str], output_dir, subfolder}` e chiama `download_playlist_from_urls(urls, ...)` in `core/downloader.py`. Se non esiste una funzione equivalente in `downloader.py`, va aggiunta.

  **Verifica in implementazione:** controlla se `download_playlist(tracks, ...)` può ricevere tracks contenenti solo `url` (bypass search); in tal caso riusa quella. Altrimenti aggiungi il nuovo path.

### Frontend

- 2 nuove tab in sidebar (`data-view="spotify"` e `data-view="youtube"`), entrambe con `data-feature="audio"` (stesso license gate del Beatport)
- 2 nuove section `<section id="view-spotify">` e `<section id="view-youtube">` in `webui/index.html`
- Modulo JS `SpotifyUI` e `YoutubeUI` in `webui/js/app.js`, entrambi con pattern init/loadResults/renderTable/updateSelection/startDownload (parallelo a `BeatportUI`)
- Stili in `webui/css/style.css` — riusa `.beatport-table` come base, aggiunge varianti dove serve

### Persistenza

3 nuovi campi in `core/config.py::DEFAULTS`:
- `spotify_search_last_query: str = ""`
- `spotify_search_artist_mode: bool = False`
- `youtube_search_last_query: str = ""`

Salvati dal backend a ogni ricerca (analogo a `beatport_last_genre`).

### Cartelle output

- `{output_dir}/Spotify/` (piatta, nessun sub-folder per query)
- `{output_dir}/YouTube/` (piatta)

Sanitizzazione slash coerente con il pattern di `start_tracks_download` (subfolder singolo, no nested).

## Data flow

### Spotify search

```
[JS] User digita query, opzionale toggle "Solo artista", click Cerca
  ↓
[JS] api.spotify_search(query, artist_mode)
  ↓
[PY] api/bridge.py::spotify_search():
    ├─ Salva {spotify_search_last_query, spotify_search_artist_mode} in config
    ├─ Verifica creds Spotify (client_id, client_secret) → altrimenti {ok:false, error:"no_creds"}
    ├─ Get token (spotify_client.get_access_token)
    ├─ Se artist_mode:
    │   └─ spotify_client.search_artist_discography(token, query)
    ├─ Altrimenti:
    │   └─ spotify_client.search_tracks(token, query, limit=50)
    └─ Ritorna {ok:True, tracks: [...]}
  ↓
[JS] Riceve lista, chiama api.spotify_check_existing() per pre-deselezionare i già-scaricati
  ↓
[JS] Renderizza tabella (colonne: check, #, artista, titolo, album, durata, stato)
  ↓
[JS] User seleziona, click "Scarica selezionati"
  ↓
[JS] api.spotify_search_download(tracks_selected)
  ↓
[PY] converte in [{name, artist}] e chiama self.start_tracks_download({..., subfolder: "Spotify"})
  ↓
[EXISTING] pipeline yt-dlp, log/progress su canale "download"
```

### YouTube search

```
[JS] User digita query, click Cerca
  ↓
[JS] api.youtube_search(query)
  ↓
[PY] api/bridge.py::youtube_search():
    ├─ Salva youtube_search_last_query in config
    ├─ core.youtube_search.search_youtube(query, limit=50)
    │   └─ subprocess: yt-dlp --flat-playlist --dump-single-json "ytsearch50:<query>"
    └─ Ritorna {ok:True, tracks: [{id, url, title, channel, duration_sec}, ...]}
  ↓
[JS] Renderizza tabella (colonne: check, #, titolo video, canale, durata, stato)
  ↓
[JS] User seleziona, click "Scarica selezionati"
  ↓
[JS] api.youtube_search_download(tracks_selected)  # passa URL, non {name,artist}
  ↓
[PY] start_urls_download({urls, subfolder: "YouTube"})
  ↓
[EXISTING] pipeline yt-dlp diretto sugli URL
```

## Matrice errori & recovery

| Errore | Dove | Comportamento |
|---|---|---|
| Query vuota | UI JS | Bottone "Cerca" disabilitato, nessuna richiesta |
| Creds Spotify mancanti | spotify_search | `{ok:false, error:"no_creds"}` → banner giallo con link Impostazioni |
| Spotify 401 (token scaduto/invalid) | get_access_token | Refresh token nel handler; se persiste, banner rosso |
| Spotify 429 rate limit | search endpoint | `{ok:false, error:"rate_limit", message:"Attendi qualche secondo"}` → banner arancione, retry manuale |
| Spotify 5xx | search endpoint | `{ok:false, error:"server", message:...}` → banner rosso, retry |
| Nessun risultato Spotify | search endpoint | `{ok:true, tracks:[]}` → messaggio grigio "Nessun brano trovato per '<query>'" |
| Artist-mode senza match esatto | search_artist_discography | Solleva ValueError → `{ok:false, error:"artist_not_found", message:"Artista '<q>' non trovato — disattiva toggle per ricerca libera"}` |
| yt-dlp non trovato | search_youtube | RuntimeError → banner rosso "yt-dlp non installato" |
| yt-dlp timeout (rete lenta) | search_youtube | subprocess.TimeoutExpired → banner rosso "Timeout ricerca YouTube" |
| yt-dlp errore generico | search_youtube | Non-zero exit → banner rosso con stderr tail |
| Nessun risultato YouTube | search_youtube | `{ok:true, tracks:[]}` → messaggio grigio |
| User preme Stop durante download | download pipeline | Comportamento invariato (esistente) |

## Licenza / piani

Entrambe le tab sono audio download → gate `_gate("audio")` automatico via `start_tracks_download` / `start_urls_download`. Il `daily_limit` del piano si applica. Nessuna nuova feature-flag.

## Testing

### Unit tests

**`tests/test_spotify_client.py` (estensione):**
- `test_search_tracks_returns_list_up_to_limit` — mock response con 50 items, verifica list length
- `test_search_tracks_maps_fields_correctly` — sample dict → verifica keys {id, url, name, artists, album, duration_sec}
- `test_search_tracks_empty_query_returns_empty` — mock 0 items
- `test_search_artist_discography_exact_match_wins` — mock search artist con 3 candidati diversi, verifica quello esatto (case-insensitive)
- `test_search_artist_discography_top_tracks_and_albums_combined` — mock 3 endpoint, verifica deduplica
- `test_search_artist_discography_raises_when_no_match` — mock search artist con 0 risultati → ValueError
- `test_search_artist_discography_deduplicates` — mock top-tracks e album-tracks con overlap → verifica no duplicati

**`tests/test_youtube_search.py` (nuovo):**
- `test_search_youtube_parses_entries` — mock `subprocess.run` con JSON stub (5 entries), verifica list mapping
- `test_search_youtube_empty_result` — mock JSON senza entries → []
- `test_search_youtube_ytdlp_not_found` — mock `find_ytdlp` che ritorna None → RuntimeError
- `test_search_youtube_timeout` — mock subprocess.TimeoutExpired → RuntimeError

### Test manuale end-to-end

**Tab Spotify:**
1. Query semplice: "Solomun" senza toggle → 50 risultati, ordinati per rilevanza
2. Query composta: "Kapuchon Hot Sauce" → 5-10 risultati pertinenti
3. Artist mode: "Solomun" con toggle attivo → 100-300 risultati (top tracks + tutti album)
4. Artist mode con nome inesistente: "sadgjhkasdg" → banner "Artista non trovato"
5. Download di 3 brani → file in `MUSICA/Spotify/`
6. Ricerca ripetuta → "già scaricato" mostrato correttamente
7. Riavvio app → ultima query + toggle ricordati

**Tab YouTube:**
1. Query: "Kapuchon Hot Sauce" → 50 risultati con canali diversi
2. Query set DJ: "Solomun Cocoricò 2024" → set lunghi (60+ min) in lista
3. Download di 2 brani → file in `MUSICA/YouTube/`
4. Query vuota → bottone disabilitato
5. Riavvio → ultima query ricordata

## Rollout

1. Branch `feat/music-search`
2. Bump `core/config.py::VERSION` → `v1.8.1`
3. Note release `/tmp/notes-v1.8.1.md`:
   > **Nuove tab Spotify e YouTube 🔎** — cerca brani per titolo o artista su Spotify (con toggle "solo artista" per scaricare tutta la discografia), oppure cerca su YouTube per trovare mix DJ, unreleased, bootleg e brani non presenti su Spotify.
4. Commit + tag `v1.8.1` → CI + release notes background task
5. Update DB `releases` tabella sul server (macos + windows rows)

Zero cambi server-side backend, zero migration.

## Struttura file impattati

**Nuovi:**
- `core/youtube_search.py`
- `tests/test_youtube_search.py`

**Modificati:**
- `core/spotify_client.py` — 2 nuove funzioni pubbliche (`search_tracks`, `search_artist_discography`)
- `core/downloader.py` — se serve, aggiunta `download_playlist_from_urls()` per il flusso YouTube
- `core/config.py` — VERSION bump + 3 nuovi campi in DEFAULTS
- `api/bridge.py` — 6 nuovi metodi Api: `spotify_search`, `spotify_check_existing`, `spotify_search_download`, `youtube_search`, `youtube_check_existing`, `youtube_search_download` + eventuale helper `start_urls_download`
- `tests/test_spotify_client.py` — 7 nuovi test
- `webui/index.html` — 2 nav-item + 2 sezioni view
- `webui/js/app.js` — moduli `SpotifyUI` e `YoutubeUI` (~200 righe cadauno, parallelo a `BeatportUI`)
- `webui/css/style.css` — piccole estensioni (o riuso classi Beatport)
- `requirements.txt` — nessuna nuova dep

## Riduzione della duplicazione

Se durante l'implementazione emerge che i 3 pannelli (Beatport, Spotify, YouTube) hanno logica JS quasi identica (renderTable con checkbox, updateSelectionCount, startDownload wrapper), **valuta** l'estrazione di un `SelectableTracksTable` component in `webui/js/app.js`. Se l'astrazione è chiara e riduce codice significativamente, fallo. Se costringe a hooks/callbacks tortuosi per gestire differenze di colonne, lascia stare — 3 istanze non sono tante e YAGNI.
