"""MusicTools — Entry point (pywebview + WebKit/EdgeChromium)."""

import os
import sys
from pathlib import Path

# Windows: forza il caricamento del runtime pythonnet PRIMA di importare
# webview. Con PyInstaller il lazy-loader fallisce con
# "Failed to resolve Python.Runtime.Loader.Initialize" perche'
# Python.Runtime.dll viene bundlata ma il loader non sa risolverla
# senza l'inizializzazione esplicita. Fix conferma:
# https://github.com/pythonnet/pythonnet/issues/2178
if sys.platform == "win32":
    try:
        # Punta pythonnet ai propri file runtime dentro al bundle PyInstaller.
        if getattr(sys, "frozen", False):
            _bundle = Path(sys._MEIPASS)  # type: ignore[attr-defined]
            _rt = _bundle / "pythonnet" / "runtime"
            if _rt.exists():
                os.environ["PYTHONNET_RUNTIME"] = "netfx"
                os.environ["PYTHONNET_PYDLL"] = sys.executable
        from pythonnet import load as _pythonnet_load
        _pythonnet_load("netfx")
        import clr  # noqa: F401  - inizializza il loader
    except Exception as _e:
        # Se il preload fallisce, lasciamo che webview tenti comunque:
        # l'errore originale verra' mostrato con stack trace.
        print(f"[bootstrap] preload pythonnet failed: {_e}")

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
        title="MusicTools",
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
