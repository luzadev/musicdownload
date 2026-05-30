"""Download da YouTube via yt-dlp (subprocess per usare la versione piu aggiornata)."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from core.paths import find_ytdlp, find_ffmpeg_dir


# Flag globale per interruzione
_stop_event = threading.Event()
_current_process: Optional[subprocess.Popen] = None
_process_lock = threading.Lock()


def request_stop():
    """Richiede l'interruzione del download in corso."""
    _stop_event.set()
    with _process_lock:
        if _current_process and _current_process.poll() is None:
            _current_process.terminate()


def reset_stop():
    _stop_event.clear()


def is_stopped() -> bool:
    return _stop_event.is_set()


def _load_done_set(done_file: Path) -> set[str]:
    """Carica l'elenco delle tracce gia scaricate."""
    if done_file.exists():
        try:
            return set(done_file.read_text(encoding="utf-8").splitlines())
        except OSError:
            return set()
    return set()


def _mark_done(done_file: Path, key: str) -> None:
    """Aggiunge una traccia al file delle tracce scaricate."""
    try:
        with open(done_file, "a", encoding="utf-8") as f:
            f.write(key + "\n")
    except OSError:
        pass


_STOPWORDS = {
    "official", "video", "audio", "music", "lyric", "lyrics", "hd", "4k",
    "remix", "edit", "extended", "feat", "ft", "featuring", "with",
    "from", "the", "and", "of", "a", "an", "to", "in",
}


def _tokenize(s: str) -> set[str]:
    """Estrae token alfanumerici significativi da una stringa."""
    s = s.lower()
    tokens = re.findall(r"[a-z0-9]+", s)
    return {t for t in tokens if len(t) >= 2 and t not in _STOPWORDS}


def _scan_existing_files(directory: Path, extensions: tuple[str, ...] = (".mp3", ".m4a", ".opus", ".webm", ".wav", ".flac")) -> list[set[str]]:
    """Ritorna lista di set di token dei filename presenti nella directory."""
    if not directory.exists():
        return []
    return [_tokenize(f.stem) for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() in extensions]


def _file_exists_for_query(query: str, existing_tokens: list[set[str]]) -> bool:
    """Verifica se esiste gia un file il cui titolo contiene tutte le parole del query.
    Match basato sui token: tutte le parole significative del query devono essere
    presenti nel filename (l'ordine non conta, eventuali parole extra nel filename ok)."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return False
    for file_tokens in existing_tokens:
        if query_tokens.issubset(file_tokens):
            return True
    return False


def _search_youtube(query: str, cookies_path: Optional[str] = None) -> tuple[str, str]:
    """Cerca un video su YouTube. Ritorna (video_url, video_title)."""
    ytdlp = find_ytdlp()
    cmd = [
        ytdlp,
        f"ytsearch1:{query}",
        "--dump-json",
        "--no-download",
        "--no-warnings",
        "--flat-playlist",
    ]
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", cookies_path])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError(f"Ricerca fallita: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    video_id = data.get("id", "")
    title = data.get("title", query)
    if not video_id:
        raise ValueError("Nessun risultato trovato")

    return f"https://www.youtube.com/watch?v={video_id}", title


def download_playlist(
    tracks: list[dict],
    output_dir: str,
    bitrate: str = "320K",
    cookies_path: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
) -> None:
    """Scarica tutti i brani dalla lista di tracce.

    Args:
        tracks: lista di {"name": ..., "artist": ...}
        output_dir: directory di destinazione
        bitrate: qualita audio (es. "320K")
        cookies_path: percorso file cookies (opzionale)
        progress_callback: callback(track_index, total, track_name, status, percent)
    """
    reset_stop()
    total = len(tracks)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    done_file = out_path / ".downloaded_tracks"
    done_set = _load_done_set(done_file)
    existing_files = _scan_existing_files(out_path)
    ytdlp = find_ytdlp()

    for i, track in enumerate(tracks):
        if is_stopped():
            if progress_callback:
                progress_callback(i, total, "", "stopped", 0)
            return

        query = f"{track['name']} - {track['artist']}"
        track_only = track['name']

        # Salta brani gia scaricati in precedenza (file di tracking)
        if query in done_set:
            if progress_callback:
                progress_callback(i, total, query, "skipped", 100)
            continue

        # Salta se esiste gia un file corrispondente nella cartella
        if (_file_exists_for_query(query, existing_files)
                or _file_exists_for_query(track_only, existing_files)):
            _mark_done(done_file, query)
            done_set.add(query)
            if progress_callback:
                progress_callback(i, total, query, "skipped", 100)
            continue

        if progress_callback:
            progress_callback(i, total, query, "searching", 0)

        # Cerca il video su YouTube
        try:
            video_url, _ = _search_youtube(query, cookies_path)
        except Exception as e:
            if progress_callback:
                progress_callback(i, total, query, f"error: {e}", 0)
            continue

        if is_stopped():
            return

        if progress_callback:
            progress_callback(i, total, query, "downloading", 0)

        # Scarica con yt-dlp subprocess
        cmd = [
            ytdlp,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", bitrate.rstrip("Kk"),
            "--embed-thumbnail",
            "--add-metadata",
            "--no-check-certificates",
            "--newline",
            "--output", str(Path(output_dir) / "%(title)s.%(ext)s"),
            video_url,
        ]
        ffmpeg_dir = find_ffmpeg_dir()
        if ffmpeg_dir:
            cmd.extend(["--ffmpeg-location", ffmpeg_dir])
        if cookies_path and Path(cookies_path).exists():
            cmd.extend(["--cookies", cookies_path])

        try:
            with _process_lock:
                _current_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )

            for line in _current_process.stdout:
                if is_stopped():
                    _current_process.terminate()
                    if progress_callback:
                        progress_callback(i, total, query, "stopped", 0)
                    return

                # Parse progress da output yt-dlp
                pct_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                if pct_match and progress_callback:
                    pct = int(float(pct_match.group(1)))
                    progress_callback(i, total, query, "downloading", pct)

            return_code = _current_process.wait()

            with _process_lock:
                _current_process = None

            if return_code == 0:
                _mark_done(done_file, query)
                done_set.add(query)
                existing_files = _scan_existing_files(out_path)
                if progress_callback:
                    progress_callback(i, total, query, "done", 100)
            else:
                if progress_callback:
                    progress_callback(i, total, query, f"error: yt-dlp exit {return_code}", 0)

        except Exception as e:
            with _process_lock:
                _current_process = None
            if progress_callback:
                progress_callback(i, total, query, f"error: {e}", 0)

    if progress_callback and not is_stopped():
        progress_callback(total, total, "", "completed", 100)


def download_direct_url(
    url: str,
    output_dir: str,
    bitrate: str = "320K",
    cookies_path: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
) -> None:
    """Scarica direttamente da un URL supportato da yt-dlp (YouTube, SoundCloud, ecc.).

    Supporta sia singoli video che playlist.
    Callback signature: progress_callback(idx, total, track_name, status, pct)
    """
    global _current_process
    reset_stop()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    done_file = out_path / ".downloaded_tracks"
    done_set = _load_done_set(done_file)
    existing_files = _scan_existing_files(out_path)
    ytdlp = find_ytdlp()

    # 1. Ottieni info tramite yt-dlp --dump-json
    probe_cmd = [
        ytdlp,
        "--dump-json",
        "--flat-playlist",
        "--no-download",
        "--no-warnings",
        url,
    ]
    if cookies_path and Path(cookies_path).exists():
        probe_cmd.extend(["--cookies", cookies_path])

    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise ValueError(result.stderr.strip())
    except Exception as e:
        if progress_callback:
            progress_callback(0, 0, url, f"error: {e}", 0)
        return

    # Ogni riga stdout e un JSON (una entry per playlist, una per singolo)
    entries = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        if progress_callback:
            progress_callback(0, 0, url, "error: Nessun contenuto trovato", 0)
        return

    total = len(entries)

    # 2. Scarica ogni entry
    for i, entry in enumerate(entries):
        if is_stopped():
            if progress_callback:
                progress_callback(i, total, "", "stopped", 0)
            return

        title = entry.get("title", f"Track {i + 1}")
        entry_url = entry.get("url") or entry.get("webpage_url") or entry.get("original_url") or url

        # Per singoli video (non flat-playlist), usa l'URL originale
        if total == 1:
            entry_url = url

        # Salta se gia scaricato (file di tracking)
        track_key = entry.get("id") or title
        if track_key in done_set:
            if progress_callback:
                progress_callback(i, total, title, "skipped", 100)
            continue

        # Salta se esiste gia un file corrispondente nella cartella
        if _file_exists_for_query(title, existing_files):
            _mark_done(done_file, track_key)
            done_set.add(track_key)
            if progress_callback:
                progress_callback(i, total, title, "skipped", 100)
            continue

        if progress_callback:
            progress_callback(i, total, title, "downloading", 0)

        cmd = [
            ytdlp,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", bitrate.rstrip("Kk"),
            "--embed-thumbnail",
            "--add-metadata",
            "--no-check-certificates",
            "--newline",
            "--output", str(Path(output_dir) / "%(title)s.%(ext)s"),
            entry_url,
        ]
        ffmpeg_dir = find_ffmpeg_dir()
        if ffmpeg_dir:
            cmd.extend(["--ffmpeg-location", ffmpeg_dir])
        if cookies_path and Path(cookies_path).exists():
            cmd.extend(["--cookies", cookies_path])

        try:
            with _process_lock:
                _current_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )

            for line in _current_process.stdout:
                if is_stopped():
                    _current_process.terminate()
                    if progress_callback:
                        progress_callback(i, total, title, "stopped", 0)
                    return

                pct_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                if pct_match and progress_callback:
                    pct = int(float(pct_match.group(1)))
                    progress_callback(i, total, title, "downloading", pct)

            return_code = _current_process.wait()

            with _process_lock:
                _current_process = None

            if return_code == 0:
                _mark_done(done_file, track_key)
                done_set.add(track_key)
                existing_files = _scan_existing_files(out_path)
                if progress_callback:
                    progress_callback(i, total, title, "done", 100)
            else:
                if progress_callback:
                    progress_callback(i, total, title, f"error: yt-dlp exit {return_code}", 0)

        except Exception as e:
            with _process_lock:
                _current_process = None
            if progress_callback:
                progress_callback(i, total, title, f"error: {e}", 0)

    if progress_callback and not is_stopped():
        progress_callback(total, total, "", "completed", 100)
