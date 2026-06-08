"""Lettura e scrittura metadati audio (ID3 per MP3, MP4 per M4A, Vorbis per FLAC)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    APIC, TIT2, TPE1, TPE2, TALB, TDRC, TRCK, TCON, COMM, TBPM, TKEY,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.wave import WAVE


SUPPORTED_EXTS = (".mp3", ".m4a", ".mp4", ".aac", ".flac", ".wav")


def _text(value) -> str:
    """Estrai testo da un frame mutagen."""
    if value is None:
        return ""
    if hasattr(value, "text"):
        t = value.text
        if isinstance(t, list) and t:
            return str(t[0])
        return str(t)
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value)


def _read_mp3(path: str, result: dict) -> dict:
    result["format"] = "MP3"
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return result

    result["title"] = _text(tags.get("TIT2"))
    result["artist"] = _text(tags.get("TPE1"))
    result["album_artist"] = _text(tags.get("TPE2"))
    result["album"] = _text(tags.get("TALB"))
    result["year"] = _text(tags.get("TDRC"))
    result["track"] = _text(tags.get("TRCK"))
    result["genre"] = _text(tags.get("TCON"))
    result["bpm"] = _text(tags.get("TBPM"))
    result["key"] = _text(tags.get("TKEY"))

    for k in tags.keys():
        if k.startswith("COMM"):
            result["comment"] = _text(tags[k])
            break

    for k in tags.keys():
        if k.startswith("APIC"):
            apic = tags[k]
            result["cover_base64"] = base64.b64encode(apic.data).decode("ascii")
            result["cover_mime"] = apic.mime or "image/jpeg"
            break

    return result


def _read_mp4(path: str, result: dict) -> dict:
    result["format"] = "M4A/MP4"
    m = MP4(path)
    tags = m.tags or {}
    result["title"] = _text(tags.get("\xa9nam"))
    result["artist"] = _text(tags.get("\xa9ART"))
    result["album_artist"] = _text(tags.get("aART"))
    result["album"] = _text(tags.get("\xa9alb"))
    result["year"] = _text(tags.get("\xa9day"))
    track_pair = tags.get("trkn")
    if track_pair and isinstance(track_pair, list) and track_pair:
        num, tot = track_pair[0] if isinstance(track_pair[0], tuple) else (track_pair[0], 0)
        result["track"] = f"{num}/{tot}" if tot else str(num)
    result["genre"] = _text(tags.get("\xa9gen"))
    result["comment"] = _text(tags.get("\xa9cmt"))
    result["bpm"] = _text(tags.get("tmpo"))

    covers = tags.get("covr")
    if covers:
        c = covers[0]
        result["cover_base64"] = base64.b64encode(bytes(c)).decode("ascii")
        result["cover_mime"] = "image/jpeg" if c.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
    return result


def _read_wav(path: str, result: dict) -> dict:
    result["format"] = "WAV"
    w = WAVE(path)
    tags = w.tags  # ID3 object, puo essere None
    if tags is None:
        return result

    result["title"] = _text(tags.get("TIT2"))
    result["artist"] = _text(tags.get("TPE1"))
    result["album_artist"] = _text(tags.get("TPE2"))
    result["album"] = _text(tags.get("TALB"))
    result["year"] = _text(tags.get("TDRC"))
    result["track"] = _text(tags.get("TRCK"))
    result["genre"] = _text(tags.get("TCON"))
    result["bpm"] = _text(tags.get("TBPM"))
    result["key"] = _text(tags.get("TKEY"))

    for k in tags.keys():
        if k.startswith("COMM"):
            result["comment"] = _text(tags[k])
            break

    for k in tags.keys():
        if k.startswith("APIC"):
            apic = tags[k]
            result["cover_base64"] = base64.b64encode(apic.data).decode("ascii")
            result["cover_mime"] = apic.mime or "image/jpeg"
            break

    return result


def _read_flac(path: str, result: dict) -> dict:
    result["format"] = "FLAC"
    f = FLAC(path)
    g = lambda k: (f.get(k) or [""])[0] if f.get(k) else ""
    result["title"] = g("title")
    result["artist"] = g("artist")
    result["album_artist"] = g("albumartist")
    result["album"] = g("album")
    result["year"] = g("date")
    result["track"] = g("tracknumber")
    result["genre"] = g("genre")
    result["bpm"] = g("bpm")
    result["key"] = g("initialkey")
    result["comment"] = g("comment")
    if f.pictures:
        pic = f.pictures[0]
        result["cover_base64"] = base64.b64encode(pic.data).decode("ascii")
        result["cover_mime"] = pic.mime or "image/jpeg"
    return result


def read_metadata(path: str) -> dict:
    """Ritorna un dict con tutti i metadati leggibili dal file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"Formato non supportato: {ext}")

    result = {
        "path": str(p),
        "filename": p.name,
        "format": "",
        "title": "", "artist": "", "album_artist": "",
        "album": "", "year": "", "track": "",
        "genre": "", "comment": "",
        "bpm": "", "key": "",
        "duration": 0, "bitrate": 0,
        "cover_base64": "", "cover_mime": "",
    }

    audio = MutagenFile(str(p))
    if audio is None:
        raise ValueError(f"Impossibile leggere: {ext}")

    info = getattr(audio, "info", None)
    if info:
        result["duration"] = int(getattr(info, "length", 0) or 0)
        result["bitrate"] = int((getattr(info, "bitrate", 0) or 0) // 1000)

    if ext == ".mp3":
        return _read_mp3(str(p), result)
    if ext in (".m4a", ".mp4", ".aac"):
        return _read_mp4(str(p), result)
    if ext == ".flac":
        return _read_flac(str(p), result)
    if ext == ".wav":
        return _read_wav(str(p), result)
    return result


def _write_mp3(path: str, data: dict, cover_path: Optional[str], remove_cover: bool) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    def set_or_del(key, frame_cls, value):
        if value:
            tags[key] = frame_cls(encoding=3, text=value)
        elif key in tags:
            del tags[key]

    set_or_del("TIT2", TIT2, data.get("title", ""))
    set_or_del("TPE1", TPE1, data.get("artist", ""))
    set_or_del("TPE2", TPE2, data.get("album_artist", ""))
    set_or_del("TALB", TALB, data.get("album", ""))
    set_or_del("TDRC", TDRC, data.get("year", ""))
    set_or_del("TRCK", TRCK, data.get("track", ""))
    set_or_del("TCON", TCON, data.get("genre", ""))
    set_or_del("TBPM", TBPM, data.get("bpm", ""))
    set_or_del("TKEY", TKEY, data.get("key", ""))

    # Rimuovi tutti i COMM esistenti
    for k in list(tags.keys()):
        if k.startswith("COMM"):
            del tags[k]
    comment = data.get("comment", "")
    if comment:
        tags.add(COMM(encoding=3, lang="ita", desc="", text=comment))

    # Cover
    if remove_cover or cover_path:
        for k in list(tags.keys()):
            if k.startswith("APIC"):
                del tags[k]
    if cover_path:
        cp = Path(cover_path)
        if cp.exists():
            ext = cp.suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            with open(cp, "rb") as f:
                cover_data = f.read()
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_data))

    tags.save(path, v2_version=3)


def _write_mp4(path: str, data: dict, cover_path: Optional[str], remove_cover: bool) -> None:
    m = MP4(path)

    def set_or_del(key, value):
        if value:
            m[key] = value
        elif key in m:
            del m[key]

    set_or_del("\xa9nam", data.get("title", ""))
    set_or_del("\xa9ART", data.get("artist", ""))
    set_or_del("aART", data.get("album_artist", ""))
    set_or_del("\xa9alb", data.get("album", ""))
    set_or_del("\xa9day", data.get("year", ""))
    set_or_del("\xa9gen", data.get("genre", ""))
    set_or_del("\xa9cmt", data.get("comment", ""))

    track = data.get("track", "")
    if track:
        try:
            parts = track.split("/")
            num = int(parts[0])
            tot = int(parts[1]) if len(parts) > 1 else 0
            m["trkn"] = [(num, tot)]
        except (ValueError, IndexError):
            pass
    elif "trkn" in m:
        del m["trkn"]

    bpm = data.get("bpm", "")
    if bpm:
        try:
            m["tmpo"] = [int(bpm)]
        except ValueError:
            pass
    elif "tmpo" in m:
        del m["tmpo"]

    if remove_cover or cover_path:
        if "covr" in m:
            del m["covr"]
    if cover_path:
        cp = Path(cover_path)
        if cp.exists():
            ext = cp.suffix.lower()
            fmt = MP4Cover.FORMAT_PNG if ext == ".png" else MP4Cover.FORMAT_JPEG
            with open(cp, "rb") as f:
                cover_data = f.read()
            m["covr"] = [MP4Cover(cover_data, imageformat=fmt)]

    m.save()


def _write_flac(path: str, data: dict, cover_path: Optional[str], remove_cover: bool) -> None:
    f = FLAC(path)

    def set_or_del(key, value):
        if value:
            f[key] = value
        elif key in f:
            del f[key]

    set_or_del("title", data.get("title", ""))
    set_or_del("artist", data.get("artist", ""))
    set_or_del("albumartist", data.get("album_artist", ""))
    set_or_del("album", data.get("album", ""))
    set_or_del("date", data.get("year", ""))
    set_or_del("tracknumber", data.get("track", ""))
    set_or_del("genre", data.get("genre", ""))
    set_or_del("bpm", data.get("bpm", ""))
    set_or_del("initialkey", data.get("key", ""))
    set_or_del("comment", data.get("comment", ""))

    if remove_cover or cover_path:
        f.clear_pictures()
    if cover_path:
        cp = Path(cover_path)
        if cp.exists():
            ext = cp.suffix.lower()
            pic = Picture()
            with open(cp, "rb") as fh:
                pic.data = fh.read()
            pic.type = 3
            pic.mime = "image/png" if ext == ".png" else "image/jpeg"
            f.add_picture(pic)

    f.save()


def _write_wav(path: str, data: dict, cover_path: Optional[str], remove_cover: bool) -> None:
    w = WAVE(path)
    if w.tags is None:
        w.add_tags()
    tags = w.tags

    def set_or_del(key, frame_cls, value):
        if value:
            tags[key] = frame_cls(encoding=3, text=value)
        elif key in tags:
            del tags[key]

    set_or_del("TIT2", TIT2, data.get("title", ""))
    set_or_del("TPE1", TPE1, data.get("artist", ""))
    set_or_del("TPE2", TPE2, data.get("album_artist", ""))
    set_or_del("TALB", TALB, data.get("album", ""))
    set_or_del("TDRC", TDRC, data.get("year", ""))
    set_or_del("TRCK", TRCK, data.get("track", ""))
    set_or_del("TCON", TCON, data.get("genre", ""))
    set_or_del("TBPM", TBPM, data.get("bpm", ""))
    set_or_del("TKEY", TKEY, data.get("key", ""))

    for k in list(tags.keys()):
        if k.startswith("COMM"):
            del tags[k]
    comment = data.get("comment", "")
    if comment:
        tags.add(COMM(encoding=3, lang="ita", desc="", text=comment))

    if remove_cover or cover_path:
        for k in list(tags.keys()):
            if k.startswith("APIC"):
                del tags[k]
    if cover_path:
        cp = Path(cover_path)
        if cp.exists():
            ext_c = cp.suffix.lower()
            mime = "image/png" if ext_c == ".png" else "image/jpeg"
            with open(cp, "rb") as f:
                cover_data = f.read()
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_data))

    w.save()


def write_metadata(path: str, data: dict, cover_path: Optional[str] = None,
                    remove_cover: bool = False) -> None:
    """Salva i metadati. Se remove_cover=True rimuove la copertina esistente
    senza sostituirla. Se cover_path e fornito, la sostituisce."""
    ext = Path(path).suffix.lower()
    if ext == ".mp3":
        _write_mp3(path, data, cover_path, remove_cover)
    elif ext in (".m4a", ".mp4", ".aac"):
        _write_mp4(path, data, cover_path, remove_cover)
    elif ext == ".flac":
        _write_flac(path, data, cover_path, remove_cover)
    elif ext == ".wav":
        _write_wav(path, data, cover_path, remove_cover)
    else:
        raise ValueError(f"Formato non supportato: {ext}")
