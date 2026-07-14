"""Fetch Top 100 Beatport per genere.

Approccio: estrai il JSON `__NEXT_DATA__` dal HTML della pagina Next.js.
Bypass Cloudflare via curl_cffi (TLS impersonation).
Vedi docs/superpowers/specs/2026-07-14-beatport-charts-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BeatportTrack:
    position: int
    title: str
    mix: str          # es. "Extended Mix", "Original Mix", ""
    artists: str      # es. "A, B & C" già formattato
    duration_sec: int
    beatport_id: int

    @property
    def display(self) -> str:
        """Formato testo compatibile coi file .txt curati a mano:
        'Artista – Titolo (Mix) (M:SS)'."""
        m, s = divmod(self.duration_sec, 60)
        return f"{self.artists} – {self.title} ({self.mix}) ({m}:{s:02d})"

    @property
    def spotify_query(self) -> str:
        """Query pura per la search Spotify (senza mix name, che disturba
        il matching su titoli tipo 'Extended Mix')."""
        return f"{self.artists} {self.title}"


# Mappa slug URL Beatport -> (numeric_id, display_name)
# Enumerata via scripts/refresh_beatport_genres.py (Task 1).
# Copia dell'output di /tmp/genres_output.txt (31 generi).
GENRES: dict = {
    "drum-bass": (1, "Drum & Bass"),
    "hard-techno": (2, "Hard Techno"),
    "electronica": (3, "Electronica"),
    "house": (5, "House"),
    "techno-peak-time-driving": (6, "Techno (Peak Time / Driving)"),
    "trance-main-floor": (7, "Trance (Main Floor)"),
    "hard-dance-hardcore-neo-rave": (8, "Hard Dance / Hardcore / Neo Rave"),
    "breaks-breakbeat-uk-bass": (9, "Breaks / Breakbeat / UK Bass"),
    "tech-house": (11, "Tech House"),
    "deep-house": (12, "Deep House"),
    "psy-trance": (13, "Psy-Trance"),
    "minimal-deep-tech": (14, "Minimal / Deep Tech"),
    "progressive-house": (15, "Progressive House"),
    "dubstep": (18, "Dubstep"),
    "indie-dance": (37, "Indie Dance"),
    "trap-future-bass": (38, "Trap / Future Bass"),
    "dance-pop": (39, "Dance / Pop"),
    "nu-disco-disco": (50, "Nu Disco / Disco"),
    "funky-house": (81, "Funky House"),
    "bass-club": (85, "Bass / Club"),
    "uk-garage-bassline": (86, "UK Garage / Bassline"),
    "afro-house": (89, "Afro House"),
    "melodic-house-techno": (90, "Melodic House & Techno"),
    "bass-house": (91, "Bass House"),
    "techno-raw-deep-hypnotic": (92, "Techno (Raw / Deep / Hypnotic)"),
    "organic-house": (93, "Organic House"),
    "electro-classic-detroit-modern": (94, "Electro (Classic / Detroit / Modern)"),
    "140-deep-dubstep-grime": (95, "140 / Deep Dubstep / Grime"),
    "mainstage": (96, "Mainstage"),
    "jackin-house": (97, "Jackin House"),
    "trance-raw-deep-hypnotic": (99, "Trance (Raw / Deep / Hypnotic)"),
}


def list_genres() -> list:
    """Ritorna [{slug, id, name}, ...] ordinato alfabeticamente per name."""
    result = [
        {"slug": slug, "id": gid, "name": name}
        for slug, (gid, name) in GENRES.items()
    ]
    result.sort(key=lambda g: g["name"].casefold())
    return result
