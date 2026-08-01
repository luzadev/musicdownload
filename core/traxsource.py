"""Fetch Top 100 Traxsource per genere.

Approccio: session curl_cffi (bypass CF via cookie) + BeautifulSoup HTML scraping.
Spec: docs/superpowers/specs/2026-08-01-traxsource-charts-design.md.
"""

from __future__ import annotations

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
