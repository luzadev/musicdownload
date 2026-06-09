#!/usr/bin/env python3
"""
Build script per creare MusicTools.app su macOS.

Uso:
    python3 build_macos.py

Cosa fa:
1. Scarica il binario standalone di yt-dlp per macOS
2. Raccoglie ffmpeg + ffprobe + tutte le loro dylib da Homebrew
3. Esegue PyInstaller per creare MusicTools.app

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

    icon_path = ROOT / "assets" / "icon.icns"
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
        "--add-data", f"{ROOT / 'webui'}:webui",
        # Hidden imports per pywebview (WebKit su macOS)
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.cocoa",
        "--hidden-import", "requests",
        "--collect-all", "mutagen",
        # Binari bundled (yt-dlp, ffmpeg, ffprobe + dylibs)
        *add_binaries,
        # Entry point
        str(ROOT / "main.py"),
    ])

    log(f"Comando: {' '.join(cmd[:10])}...")
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    app_path = DIST_DIR / "MusicTools.app"
    if app_path.exists():
        log(f"Build completata: {app_path}")
        patch_info_plist(app_path)
        wrap_subprocess_in_bundle(app_path)
        adhoc_codesign(app_path)
        # Mostra dimensione
        size = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file())
        log(f"Dimensione: {size / 1024 / 1024:.0f} MB")
    else:
        log("ATTENZIONE: .app non trovata, controlla l'output di PyInstaller")
        # Potrebbe essere in dist/MusicTools/ (non .app)
        alt = DIST_DIR / "MusicTools"
        if alt.exists():
            log(f"Trovata directory: {alt}")


def patch_info_plist(app_path):
    """Aggiunge le chiavi TCC (Transparency, Consent and Control) richieste
    da macOS nel bundle .app, altrimenti macOS nega silenziosamente l'accesso
    al microfono e l'app NON compare in Impostazioni > Privacy e sicurezza.

    Senza NSMicrophoneUsageDescription, qualsiasi tentativo di ffmpeg di
    aprire un dispositivo audio (incluso BlackHole) viene rifiutato dal
    sistema e non viene mostrato nessun prompt all'utente.
    """
    info_plist = app_path / "Contents" / "Info.plist"
    if not info_plist.exists():
        log("ATTENZIONE: Info.plist non trovato, skip patch TCC")
        return

    pb = "/usr/libexec/PlistBuddy"

    # Helper: aggiungi una chiave; se gia presente sovrascrivila.
    def add_or_set(key, value, ptype="string"):
        # Tenta Add; se esiste, fa Set.
        r = subprocess.run(
            [pb, "-c", f'Add :{key} {ptype} "{value}"', str(info_plist)],
            capture_output=True, text=True,
        )
        if r.returncode != 0 and "already exists" in (r.stderr + r.stdout).lower():
            subprocess.run(
                [pb, "-c", f'Set :{key} "{value}"', str(info_plist)],
                check=True,
            )

    log("Patching Info.plist con le chiavi TCC...")
    add_or_set(
        "NSMicrophoneUsageDescription",
        "MusicTools usa il microfono per registrare l'audio del sistema "
        "(ad esempio tramite BlackHole o un altro dispositivo loopback).",
    )
    # Sicurezza extra: dichiarare bundle identifier stabile aiuta il
    # database TCC a riconoscere coerentemente l'app tra le sessioni.
    add_or_set("CFBundleIdentifier", "com.djluza.musictools")
    add_or_set("LSApplicationCategoryType", "public.app-category.music")
    log("Info.plist aggiornato.")


_BUNDLE_ID = "com.djluza.musictools"


def _subprocess_info_plist(executable, bundle_id):
    """Info.plist per un mini-bundle che incapsula un binario subprocess.

    NSMicrophoneUsageDescription qui dentro e' la chiave: senza di essa,
    macOS uccide il subprocess con SIGABRT appena tenta di aprire un
    device audio, anche se il main MusicTools ha il proprio TCC concesso.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'    <key>CFBundleExecutable</key><string>{executable}</string>\n'
        f'    <key>CFBundleIdentifier</key><string>{bundle_id}</string>\n'
        f'    <key>CFBundleName</key><string>{executable}</string>\n'
        '    <key>CFBundlePackageType</key><string>APPL</string>\n'
        '    <key>CFBundleShortVersionString</key><string>1.0</string>\n'
        '    <key>CFBundleVersion</key><string>1</string>\n'
        '    <key>LSBackgroundOnly</key><true/>\n'
        '    <key>LSUIElement</key><true/>\n'
        '    <key>NSMicrophoneUsageDescription</key>\n'
        '    <string>MusicTools usa il microfono per registrare l\'audio del '
        'sistema (BlackHole o altri dispositivi loopback).</string>\n'
        '</dict>\n'
        '</plist>\n'
    )


def wrap_subprocess_in_bundle(app_path):
    """Sposta ffmpeg e ffprobe in mini-bundle .app dentro Frameworks/.

    macOS 14+ ENFORCE il fatto che ogni binario che apre device
    privacy-sensitive (microfono, camera, ...) debba avere un proprio
    Info.plist accessibile con NSMicrophoneUsageDescription. Quando
    ffmpeg viene lanciato come binario standalone (anche se figlio di
    MusicTools), non c'e' Info.plist associato -> SIGABRT.

    Soluzione: incapsulare ffmpeg in MusicTools.app/Contents/Frameworks/
    ffmpeg.app/Contents/MacOS/ffmpeg, con Info.plist nel suo bundle.
    Stesso per ffprobe.
    """
    log("Wrapping ffmpeg e ffprobe in sub-bundle .app...")
    fw = app_path / "Contents" / "Frameworks"
    if not fw.exists():
        log("ATTENZIONE: Contents/Frameworks non trovato, skip wrapping.")
        return

    for name in ("ffmpeg", "ffprobe"):
        src = fw / name
        if not src.exists() or not src.is_file():
            log(f"  skip {name}: non trovato in Frameworks/")
            continue
        wrap = fw / f"{name}.app"
        if wrap.exists():
            shutil.rmtree(wrap)
        macos = wrap / "Contents" / "MacOS"
        macos.mkdir(parents=True, exist_ok=True)
        dest = macos / name
        shutil.move(str(src), str(dest))
        dest.chmod(0o755)

        # Aggiungi un nuovo rpath che punta a Contents/Frameworks/ (dove
        # stanno le dylib del bundle MusicTools).
        # @executable_path = ffmpeg.app/Contents/MacOS/
        # ../../../ = MusicTools.app/Contents/Frameworks/
        subprocess.run(
            ["install_name_tool", "-add_rpath",
             "@executable_path/../../../", str(dest)],
            capture_output=True,
        )

        # Crea Info.plist con NSMicrophoneUsageDescription.
        info = wrap / "Contents" / "Info.plist"
        bundle_id = f"com.djluza.musictools.{name}"
        info.write_text(_subprocess_info_plist(name, bundle_id))
        log(f"  wrap: {name} -> {dest.relative_to(app_path)}")


def adhoc_codesign(app_path):
    """Ad-hoc codesign dell'intero bundle .app con identifier coerente.

    macOS tratta ogni binario Mach-O firmato come una "app" distinta per
    le decisioni TCC (microfono, camera, ecc.). Con `codesign --deep`
    standard, i nested binary (ffmpeg, ffprobe, yt-dlp) ricevono ognuno
    un identifier auto-generato del tipo `<nome>-<hash>`, diverso da
    quello del bundle principale -> TCC NEGA al subprocess.

    Soluzione: firmiamo PRIMA ogni binario interno con `--identifier
    com.djluza.musictools`, poi il bundle .app intero. Cosi' TCC vede
    tutti i Mach-O come parte dello stesso "team" e propaga il permesso
    del main ai subprocess.
    """
    log("Ad-hoc codesign del bundle (identifier coerente per TCC)...")
    try:
        # 1) Pulisci attributi estesi (rimuove quarantine residui dal build)
        subprocess.run(["xattr", "-cr", str(app_path)], capture_output=True)

        # 2) Trova tutti i Mach-O nested (binari ed eventuali .dylib).
        #    Li firmiamo uno a uno con identifier coerente, dal piu' profondo
        #    al piu' esterno (richiesta da codesign).
        nested_machos = []
        for p in sorted(app_path.rglob("*"), key=lambda x: -len(x.parts)):
            if not p.is_file():
                continue
            # Skip risorse non eseguibili
            if p.suffix in (".plist", ".nib", ".png", ".icns", ".svg",
                             ".html", ".css", ".js", ".json", ".md", ".txt"):
                continue
            try:
                with open(p, "rb") as f:
                    magic = f.read(4)
            except Exception:
                continue
            # Mach-O magic numbers (32/64-bit, big/little endian, fat)
            if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
                         b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                         b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                nested_machos.append(p)

        log(f"Trovati {len(nested_machos)} binari Mach-O da firmare.")

        for p in nested_machos:
            # Per ffmpeg/ffprobe dentro al sub-bundle .app, usa l'identifier
            # del SUB-bundle (TCC li tratta come app separate con Info.plist
            # proprio). Per gli altri binari nested (dylib, framework), usa
            # l'identifier del bundle principale.
            ident = _BUNDLE_ID
            parts = p.relative_to(app_path).parts
            for sub in ("ffmpeg.app", "ffprobe.app"):
                if sub in parts:
                    ident = f"{_BUNDLE_ID}.{sub.replace('.app', '')}"
                    break
            r = subprocess.run(
                ["codesign", "--force", "--sign", "-",
                 "--identifier", ident,
                 "--timestamp=none",
                 str(p)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                log(f"  warn: firma {p.name} fallita: {r.stderr.strip()}")

        # Firma anche i sub-bundle .app come bundle (con il loro Info.plist).
        for sub in ("ffmpeg.app", "ffprobe.app"):
            sub_path = app_path / "Contents" / "Frameworks" / sub
            if not sub_path.exists():
                continue
            sub_ident = f"{_BUNDLE_ID}.{sub.replace('.app', '')}"
            r = subprocess.run(
                ["codesign", "--force", "--sign", "-",
                 "--identifier", sub_ident,
                 "--timestamp=none",
                 str(sub_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                log(f"  warn: firma {sub} fallita: {r.stderr.strip()}")

        # 3) Firma del bundle .app principale (l'identifier corretto viene
        #    letto dall'Info.plist - CFBundleIdentifier che gia' settiamo).
        r = subprocess.run(
            ["codesign", "--force", "--sign", "-",
             "--identifier", _BUNDLE_ID,
             "--timestamp=none",
             str(app_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            log(f"ATTENZIONE: firma bundle fallita: {r.stderr.strip()}")
        else:
            log("Codesign ad-hoc completato.")

        # 4) Verifica finale
        verify = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(app_path)],
            capture_output=True, text=True,
        )
        if verify.returncode == 0:
            log("Verifica firma OK.")
        else:
            log(f"NOTA verifica firma: {verify.stderr.strip()}")
    except FileNotFoundError:
        log("ATTENZIONE: 'codesign' non trovato nel PATH, skip ad-hoc signing")


# =========================================================================
# Main
# =========================================================================
def main():
    print("=" * 50)
    print("  MusicTools — Build macOS")
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
    app = DIST_DIR / "MusicTools.app"
    if app.exists():
        print(f"\n  L'app e in: {app}")
        print(f"  Per testarla: open '{app}'")
        print(f"\n  Per distribuirla, comprimi la cartella:")
        print(f"  zip -r MusicTools.zip dist/MusicTools.app")
    print()


if __name__ == "__main__":
    main()
