"""Scrittura tag ID3 su file MP3 via mutagen, con cover art da URL."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import requests
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3


SAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_stem(stem: str, max_len: int = 180) -> str:
    """Rimuove caratteri non validi per un filename e limita lunghezza."""
    s = SAFE_FILENAME_RE.sub("_", stem or "").strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or "untitled"


def build_filename_stem(artist: str, title: str) -> str:
    """Compone 'Artista - Titolo' sanitizzato."""
    artist = (artist or "").strip()
    title = (title or "").strip()
    if artist and title:
        return sanitize_filename_stem(f"{artist} - {title}")
    return sanitize_filename_stem(title or artist or "untitled")


def _download_cover(url: str) -> Optional[bytes]:
    """Scarica bytes cover, ritorna None su qualsiasi errore."""
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None


def _cover_mime(url: str, content: bytes) -> str:
    """Deduci MIME dell'immagine da URL o magic bytes."""
    u = url.lower()
    if u.endswith(".png"):
        return "image/png"
    if u.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    # magic bytes
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/jpeg"  # default


def write_tags(filepath: str, metadata: dict) -> None:
    """Scrive ID3 tag su file MP3 esistente.

    metadata: dict con chiavi opzionali:
        title, artist, album, date (YYYY o YYYY-MM-DD), genre,
        tracknumber, cover_url

    Errori non fatali (file mancante, tag non scrivibili): silenziosi
    per non bloccare il download principale.
    """
    p = Path(filepath)
    if not p.exists():
        return

    # 1. Tag testuali via EasyID3
    try:
        try:
            audio = EasyID3(str(p))
        except Exception:
            # Se il file non ha header ID3, aggiungine uno vuoto
            mp3 = MP3(str(p))
            if mp3.tags is None:
                mp3.add_tags()
                mp3.save()
            audio = EasyID3(str(p))
        for key in ("title", "artist", "album", "date", "genre", "tracknumber"):
            val = metadata.get(key)
            if val:
                audio[key] = str(val)
        audio.save(str(p))
    except Exception:
        return  # ID3 broken, non provo la cover

    # 2. Cover art via ID3 APIC
    cover_url = (metadata.get("cover_url") or "").strip()
    if not cover_url:
        return
    cover_bytes = _download_cover(cover_url)
    if not cover_bytes:
        return
    try:
        mime = _cover_mime(cover_url, cover_bytes)
        tags = ID3(str(p))
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_bytes))
        tags.save(str(p))
    except Exception:
        pass
