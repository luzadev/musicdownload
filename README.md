# MusicDownload

Applicazione desktop per scaricare musica da Spotify, YouTube, SoundCloud e qualsiasi sorgente supportata da yt-dlp, con possibilita di migliorare la qualita audio dei file esistenti.

Sviluppata da **LuZa**.

## Funzionalita

- **Download da Spotify** — Incolla un link a playlist, album o brano singolo: l'app risolve i brani via API Spotify e li scarica da YouTube in MP3
- **Download diretto** — Incolla un URL YouTube, SoundCloud o qualsiasi sorgente yt-dlp e scarica direttamente in MP3 (singoli video e playlist)
- **Upgrade qualita** — Scansiona una cartella di file audio e riscarica quelli a bassa qualita da YouTube
- **Aggiornamento app** — Controlla la disponibilita di nuove versioni direttamente dalle Impostazioni
- **Gestione impostazioni** — Credenziali Spotify, bitrate, soglia HQ, percorsi, tema

## Requisiti

- Python 3.8+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installato nel sistema (`brew install yt-dlp` su macOS)
- [ffmpeg](https://ffmpeg.org/) installato nel sistema (`brew install ffmpeg` su macOS)
- Credenziali Spotify API (gratuite, vedi sotto) — necessarie solo per URL Spotify

## Installazione

```bash
pip install -r requirements.txt
```

Dipendenze Python:

| Pacchetto | Utilizzo |
|---|---|
| `customtkinter` | GUI moderna basata su Tkinter |
| `requests` | Chiamate API Spotify |
| `yt-dlp` | Download audio da YouTube |
| `Pillow` | Gestione immagini (copertine) |

## Avvio

```bash
python3 main.py
```

## Credenziali Spotify API

1. Vai su https://developer.spotify.com/dashboard e accedi (anche account gratuito)
2. Clicca **Create app**
3. Compila: nome a piacere, Redirect URI `http://localhost:8888/callback`, seleziona **Web API**
4. Nella pagina dell'app, clicca **Settings**
5. Copia **Client ID** e **Client Secret** nelle Impostazioni dell'app

Le credenziali sono gratuite e non richiedono Spotify Premium.

## Struttura progetto

```
MusicDownload/
├── main.py                  # Entry point
├── requirements.txt         # Dipendenze Python
├── build_macos.py           # Script build macOS (.app)
├── build_windows.py         # Script build Windows (.exe)
│
├── core/                    # Logica backend
│   ├── config.py            # Configurazione persistente (JSON)
│   ├── paths.py             # Ricerca binari (yt-dlp, ffmpeg)
│   ├── spotify_client.py    # Autenticazione e API Spotify
│   ├── downloader.py        # Download brani (Spotify via YouTube + URL diretti yt-dlp)
│   └── upgrader.py          # Upgrade qualita file esistenti
│
└── gui/                     # Interfaccia grafica
    ├── app.py               # Finestra principale con sidebar
    ├── download_tab.py      # Pagina download
    ├── upgrade_tab.py       # Pagina upgrade
    └── settings_tab.py      # Pagina impostazioni
```

## Configurazione

Il file `config.json` viene creato automaticamente:

| Chiave | Default | Descrizione |
|---|---|---|
| `client_id` | `""` | Spotify Client ID |
| `client_secret` | `""` | Spotify Client Secret |
| `bitrate` | `"320K"` | Bitrate download (128K/192K/256K/320K) |
| `hq_threshold` | `310` | Soglia kbps per considerare un file HQ |
| `cookies_path` | `"cookies.txt"` | Path al file cookies YouTube (opzionale) |
| `output_dir` | `"MUSICA/"` | Cartella output predefinita |
| `theme` | `"dark"` | Tema interfaccia (dark/light/system) |

Posizione del file:
- **Sviluppo**: directory del progetto
- **macOS bundle**: `~/Library/Application Support/MusicDownload/`
- **Windows bundle**: `%APPDATA%/MusicDownload/`

## Build

### macOS

```bash
brew install ffmpeg
pip install pyinstaller
python3 build_macos.py
```

Produce `dist/MusicDownload.app` con yt-dlp, ffmpeg e ffprobe inclusi.

### Windows

```bash
pip install pyinstaller
python build_windows.py
```

Produce `dist/MusicDownload/MusicDownload.exe` con tutti i binari inclusi.

## Aggiornamento app

L'app verifica la disponibilita di nuove versioni tramite un file `version.json` remoto. Il formato atteso:

```json
{
  "version": "v1.1",
  "download_url": "https://www.djluza.com/musicdownload/MusicDownload.dmg",
  "notes": "Descrizione delle novita"
}
```

L'URL di controllo e configurabile nella costante `UPDATE_URL` in `gui/settings_tab.py`.

## Licenza

Uso personale.
