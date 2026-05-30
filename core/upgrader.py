"""Logica upgrade qualita audio — riscrittura di upgrade_quality.sh."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from core.paths import find_ytdlp, find_ffmpeg_dir, find_ffprobe

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac"}

# Flag globale per interruzione
_stop_event = threading.Event()
_current_process: Optional[subprocess.Popen] = None
_process_lock = threading.Lock()


def request_stop():
    _stop_event.set()
    with _process_lock:
        if _current_process and _current_process.poll() is None:
            _current_process.terminate()


def reset_stop():
    _stop_event.clear()


def is_stopped() -> bool:
    return _stop_event.is_set()


def scan_audio_files(directory: str, recursive: bool = False) -> list[Path]:
    """Trova file audio nella directory."""
    base = Path(directory)
    files = []
    if recursive:
        for ext in AUDIO_EXTENSIONS:
            files.extend(base.rglob(f"*{ext}"))
    else:
        for ext in AUDIO_EXTENSIONS:
            files.extend(base.glob(f"*{ext}"))
    return sorted(files)


def get_bitrate(filepath: str | Path) -> int:
    """Ritorna il bitrate in kbps tramite ffprobe. Ritorna 0 in caso di errore."""
    try:
        ffprobe_bin = find_ffprobe() or "ffprobe"
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        bit_rate = int(data.get("format", {}).get("bit_rate", 0))
        return bit_rate // 1000
    except Exception:
        return 0


def _load_done_set(done_file: Path) -> set[str]:
    if done_file.exists():
        return set(done_file.read_text(encoding="utf-8").splitlines())
    return set()


def _mark_done(done_file: Path, filename: str) -> None:
    with open(done_file, "a", encoding="utf-8") as f:
        f.write(filename + "\n")


def _search_youtube(query: str, cookies_path: Optional[str] = None) -> str:
    """Cerca un video su YouTube e ritorna l'URL."""
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
        raise ValueError("Ricerca fallita")

    data = json.loads(result.stdout)
    video_id = data.get("id", "")
    if not video_id:
        raise ValueError("Nessun risultato")
    return f"https://www.youtube.com/watch?v={video_id}"


def update_cover_only(
    filepath: Path,
    video_url: str,
    temp_dir: Path,
    cookies_path: Optional[str] = None,
) -> bool:
    """Aggiorna solo la copertina di un file audio. Ritorna True se riuscito."""
    ytdlp = find_ytdlp()
    cmd = [
        ytdlp,
        "--skip-download",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--no-warnings",
        "--output", str(temp_dir / "cover"),
        video_url,
    ]
    ffmpeg_dir = _find_ffmpeg_dir()
    if ffmpeg_dir:
        cmd.extend(["--ffmpeg-location", ffmpeg_dir])
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", cookies_path])

    subprocess.run(cmd, capture_output=True, timeout=60)

    cover_files = list(temp_dir.glob("cover*.jpg"))
    if not cover_files:
        return False

    cover_file = cover_files[0]
    temp_output = temp_dir / "temp_output.mp3"

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(filepath),
                "-i", str(cover_file),
                "-map", "0:a", "-map", "1:0",
                "-c:a", "copy",
                "-id3v2_version", "3",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
                str(temp_output),
            ],
            capture_output=True,
            timeout=60,
        )
    except Exception:
        _cleanup_temp(temp_dir)
        return False

    if temp_output.exists():
        temp_output.replace(filepath)
        _cleanup_temp(temp_dir)
        return True

    _cleanup_temp(temp_dir)
    return False


def _cleanup_temp(temp_dir: Path) -> None:
    for pattern in ("*.jpg", "*.webp", "*.mp3", "*.webm", "*.m4a"):
        for f in temp_dir.glob(pattern):
            f.unlink(missing_ok=True)


def upgrade_folder(
    directory: str,
    threshold: int = 310,
    cookies_path: Optional[str] = None,
    recursive: bool = False,
    progress_callback: Optional[Callable] = None,
) -> None:
    """Logica principale di upgrade qualita."""
    reset_stop()
    ytdlp = find_ytdlp()

    if recursive:
        base = Path(directory)
        folders = set()
        for ext in AUDIO_EXTENSIONS:
            for f in base.rglob(f"*{ext}"):
                folders.add(f.parent)
        folders = sorted(folders)
    else:
        folders = [Path(directory)]

    all_items: list[tuple[Path, Path]] = []
    for folder in folders:
        for ext in AUDIO_EXTENSIONS:
            for f in sorted(folder.glob(f"*{ext}")):
                all_items.append((f, folder))

    total = len(all_items)
    if total == 0:
        if progress_callback:
            progress_callback(0, 0, "", "no_files", 0, 0)
        return

    processed = 0

    for filepath, folder in all_items:
        if is_stopped():
            if progress_callback:
                progress_callback(processed, total, "", "stopped", 0, 0)
            return

        done_file = folder / ".upgraded_tracks"
        temp_dir = folder / ".temp_download"
        temp_dir.mkdir(exist_ok=True)

        done_set = _load_done_set(done_file)
        filename = filepath.stem

        if filename in done_set:
            processed += 1
            if progress_callback:
                progress_callback(processed, total, filepath.name, "skipped", 0, 0)
            continue

        current_kbps = get_bitrate(filepath)

        if progress_callback:
            progress_callback(processed, total, filepath.name, "searching", current_kbps, 0)

        query = filename
        try:
            video_url = _search_youtube(query, cookies_path)
        except Exception:
            _mark_done(done_file, filename)
            processed += 1
            if progress_callback:
                progress_callback(processed, total, filepath.name, "not_found", current_kbps, 0)
            continue

        if is_stopped():
            return

        # Se qualita gia alta, aggiorna solo copertina
        if current_kbps >= threshold:
            if progress_callback:
                progress_callback(processed, total, filepath.name, "cover_only", current_kbps, 0)

            success = update_cover_only(filepath, video_url, temp_dir, cookies_path)
            _mark_done(done_file, filename)
            processed += 1

            status = "cover_done" if success else "cover_failed"
            if progress_callback:
                progress_callback(processed, total, filepath.name, status, current_kbps, current_kbps)
            continue

        # Scarica versione HQ
        if progress_callback:
            progress_callback(processed, total, filepath.name, "downloading", current_kbps, 0)

        cmd = [
            ytdlp,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--add-metadata",
            "--no-warnings",
            "--newline",
            "--output", str(temp_dir / "%(title)s.%(ext)s"),
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
                    return
                pct_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                if pct_match and progress_callback:
                    pct = int(float(pct_match.group(1)))
                    progress_callback(processed, total, filepath.name, "downloading", current_kbps, pct)

            _current_process.wait()
            with _process_lock:
                _current_process = None

        except Exception:
            with _process_lock:
                _current_process = None
            _mark_done(done_file, filename)
            processed += 1
            if progress_callback:
                progress_callback(processed, total, filepath.name, "download_error", current_kbps, 0)
            _cleanup_temp(temp_dir)
            continue

        # Trova il file scaricato
        new_files = list(temp_dir.glob("*.mp3"))
        if not new_files:
            _mark_done(done_file, filename)
            processed += 1
            if progress_callback:
                progress_callback(processed, total, filepath.name, "download_error", current_kbps, 0)
            _cleanup_temp(temp_dir)
            continue

        newest = max(new_files, key=lambda p: p.stat().st_mtime)
        new_kbps = get_bitrate(newest)

        filepath.unlink()
        newest.replace(filepath.parent / f"{filename}.mp3")

        _mark_done(done_file, filename)
        _cleanup_temp(temp_dir)
        processed += 1

        if progress_callback:
            progress_callback(processed, total, filepath.name, "upgraded", current_kbps, new_kbps)

    for folder in folders:
        td = folder / ".temp_download"
        if td.exists():
            try:
                td.rmdir()
            except OSError:
                pass

    if progress_callback and not is_stopped():
        progress_callback(total, total, "", "completed", 0, 0)


def count_files_info(directory: str, recursive: bool = False) -> tuple[int, int]:
    """Ritorna (total_audio_files, already_upgraded)."""
    files = scan_audio_files(directory, recursive)
    total = len(files)

    already_done = 0
    for f in files:
        done_file = f.parent / ".upgraded_tracks"
        done_set = _load_done_set(done_file)
        if f.stem in done_set:
            already_done += 1

    return total, already_done
