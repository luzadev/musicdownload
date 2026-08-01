"""Estrae la lista dei generi Traxsource dalla pagina /top.
Uso: python3 scripts/refresh_traxsource_genres.py > /tmp/tx_genres.txt
Poi copia manualmente in core/traxsource.py::GENRES."""

from __future__ import annotations

import re
import sys
from curl_cffi import requests


def main() -> int:
    s = requests.Session(impersonate="chrome131")
    s.get("https://www.traxsource.com/", timeout=15)
    r = s.get("https://www.traxsource.com/top", timeout=15,
              headers={"Referer": "https://www.traxsource.com/"})
    if r.status_code != 200:
        print(f"HTTP {r.status_code}", file=sys.stderr)
        return 1
    # href="/genre/<id>/<slug>"
    hits = re.findall(r'href="/genre/(\d+)/([a-z0-9-]+)"', r.text)
    seen = set()
    for gid, slug in hits:
        if slug in seen:
            continue
        seen.add(slug)
        # Display name = slug con capitalizzazione euristica (l'utente lo raffina a mano)
        name = " ".join(w.capitalize() for w in slug.replace("-", " ").split())
        print(f'    "{slug}": ({gid}, "{name}"),')
    return 0


if __name__ == "__main__":
    sys.exit(main())
