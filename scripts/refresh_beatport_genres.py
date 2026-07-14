"""Estrae lo slug + numeric id di tutti i generi Beatport.
Uso: python3 scripts/refresh_beatport_genres.py > /tmp/genres.txt
Poi copia manualmente in core/beatport.py::GENRES.

Nota: la pagina /genres (task originale) restituisce 404 sull'attuale sito
Beatport. Aggreghiamo quindi la lista dei generi dalla pagina /charts, dove
ogni featured chart include un array `genres` completo di slug + id + name.
"""

from __future__ import annotations

import re
import json
import sys
from curl_cffi import requests


GENRES_URL = "https://www.beatport.com/genres"
CHARTS_URL = "https://www.beatport.com/charts"


def _fetch_next_data(url: str) -> dict:
    resp = requests.get(url, impersonate="chrome131", timeout=15)
    resp.raise_for_status()
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL
    )
    if not m:
        raise RuntimeError(f"__NEXT_DATA__ non trovato su {url}")
    return json.loads(m.group(1))


def _collect_genres(node, out: dict) -> None:
    """Raccoglie ricorsivamente ogni dict con chiavi slug/id/name che appare
    dentro un array chiamato "genres"."""
    if isinstance(node, dict):
        for k, v in node.items():
            if (
                k == "genres"
                and isinstance(v, list)
                and v
                and all(
                    isinstance(x, dict) and "slug" in x and "id" in x and "name" in x
                    for x in v
                )
            ):
                for g in v:
                    out[g["id"]] = (g["slug"], g["name"])
            else:
                _collect_genres(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_genres(item, out)


def main() -> int:
    # Prova /genres (URL originale). Se 404 o schema inatteso, cade su /charts.
    try:
        data = _fetch_next_data(GENRES_URL)
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
        for q in queries:
            d = q.get("state", {}).get("data", {})
            if (
                isinstance(d, dict)
                and "results" in d
                and isinstance(d["results"], list)
            ):
                for g in d["results"]:
                    if "slug" in g and "id" in g and "name" in g:
                        print(f'    "{g["slug"]}": ({g["id"]}, "{g["name"]}"),')
        return 0
    except Exception as e:
        print(f"# /genres non disponibile ({e}), fallback su /charts", file=sys.stderr)

    data = _fetch_next_data(CHARTS_URL)
    genres: dict = {}
    _collect_genres(data, genres)
    if not genres:
        print("nessun genere trovato su /charts", file=sys.stderr)
        return 1
    for gid in sorted(genres):
        slug, name = genres[gid]
        print(f'    "{slug}": ({gid}, "{name}"),')
    return 0


if __name__ == "__main__":
    sys.exit(main())
