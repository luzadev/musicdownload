# MusicDownload

Applicazione desktop per **scaricare musica e video**, **modificare i metadati** dei file audio e **registrare l'audio** da qualsiasi ingresso del computer.

UI moderna basata su **pywebview** (WebKit su macOS, EdgeChromium su Windows) — frontend HTML/CSS/JS, backend Python.

Sviluppata da **LuZa**.

Repo: <https://github.com/luzadev/musicdownload>

## Funzionalità

| Tab | Cosa fa |
|---|---|
| **⬇ Scarica** | Spotify (playlist/album/brano) · YouTube · SoundCloud · lista URL `.txt` · tracklist `.txt` con titoli (es. Beatport Top 100) |
| **🎬 Video** | YouTube · TikTok · Instagram · Facebook (e 1000+ siti yt-dlp) in MP4, qualità best/1080p/720p/480p |
| **⚡ Upgrade** | Scansiona una cartella audio e riscarica i file sotto la soglia kbps impostata |
| **🏷 Metadati** | Editor tag ID3 / MP4 / Vorbis (MP3, M4A, FLAC, WAV) — titolo, artista, album, anno, copertina, BPM, key, commento, origine (macOS) |
| **● Registra** | Cattura audio in MP3 320 kbps da qualsiasi ingresso (mixer, scheda audio, microfono, BlackHole/loopback) |
| **⚙ Impostazioni** | Credenziali Spotify, bitrate, soglia HQ, percorsi, tema, controllo aggiornamenti |

### Auto-skip dei duplicati

Tracking persistente (`.downloaded_tracks` / `.downloaded_videos`) + scan filename token-based: re-eseguire la stessa playlist salta i brani già presenti, anche se il filename ha `Official Video` / `Lyrics` / ecc.

### Sottocartella automatica per le tracklist

Se carichi un file `.txt` con titoli (es. `Beatport Top 100 Melodic House & Techno.txt`), l'app crea automaticamente una sottocartella `<output_dir>/Beatport Top 100 Melodic House & Techno/` per non mischiare brani di playlist diverse.

## Requisiti

- Python 3.8+
- `ffmpeg` + `ffprobe` (solo per build/sviluppo locale: `brew install ffmpeg` su macOS)
- Credenziali Spotify API gratuite — solo se si usano URL Spotify

Nelle build distribuite (`.app` / `.exe`) **tutto è incluso** — non serve installare nulla.

## Installazione (sviluppo)

```bash
git clone https://github.com/luzadev/musicdownload.git
cd musicdownload
pip install -r requirements.txt
python3 main.py
```

Dipendenze principali:

| Pacchetto | Utilizzo |
|---|---|
| `pywebview` | Finestra nativa con WebView (WebKit / EdgeChromium) |
| `requests` | Chiamate API Spotify e GitHub |
| `yt-dlp` | Download audio/video da YouTube e oltre 1000 siti |
| `mutagen` | Lettura/scrittura tag ID3, MP4, FLAC, WAV |
| `pyobjc-framework-WebKit` (macOS) | Backend WebKit di pywebview |
| `pythonnet` (Windows) | Backend EdgeChromium di pywebview |

## Credenziali Spotify API

Necessarie solo per scaricare da URL `open.spotify.com/...`.

1. Vai su <https://developer.spotify.com/dashboard> e accedi (anche account gratuito)
2. Clicca **Create app**
3. Compila: nome a piacere, Redirect URI `http://localhost:8888/callback`, seleziona **Web API**
4. Apri la app e clicca **Settings**
5. Copia **Client ID** e **Client Secret** nelle Impostazioni dell'app

Le credenziali sono gratuite, non servono Spotify Premium.

## Cookies per contenuti privati

Per scaricare **Instagram / Facebook privati** o aggirare il rate-limit di YouTube serve un file `cookies.txt` (formato Netscape). Esportalo dal browser con un'estensione tipo "Get cookies.txt LOCALLY" e imposta il percorso in **Impostazioni → Percorsi**.

## Guida rapida: registrazione audio di sistema (macOS)

macOS non espone nativamente l'output audio del sistema. Per registrare quello che esce dagli speaker (es. uno stream Spotify/YouTube), serve un driver virtuale di **loopback**. Il più diffuso è **BlackHole**, gratuito e open source.

### 1. Installazione

```bash
brew install blackhole-2ch
```

> Subito dopo l'installazione, se non vedi BlackHole nella tab Registra, riavvia il servizio audio:
> ```bash
> sudo killall coreaudiod
> ```
> Si rilancia da solo in pochi secondi, nessun danno. In alternativa, logout/login o riavvio del Mac.

### 2. Permesso Microfono

Anche se non è un microfono fisico, macOS richiede il permesso "Microfono" per leggere da BlackHole via AVFoundation.

Vai su **Preferenze di Sistema → Privacy e sicurezza → Microfono** e abilita l'app da cui lanci MusicDownload (Terminal/iTerm in sviluppo, oppure MusicDownload.app per la build distribuita). Se non vedi nessuna voce, comparirà un popup la prima volta che premi REC — accetta.

### 3. Setup A — minimo (registri ma non senti l'audio durante)

1. Click sull'icona altoparlante nella barra menu → **Output → BlackHole 2ch**
   *Oppure: Preferenze di Sistema → Audio → Uscita → BlackHole 2ch*
2. Fai partire lo stream (Spotify/YouTube): non sentirai nulla — è normale, l'audio va a BlackHole
3. App MusicDownload → tab **● Registra** → dispositivo **🔄 BlackHole 2ch (loopback)** → **REC**
4. **Stop** e riascolta il file MP3 generato

### 4. Setup B — completo (registri E senti l'audio contemporaneamente, consigliato)

1. Apri **Configurazione MIDI Audio** (`Applicazioni → Utility → Configurazione MIDI Audio`)
2. In basso a sinistra: **+ → Crea dispositivo aggregato a uscita multipla** (Multi-Output Device)
3. Nella colonna a destra, spunta sia **BlackHole 2ch** sia i tuoi **Altoparlanti integrati** (o le cuffie)
4. Imposta **BlackHole 2ch** come **Master Device** (menù a tendina in alto)
5. Abilita **Drift Correction** sulla riga degli altoparlanti
6. (Opzionale) Rinomina il dispositivo aggregato in `Speakers + BlackHole`
7. **Preferenze di Sistema → Audio → Uscita** → seleziona `Speakers + BlackHole`
8. Nella tab Registra dell'app scegli **🔄 BlackHole 2ch (loopback)** — **NON il dispositivo aggregato**, quello è solo per riprodurre

Adesso ogni audio del sistema viene riprodotto sugli speaker (lo senti) e contemporaneamente catturato da BlackHole (viene registrato).

### Troubleshooting

| Sintomo | Causa probabile | Fix |
|---|---|---|
| BlackHole non compare nel dropdown | CoreAudio non l'ha ancora caricato dopo l'install | `sudo killall coreaudiod` poi premi **↻ Aggiorna** |
| Errore `ffmpeg exit -6` o `permesso Microfono mancante` | macOS nega l'accesso al device | Privacy e sicurezza → Microfono → abilita Terminal/MusicDownload |
| File MP3 muto | Output di sistema non passa per BlackHole | Cambia output su BlackHole o Multi-Output Device (vedi Setup A/B) |
| Audio doppio/eco nel file | Stai registrando da BlackHole *e* da microfono fisico simultaneamente | Verifica che nel dropdown ci sia solo `BlackHole 2ch` |
| Audio crackly/distorto | Sample rate non allineato | In Audio MIDI Setup, BlackHole + altoparlanti tutti a 48 kHz |

## Struttura progetto

```
MusicDownload/
├── main.py                  # Entry point — bootstrap pywebview
├── requirements.txt
├── build_macos.py           # Script build macOS (.app)
├── build_windows.py         # Script build Windows (.exe)
├── .github/workflows/
│   └── build.yml            # CI: build macOS + Windows + Release automatica su tag
│
├── core/                    # Logica backend (riusabile, no UI)
│   ├── config.py            # Configurazione persistente (JSON)
│   ├── paths.py             # Ricerca binari (yt-dlp, ffmpeg)
│   ├── spotify_client.py    # API Spotify (Client Credentials)
│   ├── downloader.py        # Download audio + video (Spotify, yt-dlp diretto)
│   ├── upgrader.py          # Upgrade qualità file esistenti
│   ├── metadata.py          # Lettura/scrittura tag ID3/MP4/Vorbis/WAV
│   └── recorder.py          # Registrazione audio via ffmpeg
│
├── api/
│   └── bridge.py            # Ponte JS <-> Python (pywebview.js_api)
│
└── webui/                   # Frontend
    ├── index.html           # Single-page, 6 view
    ├── css/style.css        # Tema scuro Spotify-like, gradient hero, animazioni
    └── js/app.js            # Routing, eventi, chiamate API
```

## Configurazione

Il file `config.json` viene creato automaticamente al primo avvio:

| Chiave | Default | Descrizione |
|---|---|---|
| `client_id` | `""` | Spotify Client ID |
| `client_secret` | `""` | Spotify Client Secret |
| `bitrate` | `"320K"` | Bitrate download audio (128K/192K/256K/320K) |
| `hq_threshold` | `310` | Soglia kbps per considerare un file HQ |
| `cookies_path` | `""` | Path al file `cookies.txt` (opzionale) |
| `output_dir` | `""` | Cartella output predefinita |
| `theme` | `"dark"` | Tema interfaccia |

Posizione:
- **Sviluppo**: directory del progetto
- **macOS bundle**: `~/Library/Application Support/MusicDownload/`
- **Windows bundle**: `%APPDATA%/MusicDownload/`

## Build locale

### macOS

```bash
brew install ffmpeg
pip install pyinstaller
python3 build_macos.py
```

Produce `dist/MusicDownload.app` con yt-dlp, ffmpeg, ffprobe e tutte le dylib bundled (rpath patchati con `install_name_tool`).

### Windows

```bash
pip install pyinstaller
python build_windows.py
```

Produce `dist/MusicDownload/MusicDownload.exe`. Lo script scarica automaticamente `yt-dlp.exe` e `ffmpeg.exe`/`ffprobe.exe` static build.

## Build & Release automatiche (GitHub Actions)

Ogni push di un tag `v*` triggera la pipeline `.github/workflows/build.yml`:

1. **`build-macos`** (runner `macos-latest`) → `MusicDownload-macOS.zip` (la `.app` zippata con `ditto`)
2. **`build-windows`** (runner `windows-latest`) → `MusicDownload-Windows.zip`
3. **`release`** → crea automaticamente una GitHub Release con entrambi gli asset allegati

Per pubblicare una nuova versione:

```bash
git tag v1.3.0
git push origin v1.3.0
```

Per fare solo una build di test (senza release):

```bash
gh workflow run "Build MusicDownload" --ref main
```

oppure dalla UI: **Actions → Build MusicDownload → Run workflow**.

Le release ufficiali sono disponibili su <https://github.com/luzadev/musicdownload/releases>.

## Aggiornamento app

L'app verifica nuove versioni interrogando l'API GitHub Releases (`api/bridge.py` → `check_update`). Per funzionare end-to-end serve che il repo sia pubblico, altrimenti l'API restituisce 404.

## Licenza

Uso personale.
