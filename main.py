"""MusicDownload — Entry point (pywebview + WebKit/EdgeChromium)."""

import os
import sys
from pathlib import Path

import webview

from api.bridge import Api


def _resource_path(*parts) -> str:
    """Trova il path di una risorsa sia in dev che bundled (PyInstaller)."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent
    return str(base.joinpath(*parts))


def main():
    api = Api()
    index_path = _resource_path("webui", "index.html")

    window = webview.create_window(
        title="MusicDownload",
        url=index_path,
        js_api=api,
        width=1080,
        height=720,
        min_size=(900, 600),
        background_color="#0A0A0A",
        resizable=True,
    )
    api.window = window

    # Disable native menu / set dark on macOS
    webview.start(debug=False)


if __name__ == "__main__":
    main()
