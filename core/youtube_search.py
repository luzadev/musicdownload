"""Ricerca su YouTube via yt-dlp (subprocess, flat playlist metadata)."""

from __future__ import annotations

import json
import subprocess

from core.paths import find_ytdlp, subprocess_flags


_TIMEOUT_SEC = 30


def search_youtube(query: str, limit: int = 50) -> list:
    """Cerca su YouTube (ytsearchN:query) e ritorna metadata "flat" (senza scaricare).

    Args:
        query: testo di ricerca libero
        limit: numero massimo di risultati (default 50)

    Returns:
        list[dict] con {id, url, title, channel, duration_sec}. Vuota se nessun match.

    Raises:
        RuntimeError: se yt-dlp non disponibile, timeout, o exit non-zero.
    """
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise RuntimeError("yt-dlp non trovato nel bundle / PATH")

    cmd = [
        ytdlp,
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        f"ytsearch{limit}:{query}",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            **subprocess_flags(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Timeout ricerca YouTube ({_TIMEOUT_SEC}s)") from e

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"yt-dlp error: {' | '.join(tail) or 'unknown'}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"yt-dlp output non-JSON: {e}") from e

    entries = data.get("entries") or []
    result: list = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        video_id = e.get("id") or ""
        url = e.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        result.append({
            "id": video_id,
            "url": url,
            "title": e.get("title") or "",
            "channel": e.get("uploader") or e.get("channel") or "",
            "duration_sec": int(e.get("duration") or 0),
        })
    return result
