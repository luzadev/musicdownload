"""
Build script per creare MusicTools.exe su Windows.

Uso:
    python build_windows.py

Cosa fa:
1. Scarica il binario standalone di yt-dlp per Windows
2. Scarica ffmpeg static build per Windows
3. Esegue PyInstaller per creare MusicTools.exe

Requisiti:
    pip install pyinstaller
    pip install -r requirements.txt
"""

import io
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
BUNDLE_DIR = ROOT / "bundle_bin"

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


def log(msg):
    print(f"\n>>> {msg}")


# =========================================================================
# 1. Scarica yt-dlp.exe
# =========================================================================
def download_ytdlp():
    dest = BUNDLE_DIR / "yt-dlp.exe"
    if dest.exists():
        log(f"yt-dlp.exe gia presente: {dest}")
        return dest

    log(f"Scarico yt-dlp.exe ...")
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(YTDLP_URL, dest)
    log(f"yt-dlp.exe scaricato ({dest.stat().st_size // 1024 // 1024} MB)")
    return dest


# =========================================================================
# 2. Scarica ffmpeg static build
# =========================================================================
def download_ffmpeg():
    ffmpeg_exe = BUNDLE_DIR / "ffmpeg.exe"
    ffprobe_exe = BUNDLE_DIR / "ffprobe.exe"

    if ffmpeg_exe.exists() and ffprobe_exe.exists():
        log("ffmpeg.exe e ffprobe.exe gia presenti")
        return

    log("Scarico ffmpeg static build per Windows ...")
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    # Scarica lo zip in memoria
    response = urllib.request.urlopen(FFMPEG_URL)
    zip_data = io.BytesIO(response.read())
    log("Download completato, estraggo ffmpeg.exe e ffprobe.exe ...")

    with zipfile.ZipFile(zip_data) as zf:
        for member in zf.namelist():
            basename = Path(member).name
            if basename in ("ffmpeg.exe", "ffprobe.exe"):
                # Estrai solo il file, senza sottocartelle
                data = zf.read(member)
                dest = BUNDLE_DIR / basename
                dest.write_bytes(data)
                log(f"  Estratto: {basename} ({len(data) // 1024 // 1024} MB)")

    if not ffmpeg_exe.exists():
        print("ERRORE: ffmpeg.exe non trovato nello zip!")
        sys.exit(1)


# =========================================================================
# 3. PyInstaller
# =========================================================================
def run_pyinstaller():
    log("Eseguo PyInstaller...")

    # Genera lista --add-binary per i binari bundled
    add_binaries = []
    for f in BUNDLE_DIR.iterdir():
        if f.is_file() and f.suffix in (".exe", ""):
            add_binaries.extend(["--add-binary", f"{f};."])

    icon_path = ROOT / "assets" / "icon.ico"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "MusicTools",
        "--windowed",
        "--onedir",
        "--noconfirm",
    ]
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])
    cmd.extend([
        # Web UI assets (HTML/CSS/JS) — usati da pywebview
        "--add-data", f"{ROOT / 'webui'};webui",
        # Hidden imports per pywebview (EdgeChromium su Windows)
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "clr",
        "--hidden-import", "clr_loader",
        "--hidden-import", "requests",
        # Collegamenti completi: webview, pythonnet, clr_loader (porta
        # con se Python.Runtime.dll + nethost.dll + runtimeconfig.json
        # altrimenti winforms.py fallisce con "Failed to resolve
        # Python.Runtime.Loader.Initialize ...")
        "--collect-all", "webview",
        "--collect-all", "pythonnet",
        "--collect-all", "clr_loader",
        "--collect-all", "mutagen",
        "--copy-metadata", "pythonnet",
        "--copy-metadata", "clr_loader",
        # Binari bundled
        *add_binaries,
        # Entry point
        str(ROOT / "main.py"),
    ])

    log(f"Comando: {' '.join(cmd[:10])}...")
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    exe_path = DIST_DIR / "MusicTools" / "MusicTools.exe"
    if exe_path.exists():
        log(f"Build completata: {exe_path}")
    else:
        log("ATTENZIONE: MusicTools.exe non trovato, controlla l'output")


# =========================================================================
# Main
# =========================================================================
def main():
    print("=" * 50)
    print("  MusicTools - Build Windows")
    print("=" * 50)

    if sys.platform != "win32":
        print("\nATTENZIONE: Questo script va eseguito su Windows!")
        print("PyInstaller non supporta cross-compilation.")
        print("Copia il progetto su una macchina Windows e rilancia.")
        sys.exit(1)

    # Verifica pyinstaller
    try:
        import PyInstaller
        log(f"PyInstaller {PyInstaller.__version__}")
    except ImportError:
        log("Installo PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                       check=True)

    # Pulisci bundle precedente
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)

    download_ytdlp()
    download_ffmpeg()
    run_pyinstaller()

    print("\n" + "=" * 50)
    print("  DONE!")
    print("=" * 50)
    dist = DIST_DIR / "MusicTools"
    if dist.exists():
        print(f"\n  L'app e in: {dist}")
        print(f"  Eseguibile: {dist / 'MusicTools.exe'}")
        print(f"\n  Per distribuirla, comprimi la cartella:")
        print(f"  Comprimi {dist} -> MusicTools_Windows.zip")
    print()


if __name__ == "__main__":
    main()
