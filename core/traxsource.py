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


_TOP100_LINK_RE = re.compile(r'href="(/title/\d+/top-100-[a-z0-9-]+)"')


def _discover_top100_url(genre_html: str) -> str:
    """Estrae il path relativo della playlist Top 100 corrente dalla pagina di un genere."""
    m = _TOP100_LINK_RE.search(genre_html)
    if not m:
        raise TraxsourceParseError("link Top 100 non trovato nella pagina genere")
    return m.group(1)


def _parse_tracks(html: str) -> list:
    """Parsa la pagina Top 100 (title playlist) e ritorna list[TraxsourceTrack].

    Selettori (verificati su fixture tech-house 2026-07):
      row       = div.trk-row.play-trk (data-trid=<int>)
      position  = div.tnum (inside div.tnum-pos)
      title <a> = div.trk-cell.title a[href^="/track/"]
      version   = span.version (contiene child span.duration da rimuovere)
      artists   = a.com-artists (uno o piu)
      label <a> = div.trk-cell.label a
      cover img = div.trk-cell.thumb img (src /scripts/image.php/52x52/...)
    """
    # Lazy import — bs4 non e' hard-dep del modulo (importato solo quando serve).
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.trk-row.play-trk")
    if not rows:
        raise TraxsourceParseError("nessuna track (div.trk-row.play-trk) trovata")

    out: list = []
    for i, row in enumerate(rows, 1):
        try:
            trid = int(row.get("data-trid") or 0)

            pos_el = row.select_one("div.tnum")
            position = i  # fallback su enumerate se pos manca / non e' un numero
            if pos_el:
                pos_txt = pos_el.get_text(strip=True)
                if pos_txt.isdigit():
                    position = int(pos_txt)

            title_a = row.select_one('div.trk-cell.title a[href^="/track/"]')
            if not title_a:
                continue
            title = title_a.get_text(strip=True)
            href = title_a.get("href") or ""
            slug = href.rsplit("/", 1)[-1]

            # Mix version: contenuto di span.version, escluso span.duration
            mix = ""
            version_el = row.select_one("span.version")
            if version_el:
                dur_el = version_el.select_one("span.duration")
                if dur_el:
                    dur_el.extract()
                mix = version_el.get_text(strip=True)

            artist_names = [a.get_text(strip=True) for a in row.select("a.com-artists")]
            artists = _format_artists(artist_names)

            label_a = row.select_one("div.trk-cell.label a")
            label = label_a.get_text(strip=True) if label_a else ""

            img = row.select_one('div.trk-cell.thumb img[src*="/scripts/image.php/"]')
            image_url = (img.get("src") or "") if img else ""
            cover_large = _large_cover(image_url)

            out.append(TraxsourceTrack(
                position=position,
                title=title,
                mix=mix,
                artists=artists,
                label=label,
                traxsource_id=trid,
                slug=slug,
                image_url=image_url,
                cover_url_large=cover_large,
            ))
        except Exception as e:
            raise TraxsourceParseError(f"errore parse track[{i}]: {e}") from e
    return out
