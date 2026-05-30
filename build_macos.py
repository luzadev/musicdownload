#!/usr/bin/env python3
"""
Build script per creare MusicDownload.app su macOS.

Uso:
    python3 build_macos.py

Cosa fa:
1. Scarica il binario standalone di yt-dlp per macOS
2. Raccoglie ffmpeg + ffprobe + tutte le loro dylib da Homebrew
3. Esegue PyInstaller per creare MusicDownload.app

Requisiti:
    pip3 install pyinstaller
    brew install ffmpeg
"""

import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
BUNDLE_DIR = ROOT / "bundle_bin"  # binari da includere nell'app


def log(msg):
    print(f"\n>>> {msg}")


# =========================================================================
# 1. Scarica yt-dlp standalone
# =========================================================================
def download_ytdlp():
    """Scarica il binario standalone di yt-dlp per macOS."""
    arch = platform.machine()  # arm64 o x86_64
    if arch == "arm64":
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
    else:
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos_legacy"

    dest = BUNDLE_DIR / "yt-dlp"
    if dest.exists():
        log(f"yt-dlp gia presente: {dest}")
        return dest

    log(f"Scarico yt-dlp da {url} ...")
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    # Usa curl perche urllib di Python 3.8 ha problemi SSL su macOS
    subprocess.run(
        ["curl", "-L", "-o", str(dest), url],
        check=True,
    )
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    log(f"yt-dlp scaricato: {dest}")
    return dest


# =========================================================================
# 2. Raccogli ffmpeg/ffprobe + dylib
# =========================================================================
def find_brew_binary(name):
    """Trova il percorso reale di un binario brew."""
    path = shutil.which(name, path="/opt/homebrew/bin:/usr/local/bin")
    if not path:
        path = shutil.which(name)
    if not path:
        print(f"ERRORE: {name} non trovato. Installa con: brew install {name}")
        sys.exit(1)
    return str(Path(path).resolve())


def collect_dylibs(binary_path, collected=None):
    """Raccoglie ricorsivamente tutte le dylib linkate da un binario."""
    if collected is None:
        collected = set()

    result = subprocess.run(
        ["otool", "-L", binary_path],
        capture_output=True, text=True,
    )

    for line in result.stdout.splitlines()[1:]:  # skip prima riga (nome binario)
        line = line.strip()
        match = re.match(r"(.+\.dylib)\s+\(", line)
        if not match:
            continue
        dylib = match.group(1).strip()
        # Includi solo librerie homebrew (non di sistema)
        if dylib.startswith("/opt/homebrew/") or dylib.startswith("/usr/local/"):
            real = str(Path(dylib).resolve())
            if real not in collected and os.path.exists(real):
                collected.add(real)
                # Raccogli ricorsivamente
                collect_dylibs(real, collected)

    return collected


def bundle_ffmpeg():
    """Copia ffmpeg, ffprobe e tutte le loro dylib in bundle_bin/."""
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    ffmpeg_path = find_brew_binary("ffmpeg")
    ffprobe_path = find_brew_binary("ffprobe")

    log("Raccolgo librerie dinamiche di ffmpeg/ffprobe...")
    all_dylibs = set()
    collect_dylibs(ffmpeg_path, all_dylibs)
    collect_dylibs(ffprobe_path, all_dylibs)

    log(f"Trovate {len(all_dylibs)} dylib")

    # Copia binari
    for src in (ffmpeg_path, ffprobe_path):
        dst = BUNDLE_DIR / Path(src).name
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
        log(f"  Copiato: {Path(src).name}")

    # Copia dylib
    lib_dir = BUNDLE_DIR / "lib"
    lib_dir.mkdir(exist_ok=True)

    for dylib in sorted(all_dylibs):
        dst = lib_dir / Path(dylib).name
        shutil.copy2(dylib, dst)

    log(f"  Copiate {len(all_dylibs)} librerie in bundle_bin/lib/")

    # Fix rpath nei binari: cambia i riferimenti /opt/homebrew/... a @executable_path/lib/
    log("Fix rpath nei binari...")
    for binary_name in ("ffmpeg", "ffprobe"):
        binary = BUNDLE_DIR / binary_name
        _fix_rpaths(binary, all_dylibs)

    # Fix rpath nelle dylib stesse
    for dylib in sorted(all_dylibs):
        dst = lib_dir / Path(dylib).name
        _fix_rpaths(dst, all_dylibs, is_dylib=True)

    log("ffmpeg/ffprobe bundled con successo")


def _fix_rpaths(binary, all_dylibs, is_dylib=False):
    """Sostituisce i path assoluti delle dylib con path relativi."""
    prefix = "@executable_path/lib/" if not is_dylib else "@loader_path/"

    # Se e una dylib, fix anche il suo install name
    if is_dylib:
        subprocess.run(
            ["install_name_tool", "-id",
             f"@loader_path/{binary.name}", str(binary)],
            capture_output=True,
        )

    for dylib in all_dylibs:
        dylib_name = Path(dylib).name
        subprocess.run(
            ["install_name_tool", "-change",
             dylib, f"{prefix}{dylib_name}", str(binary)],
            capture_output=True,
        )
        # Prova anche con path non-resolved (symlink)
        for brew_prefix in ("/opt/homebrew", "/usr/local"):
            for alt in (f"{brew_prefix}/opt/", f"{brew_prefix}/lib/", f"{brew_prefix}/Cellar/"):
                result = subprocess.run(
                    ["otool", "-L", str(binary)],
                    capture_output=True, text=True,
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if dylib_name in line and (alt in line):
                        old_path = re.match(r"(.+\.dylib)", line)
                        if old_path:
                            subprocess.run(
                                ["install_name_tool", "-change",
                                 old_path.group(1).strip(),
                                 f"{prefix}{dylib_name}", str(binary)],
                                capture_output=True,
                            )


# =========================================================================
# 3. PyInstaller
# =========================================================================
def run_pyinstaller():
    """Esegue PyInstaller per creare l'app."""
    log("Eseguo PyInstaller...")

    # Genera lista --add-binary per i binari bundled
    add_binaries = []
    for f in BUNDLE_DIR.iterdir():
        if f.is_file() and not f.name.startswith("."):
            add_binaries.extend(["--add-binary", f"{f}:."])
    # Dylibs in lib/
    lib_dir = BUNDLE_DIR / "lib"
    if lib_dir.exists():
        for f in lib_dir.iterdir():
            if f.is_file():
                add_binaries.extend(["--add-binary", f"{f}:lib"])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "MusicDownload",
        "--windowed",
        "--onedir",
        "--noconfirm",
        # Web UI assets (HTML/CSS/JS) — usati da pywebview
        "--add-data", f"{ROOT / 'webui'}:webui",
        # Hidden imports per pywebview (WebKit su macOS)
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.cocoa",
        "--hidden-import", "requests",
        # Binari bundled (yt-dlp, ffmpeg, ffprobe + dylibs)
        *add_binaries,
        # Entry point
        str(ROOT / "main.py"),
    ]

    log(f"Comando: {' '.join(cmd[:10])}...")
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    app_path = DIST_DIR / "MusicDownload.app"
    if app_path.exists():
        log(f"Build completata: {app_path}")
        # Mostra dimensione
        size = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file())
        log(f"Dimensione: {size / 1024 / 1024:.0f} MB")
    else:
        log("ATTENZIONE: .app non trovata, controlla l'output di PyInstaller")
        # Potrebbe essere in dist/MusicDownload/ (non .app)
        alt = DIST_DIR / "MusicDownload"
        if alt.exists():
            log(f"Trovata directory: {alt}")


# =========================================================================
# Main
# =========================================================================
def main():
    print("=" * 50)
    print("  MusicDownload — Build macOS")
    print("=" * 50)

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
    bundle_ffmpeg()
    run_pyinstaller()

    print("\n" + "=" * 50)
    print("  DONE!")
    print("=" * 50)
    app = DIST_DIR / "MusicDownload.app"
    if app.exists():
        print(f"\n  L'app e in: {app}")
        print(f"  Per testarla: open '{app}'")
        print(f"\n  Per distribuirla, comprimi la cartella:")
        print(f"  zip -r MusicDownload.zip dist/MusicDownload.app")
    print()


if __name__ == "__main__":
    main()
