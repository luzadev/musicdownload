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
    # ============================================================
    # Fix Windows: rimuovi Mark of the Web (MOTW) dalle DLL bundled.
    # Quando l'utente scarica il .zip dal browser, Windows aggiunge
    # uno stream NTFS Zone.Identifier a TUTTI i file estratti.
    # .NET Framework 4.x rifiuta silenziosamente di risolvere i
    # symbol export degli assembly managed con MOTW -> il loader
    # netfx di pythonnet fallisce con "Failed to resolve
    # Python.Runtime.Loader.Initialize".
    # Soluzione: cancelliamo lo stream :Zone.Identifier da ogni
    # .dll/.exe del bundle al primo avvio (operazione idempotente
    # e sicura: l'utente ha gia eseguito l'exe esplicitamente).
    # Vedi: https://github.com/r0x0r/pywebview/issues/1215
    # ============================================================
    if getattr(sys, "frozen", False):
        try:
            import ctypes
            _kernel32 = ctypes.windll.kernel32
            _bundle = Path(sys._MEIPASS)  # type: ignore[attr-defined]
            for _f in _bundle.rglob("*"):
                if _f.suffix.lower() in (".dll", ".exe", ".pyd"):
                    _kernel32.DeleteFileW(f"{_f}:Zone.Identifier")
        except Exception as _e:
            print(f"[bootstrap] MOTW cleanup failed: {_e}")

    try:
        if getattr(sys, "frozen", False):
            os.environ["PYTHONNET_RUNTIME"] = "netfx"
        from pythonnet import load as _pythonnet_load
        _pythonnet_load("netfx")
        import clr  # noqa: F401  - inizializza il loader
    except Exception as _e:
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
