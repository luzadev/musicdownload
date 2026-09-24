"""Lettura e scrittura metadati audio (ID3 per MP3, MP4 per M4A, Vorbis per FLAC)."""

from __future__ import annotations

import base64
import plistlib
import subprocess
import struct
import sys
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    APIC, TIT2, TPE1, TPE2, TALB, TDRC, TRCK, TCON, COMM, TBPM, TKEY,
    USLT, WOAS,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.wave import WAVE


SUPPORTED_EXTS = (".mp3", ".m4a", ".mp4", ".aac", ".flac", ".wav")

_WHERE_FROM_ATTR = "com.apple.metadata:kMDItemWhereFroms"


def _read_where_from(path: str) -> list:
    """Legge l'xattr macOS 'kMDItemWhereFroms' (lista di URL/origini).
    Ritorna [] se non e macOS o se l'attributo non esiste."""
    if sys.platform != "darwin":
        return []
    try:
        res = subprocess.run(
            ["xattr", "-px", _WHERE_FROM_ATTR, path],
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode != 0:
            return []
        hex_str = "".join(res.stdout.split())
        if not hex_str:
            return []
        raw = bytes.fromhex(hex_str)
        items = plistlib.loads(raw)
        if isinstance(items, list):
            return [str(x) for x in items]
        return [str(items)]
    except Exception:
        return []


def _write_where_from(path: str, urls: list) -> None:
    """Scrive l'xattr macOS 'kMDItemWhereFroms'. Lista vuota -> rimuove."""
    if sys.platform != "darwin":
        return
    try:
        clean = [u.strip() for u in (urls or []) if u and u.strip()]
        if not clean:
            subprocess.run(
                ["xattr", "-d", _WHERE_FROM_ATTR, path],
                capture_output=True, timeout=5,
            )
            return
        data = plistlib.dumps(clean, fmt=plistlib.FMT_BINARY)
        subprocess.run(
            ["xattr", "-wx", _WHERE_FROM_ATTR, data.hex(), path],
            capture_output=True, timeout=5, check=True,
        )
    except Exception:
        pass


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


_AI_MARKERS = {
    "suno": ["suno.com", "made with suno", "sunoai"],
    "udio": ["udio.com", "made with udio"],
    "riffusion": ["riffusion.com", "made with riffusion"],
    "mubert": ["mubert.com", "made with mubert"],
    "aiva": ["aiva.ai"],
    "boomy": ["boomy.com", "made with boomy"],
    "soundraw": ["soundraw.io"],
    "loudly": ["loudly.com"],
}


def _detect_ai(comment: str, source_url: str, extra: str = "") -> tuple:
    """Ritorna (is_ai: bool, source_name: str). Case-insensitive.
    `extra` = altre stringhe da controllare (es. presenza C2PA manifest)."""
    blob = f"{comment} {source_url} {extra}".lower()
    for source, markers in _AI_MARKERS.items():
        for m in markers:
            if m in blob:
                return True, source
    if "c2pa" in blob:
        return True, ""
    return False, ""


def _dump_id3_frames(tags) -> list:
    """Lista compatta di tutti i frame ID3 (esclusa APIC binaria).
    Ogni voce: {key, preview, size, kind}. Utile per audit AI-generated."""
    out = []
    for key in tags.keys():
        try:
            frame = tags[key]
        except Exception:
            continue
        kind = "text"
        preview = ""
        size = 0
        if key.startswith("APIC"):
            kind = "binary"
            preview = f"{frame.mime or 'image'} ({len(frame.data)} bytes)"
            size = len(frame.data)
        elif key.startswith("GEOB"):
            kind = "binary"
            data = getattr(frame, "data", b"") or b""
            desc = getattr(frame, "desc", "") or ""
            mime = getattr(frame, "mime", "") or ""
            preview = f"{desc or mime or 'blob'} ({len(data)} bytes)"
            size = len(data)
        elif key.startswith("USLT"):
            txt = getattr(frame, "text", "") or ""
            preview = txt[:180] + ("…" if len(txt) > 180 else "")
            size = len(txt)
        elif key.startswith("WOAS") or key.startswith("WXXX") or key.startswith("WOAR"):
            preview = getattr(frame, "url", "") or str(frame)
            size = len(preview)
        else:
            txt = str(frame)
            preview = txt[:180] + ("…" if len(txt) > 180 else "")
            size = len(txt)
        out.append({"key": key, "preview": preview, "size": size, "kind": kind})
    return out


def _read_mp3(path: str, result: dict) -> dict:
    result["format"] = "MP3"
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return result

    result["raw_frames"] = _dump_id3_frames(tags)

    result["title"] = _text(tags.get("TIT2"))
    result["artist"] = _text(tags.get("TPE1"))
    result["album_artist"] = _text(tags.get("TPE2"))
    result["album"] = _text(tags.get("TALB"))
    result["year"] = _text(tags.get("TDRC"))
    result["track"] = _text(tags.get("TRCK"))
    result["genre"] = _text(tags.get("TCON"))
    result["bpm"] = _text(tags.get("TBPM"))
    result["key"] = _text(tags.get("TKEY"))
    result["source_url"] = _text(tags.get("WOAS"))

    for k in tags.keys():
        if k.startswith("COMM"):
            result["comment"] = _text(tags[k])
            break

    for k in tags.keys():
        if k.startswith("USLT"):
            frame = tags[k]
            result["lyrics"] = getattr(frame, "text", "") or ""
            break

    for k in tags.keys():
        if k.startswith("APIC"):
            apic = tags[k]
            result["cover_base64"] = base64.b64encode(apic.data).decode("ascii")
            result["cover_mime"] = apic.mime or "image/jpeg"
            break

    # AI detection: C2PA manifest (GEOB frame) o markers testuali
    has_c2pa = any("c2pa" in k.lower() for k in tags.keys())
    result["ai_generated"], result["ai_source"] = _detect_ai(
        result["comment"], result["source_url"], "c2pa" if has_c2pa else "",
    )

    return result


def _dump_mp4_atoms(tags) -> list:
    out = []
    for key, val in tags.items():
        preview = ""
        kind = "text"
        size = 0
        if key == "covr":
            kind = "binary"
            data = bytes(val[0]) if val else b""
            preview = f"cover ({len(data)} bytes)"
            size = len(data)
        else:
            try:
                preview = str(val[0] if isinstance(val, list) and val else val)
            except Exception:
                preview = "<binary>"
            if isinstance(preview, str):
                size = len(preview)
                if len(preview) > 180:
                    preview = preview[:180] + "…"
        out.append({"key": key, "preview": preview, "size": size, "kind": kind})
    return out


def _read_mp4(path: str, result: dict) -> dict:
    result["format"] = "M4A/MP4"
    m = MP4(path)
    tags = m.tags or {}
    result["raw_frames"] = _dump_mp4_atoms(tags)
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
    result["lyrics"] = _text(tags.get("\xa9lyr"))
    # M4A non ha WOAS: cerchiamo in freeform ----:com.apple.iTunes:URL
    for k in tags.keys():
        if isinstance(k, str) and k.startswith("----") and "URL" in k.upper():
            v = tags[k]
            if v:
                result["source_url"] = v[0].decode("utf-8", errors="ignore") if isinstance(v[0], bytes) else str(v[0])
                break

    covers = tags.get("covr")
    if covers:
        c = covers[0]
        result["cover_base64"] = base64.b64encode(bytes(c)).decode("ascii")
        result["cover_mime"] = "image/jpeg" if c.imageformat == MP4Cover.FORMAT_JPEG else "image/png"

    result["ai_generated"], result["ai_source"] = _detect_ai(
        result["comment"], result["source_url"],
    )
    return result


_WAV_INFO_MAP = {
    "INAM": "title",
    "IART": "artist",
    "IPRD": "album",
    "ICRD": "year",
    "IYER": "year",
    "IGNR": "genre",
    "ICMT": "comment",
    "ITRK": "track",
    "IPRT": "track",
    "TRCK": "track",
    "IBPM": "bpm",
    "TBPM": "bpm",
    "TKEY": "key",
}


def _read_wav_info_chunk(path: str) -> dict:
    """Legge il chunk RIFF LIST/INFO di un file WAV.
    Ritorna un dict con i campi noti. Usato come fallback quando
    il WAV non contiene ID3 embedded."""
    out: dict = {}
    try:
        with open(path, "rb") as f:
            header = f.read(12)
            if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return out
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                chunk_id, chunk_size = struct.unpack("<4sI", hdr)
                if chunk_id == b"LIST":
                    list_type = f.read(4)
                    list_end = f.tell() + (chunk_size - 4)
                    if list_type == b"INFO":
                        while f.tell() < list_end:
                            sub = f.read(8)
                            if len(sub) < 8:
                                break
                            sub_id, sub_size = struct.unpack("<4sI", sub)
                            data = f.read(sub_size).rstrip(b"\x00")
                            if sub_size % 2 == 1:
                                f.read(1)  # padding word-aligned
                            key = _WAV_INFO_MAP.get(sub_id.decode("ascii", errors="ignore"))
                            if not key or not data:
                                continue
                            for enc in ("utf-8", "latin-1"):
                                try:
                                    out[key] = data.decode(enc).strip()
                                    break
                                except UnicodeDecodeError:
                                    continue
                    else:
                        f.seek(list_end)
                else:
                    skip = chunk_size + (chunk_size % 2)
                    f.seek(skip, 1)
    except Exception:
        pass
    return out


def _read_wav(path: str, result: dict) -> dict:
    result["format"] = "WAV"

    # Prima fallback: leggi il chunk INFO (formato RIFF originale)
    info = _read_wav_info_chunk(path)
    for k, v in info.items():
        if v:
            result[k] = v

    # Poi leggi ID3 se presente; ha priorita sui valori INFO
    w = WAVE(path)
    tags = w.tags
    if tags is None:
        return result

    def setif(key, frame_key):
        v = _text(tags.get(frame_key))
        if v:
            result[key] = v

    setif("title", "TIT2")
    setif("artist", "TPE1")
    setif("album_artist", "TPE2")
    setif("album", "TALB")
    setif("year", "TDRC")
    setif("track", "TRCK")
    setif("genre", "TCON")
    setif("bpm", "TBPM")
    setif("key", "TKEY")

    for k in tags.keys():
        if k.startswith("COMM"):
            v = _text(tags[k])
            if v:
                result["comment"] = v
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
        "lyrics": "",           # USLT (MP3), \xa9lyr (M4A), UNSYNCEDLYRICS (FLAC)
        "source_url": "",       # WOAS (MP3), custom (altri) — es. URL Suno
        "ai_generated": False,  # True se rilevato marker AI (C2PA, "made with suno"...)
        "ai_source": "",        # es. "suno", "udio", "riffusion" — sorgente dedotta
        "where_from": _read_where_from(str(p)),
        "is_macos": sys.platform == "darwin",
        "raw_frames": [],       # list of {key, preview, size, kind} — tutti i frame ID3/atomi
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

    # Lyrics (USLT). Rimuovi tutti gli USLT esistenti, poi (ri)crea se non vuoto
    for k in list(tags.keys()):
        if k.startswith("USLT"):
            del tags[k]
    lyrics = data.get("lyrics", "")
    if lyrics:
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))

    # Source URL (WOAS)
    if "source_url" in data:
        src = data.get("source_url", "")
        if "WOAS" in tags:
            del tags["WOAS"]
        if src:
            tags.add(WOAS(url=src))

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
    set_or_del("\xa9lyr", data.get("lyrics", ""))

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
    senza sostituirla. Se cover_path e fornito, la sostituisce.
    Su macOS aggiorna anche l'xattr kMDItemWhereFroms se data['where_from']
    e fornito (lista di stringhe)."""
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

    # macOS extended attribute: kMDItemWhereFroms (lista URL/origini)
    if "where_from" in data:
        _write_where_from(path, data.get("where_from") or [])


def remove_frames(path: str, frame_keys: list) -> int:
    """Rimuove specifici frame ID3 (MP3) o atomi (MP4) dal file.
    Ritorna il numero di frame rimossi. `frame_keys` sono le chiavi
    esatte così come tornano da `raw_frames` (es. "TXXX:comment",
    "GEOB:c2pa manifest store", "\xa9lyr")."""
    if not frame_keys:
        return 0
    ext = Path(path).suffix.lower()
    removed = 0
    if ext == ".mp3":
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            return 0
        for key in frame_keys:
            if key in tags:
                del tags[key]
                removed += 1
        if removed:
            tags.save(path)
    elif ext in (".m4a", ".mp4", ".aac"):
        m = MP4(path)
        if m.tags is None:
            return 0
        for key in frame_keys:
            if key in m.tags:
                del m.tags[key]
                removed += 1
        if removed:
            m.save()
    else:
        raise ValueError(f"Rimozione frame non supportata per: {ext}")
    return removed
