"""Logica upgrade qualita audio — riscrittura di upgrade_quality.sh."""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from core.paths import find_ytdlp, find_ffmpeg_dir, find_ffmpeg, find_ffprobe, subprocess_flags

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac"}

# Soglia minima Jaccard per considerare un file dell'archivio come candidato.
_ARCHIVE_MIN_SIMILARITY = 0.5

# Token di lunghezza inferiore a questa vengono scartati (troppo generici).
_MIN_TOKEN_LEN = 3

# Timeout massimo per singolo download yt-dlp (secondi). Watchdog kill.
# Serve a evitare hang su video geo-restricted, YouTube throttle o rete lenta.
_DOWNLOAD_TIMEOUT_SEC = 300

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
            **subprocess_flags(),
        )
        data = json.loads(result.stdout)
        bit_rate = int(data.get("format", {}).get("bit_rate", 0))
        return bit_rate // 1000
    except Exception:
        return 0


def _normalize_stem(stem: str) -> set:
    """Ritorna il set di token normalizzati per un nome file (senza extension).

    Pipeline:
      1. Lowercase
      2. Sostituisce caratteri non alfanumerici con spazi (mantiene split naturale)
      3. Split su whitespace
      4. Filtra token di lunghezza < _MIN_TOKEN_LEN (troppo generici)
    """
    if not stem:
        return set()
    lowered = stem.lower()
    # Manteniamo spazi ma sostituiamo tutto il resto (che non è alfanumerico) con spazi
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    tokens = cleaned.split()
    return {t for t in tokens if len(t) >= _MIN_TOKEN_LEN}


def _tokens_to_key(tokens: set) -> str:
    """Chiave stabile per un set di token (usata come chiave del dict d'indice)."""
    return "|".join(sorted(tokens))


def _key_to_tokens(key: str) -> set:
    """Inverso di _tokens_to_key."""
    if not key:
        return set()
    return set(key.split("|"))


def _scan_archive(archive_dir: str) -> dict:
    """Indicizza recursivamente un archivio di file audio.

    Ritorna dict {token_key: [Path, ...]}. La scansione è case-insensitive
    sulle estensioni: `.MP3`, `.Mp3`, `.mp3` sono tutti riconosciuti.
    """
    base = Path(archive_dir)
    index: dict = {}
    if not base.exists() or not base.is_dir():
        return index
    for f in base.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        tokens = _normalize_stem(f.stem)
        if not tokens:
            continue
        key = _tokens_to_key(tokens)
        index.setdefault(key, []).append(f)
    return index


def _find_candidates(
    target_stem: str,
    index: dict,
    min_similarity: float = _ARCHIVE_MIN_SIMILARITY,
) -> list:
    """Cerca candidati nell'indice tramite Jaccard sui token del nome.

    Ritorna lista di tuple `(path, similarity, bitrate)` ordinata per
    bitrate DESC, poi similarity DESC.
    """
    target_tokens = _normalize_stem(target_stem)
    if not target_tokens:
        return []

    results: list = []
    for key, paths in index.items():
        entry_tokens = _key_to_tokens(key)
        if not entry_tokens:
            continue
        common = len(target_tokens & entry_tokens)
        if common == 0:
            continue
        total = len(target_tokens | entry_tokens)
        if total == 0:
            continue
        sim = common / total
        if sim < min_similarity:
            continue
        for p in paths:
            try:
                br = get_bitrate(p)
            except Exception:
                br = 0
            results.append((p, sim, br))

    # Ordina: bitrate DESC, poi similarity DESC (stabile)
    results.sort(key=lambda t: (-t[2], -t[1]))
    return results


def _copy_or_convert_to_mp3(
    src: Path,
    dst: Path,
    temp_dir: Path,
) -> bool:
    """Copia (o converte se necessario) `src` in `dst` come MP3.

    - Se src è già .mp3 → copia diretta con shutil.copy2
    - Altrimenti → converti con ffmpeg a 320k CBR
    Ritorna True in caso di successo.
    """
    try:
        if src.suffix.lower() == ".mp3":
            # shutil.copy (non copy2): mtime del target = ora, non quello
            # del sorgente. Così è chiaro nel Finder che il file è stato
            # aggiornato dall'upgrade.
            shutil.copy(str(src), str(dst))
            return dst.exists()
        # Convert non-mp3 -> mp3 320k
        ffmpeg_bin = find_ffmpeg() or "ffmpeg"
        temp_out = temp_dir / f"_archive_convert_{dst.stem}.mp3"
        # -y per sovrascrivere se residuo di run precedente
        subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-i", str(src),
                "-vn",  # scarta eventuali stream video/cover art (le riproviamo dopo)
                "-c:a", "libmp3lame",
                "-b:a", "320k",
                "-id3v2_version", "3",
                str(temp_out),
            ],
            capture_output=True,
            timeout=300,
            **subprocess_flags(),
        )
        if not temp_out.exists():
            return False
        temp_out.replace(dst)
        return True
    except Exception:
        return False


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

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **subprocess_flags())
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

    subprocess.run(cmd, capture_output=True, timeout=60, **subprocess_flags())

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
            **subprocess_flags(),
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
    archive_dir: Optional[str] = None,
    resolve_callback: Optional[Callable] = None,
) -> None:
    """Logica principale di upgrade qualita.

    Args:
        archive_dir: se presente, prima di scaricare da YouTube l'app cerca
            una versione HQ del brano in questa cartella (recursive). Se ne
            trova una la copia (o converte in mp3 320k) mantenendo il nome
            originale.
        resolve_callback: chiamato in caso di match multiplo nell'archivio.
            Riceve una lista di dict {path, bitrate, size, similarity} e deve
            ritornare bloccante un dict {'action': 'use_local'|'use_youtube'|
            'skip', 'path': Optional[str]}.
    """
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

    all_items: list = []
    for folder in folders:
        for ext in AUDIO_EXTENSIONS:
            for f in sorted(folder.glob(f"*{ext}")):
                all_items.append((f, folder))

    total = len(all_items)
    if total == 0:
        if progress_callback:
            progress_callback(0, 0, "", "no_files", 0, 0)
        return

    # Pre-scan dell'archivio (una volta sola). Se archive_dir è None si salta.
    archive_index: dict = {}
    if archive_dir:
        try:
            archive_index = _scan_archive(archive_dir)
        except Exception:
            archive_index = {}
        if progress_callback:
            progress_callback(0, total, "", "scan_archive", 0, len(archive_index))

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

        # ------------------------------------------------------------------
        # 1) ARCHIVE LOOKUP (se archive_dir presente)
        # ------------------------------------------------------------------
        if archive_index:
            try:
                candidates = _find_candidates(filename, archive_index)
            except Exception:
                candidates = []

            selected_path: Optional[Path] = None
            user_chose_youtube = False
            user_chose_skip = False

            if len(candidates) == 1:
                selected_path = candidates[0][0]
            elif len(candidates) >= 2 and resolve_callback is not None:
                cand_payload = []
                for cp, csim, cbr in candidates:
                    try:
                        csize = cp.stat().st_size
                    except Exception:
                        csize = 0
                    cand_payload.append({
                        "path": str(cp),
                        "bitrate": cbr,
                        "size": csize,
                        "similarity": csim,
                    })
                if progress_callback:
                    progress_callback(processed, total, filepath.name,
                                      "resolve_wait", current_kbps, 0)
                try:
                    choice = resolve_callback(str(filepath), cand_payload) or {}
                except Exception:
                    choice = {}
                action = (choice.get("action") or "").strip()
                if action == "use_local":
                    chosen = (choice.get("path") or "").strip()
                    if chosen:
                        cp = Path(chosen)
                        if cp.exists():
                            selected_path = cp
                elif action == "use_youtube":
                    user_chose_youtube = True
                elif action == "skip":
                    user_chose_skip = True
                else:
                    # Risposta invalida: fallback su YouTube per non bloccare
                    user_chose_youtube = True
            # len(candidates) >= 2 senza callback: fallback YouTube
            # len(candidates) == 0: fallback YouTube

            if user_chose_skip:
                _mark_done(done_file, filename)
                processed += 1
                if progress_callback:
                    progress_callback(processed, total, filepath.name,
                                      "skipped_by_user", current_kbps, 0)
                continue

            if selected_path is not None and not user_chose_youtube:
                # Copia/converte il candidato locale come .mp3 con nome originale
                dst = filepath.parent / f"{filename}.mp3"
                if progress_callback:
                    progress_callback(processed, total, filepath.name,
                                      "local_copy", current_kbps, 0)
                # Rimuovi originale solo se ha estensione diversa (altrimenti
                # verrà sovrascritto dalla copia)
                try:
                    if filepath.exists() and filepath.resolve() != dst.resolve():
                        filepath.unlink()
                except Exception:
                    pass
                ok = _copy_or_convert_to_mp3(selected_path, dst, temp_dir)
                if ok:
                    new_kbps = get_bitrate(dst)
                    _mark_done(done_file, filename)
                    _cleanup_temp(temp_dir)
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total, filepath.name,
                                          "local_upgraded", current_kbps, new_kbps)
                    continue
                # Copia fallita: fallback YouTube (non marchiamo done)
                _cleanup_temp(temp_dir)

        # ------------------------------------------------------------------
        # 2) YOUTUBE FALLBACK (comportamento originale)
        # ------------------------------------------------------------------
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
                    **subprocess_flags(),
                )
            proc = _current_process

            # Watchdog: kill del subprocess se supera _DOWNLOAD_TIMEOUT_SEC.
            # Previene hang indefinito su video problematici (geo-block,
            # YouTube throttle, rete lenta).
            def _watchdog_kill():
                try:
                    if proc.poll() is None:
                        proc.kill()  # SIGKILL — SIGTERM può lasciare ffmpeg orfano che tiene aperto il pipe
                except Exception:
                    pass
            watchdog = threading.Timer(_DOWNLOAD_TIMEOUT_SEC, _watchdog_kill)
            watchdog.daemon = True
            watchdog.start()

            # Lettore stdout in thread separato + queue: il main loop polla
            # con timeout invece di bloccare su `for line in proc.stdout`.
            # Cosi is_stopped() e proc.poll() vengono controllati periodicamente
            # -> il bottone Stop risponde in <1s anche se il subprocess ha
            # figli orfani (ffmpeg) che tengono aperto il pipe.
            output_q: queue.Queue = queue.Queue()

            def _reader():
                try:
                    for line in proc.stdout:
                        output_q.put(line)
                except Exception:
                    pass
                finally:
                    output_q.put(None)  # sentinel: pipe closed

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()

            try:
                while True:
                    if is_stopped():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        return
                    try:
                        line = output_q.get(timeout=0.5)
                    except queue.Empty:
                        # Se il subprocess e' morto e il pipe non produce piu' output
                        # (child orfano), esci comunque.
                        if proc.poll() is not None and output_q.empty():
                            # Aspetta ancora un attimo per drenare
                            try:
                                line = output_q.get(timeout=1.0)
                            except queue.Empty:
                                break
                        else:
                            continue
                    if line is None:
                        break
                    pct_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                    if pct_match and progress_callback:
                        pct = int(float(pct_match.group(1)))
                        progress_callback(processed, total, filepath.name, "downloading", current_kbps, pct)

                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                        proc.wait(timeout=5)
                    except Exception:
                        pass
            finally:
                watchdog.cancel()

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
