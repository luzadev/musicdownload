"""Fetch Top 100 Traxsource per genere.

Approccio: session curl_cffi (bypass CF via cookie) + BeautifulSoup HTML scraping.
Spec: docs/superpowers/specs/2026-08-01-traxsource-charts-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Generi musicali Traxsource (slug -> (id, display_name)).
# Aggiornato via scripts/refresh_traxsource_genres.py. Esclusi "sounds/samples/loops",
# "acapella", "beats", "efx-dj-tools", "stems" (non generi ma tipi di prodotto).
GENRES: dict = {
    "afro-house": (27, "Afro House"),
    "afro-latin-brazilian": (23, "Afro / Latin / Brazilian"),
    "broken-beat-nu-jazz": (2, "Broken Beat / Nu Jazz"),
    "classic-house": (12, "Classic House"),
    "deep-house": (13, "Deep House"),
    "drum-and-bass": (31, "Drum & Bass"),
    "electro-house": (11, "Electro House"),
    "electronica": (5, "Electronica"),
    "garage": (29, "Garage"),
    "house": (4, "House"),
    "jackin-house": (15, "Jackin House"),
    "leftfield": (14, "Leftfield"),
    "lounge-chill-out": (1, "Lounge / Chill Out"),
    "melodic-progressive-house": (19, "Melodic / Progressive House"),
    "minimal-deep-tech": (16, "Minimal / Deep Tech"),
    "nu-disco-indie-dance": (17, "Nu Disco / Indie Dance"),
    "pop-dance": (32, "Pop Dance"),
    "r-and-b-hip-hop": (6, "R&B / Hip Hop"),
    "soul-funk-disco": (3, "Soul / Funk / Disco"),
    "soulful-house": (24, "Soulful House"),
    "tech-house": (18, "Tech House"),
    "techno": (20, "Techno"),
    "world": (30, "World"),
}


@dataclass(frozen=True)
class TraxsourceTrack:
    position: int
    title: str
    mix: str
    artists: str
    label: str
    traxsource_id: int
    slug: str
    image_url: str = ""
    cover_url_large: str = ""


def list_genres() -> list:
    result = [
        {"slug": slug, "id": gid, "name": name}
        for slug, (gid, name) in GENRES.items()
    ]
    result.sort(key=lambda g: g["name"].casefold())
    return result


class TraxsourceError(Exception):
    """Base per errori Traxsource."""


class TraxsourceUnreachableError(TraxsourceError):
    """Rete / 5xx dopo retry."""


class TraxsourceParseError(TraxsourceError):
    """HTML ricevuto ma non conforme allo schema atteso."""


_MIX_PAREN_RE = re.compile(r"^(.*)\s*\(([^()]+)\)\s*$")
_SIZE_RE = re.compile(r"/\d+x\d+/")


def _split_title_mix(full_title: str) -> tuple:
    """Estrae mix dalle parentesi finali. 'Foo (Extended Mix)' -> ('Foo', 'Extended Mix').
    Se non ci sono parentesi finali, mix = ''."""
    if not full_title:
        return ("", "")
    m = _MIX_PAREN_RE.match(full_title.strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (full_title.strip(), "")


def _format_artists(names: list) -> str:
    """['A', 'B', 'C'] -> 'A, B & C'. Strips whitespace."""
    clean = [n.strip() for n in names if n and n.strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    return ", ".join(clean[:-1]) + " & " + clean[-1]


def _large_cover(url: str) -> str:
    """Sostituisce /NxN/ nel path con /500x500/. Se pattern assente, ritorna invariato."""
    if not url:
        return ""
    return _SIZE_RE.sub("/500x500/", url)
