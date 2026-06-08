"""Genera l'icona dell'app (PNG/ICNS/ICO) in modo riproducibile.

Stile: squircle (Apple-style rounded rect) con gradient verde Spotify
verso nero, nota musicale bianca al centro con leggero glow, highlight
sottile in alto.

Uso:
    python3 assets/generate_icon.py

Produce:
    assets/icon.png          (1024x1024, master)
    assets/icon.icns         (macOS, generato via iconutil)
    assets/icon.ico          (Windows, multi-size)
    assets/icon.iconset/...  (intermedio macOS)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SIZE = 1024
RADIUS_RATIO = 0.225          # ~22% del lato, Apple iOS-like squircle
PADDING_RATIO = 0.085         # margine fra bordo immagine e squircle

# Palette (coerente col tema della UI)
GREEN_TOP = (30, 215, 96)     # verde Spotify lucido
GREEN_BOTTOM = (15, 59, 34)   # verde scuro profondo
WHITE = (255, 255, 255, 255)
HIGHLIGHT = (255, 255, 255, 38)  # bianco semitrasparente per il riflesso


def vertical_gradient(size: int, top: Tuple[int, int, int],
                       bottom: Tuple[int, int, int]) -> Image.Image:
    """Crea un gradient verticale top -> bottom."""
    img = Image.new("RGB", (size, size), top)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        # ease (quad) per ammorbidire la transizione
        t = t * t
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def squircle_mask(size: int, radius: int, padding: int) -> Image.Image:
    """Maschera alpha per un rounded rect centrato con padding."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (padding, padding, size - padding, size - padding),
        radius=radius, fill=255,
    )
    return mask


def find_music_font() -> str:
    """Trova un font che contenga il glifo della nota musicale (♫)."""
    candidates = [
        "/System/Library/Fonts/Apple Symbols.ttf",
        "/System/Library/Fonts/Symbol.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for f in candidates:
        if Path(f).exists():
            return f
    raise RuntimeError("Nessun font Unicode con simboli trovato")


def draw_note(img: Image.Image, glyph: str = "♫") -> None:
    """Stampa la nota musicale centrata, in bianco con leggero glow."""
    font_path = find_music_font()
    target_pt = int(SIZE * 0.62)
    font = ImageFont.truetype(font_path, target_pt)

    cx, cy = SIZE // 2, SIZE // 2 - int(SIZE * 0.01)

    # Glow: stessa nota disegnata sfocata sotto in bianco semitrasparente
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.text((cx, cy), glyph, font=font, fill=(255, 255, 255, 110),
                   anchor="mm")
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=24))
    img.alpha_composite(glow_layer)

    # Testo nitido sopra
    draw = ImageDraw.Draw(img)
    draw.text((cx, cy), glyph, font=font, fill=WHITE, anchor="mm")


def make_master() -> Image.Image:
    """Genera l'immagine master 1024x1024 RGBA con tutto."""
    padding = int(SIZE * PADDING_RATIO)
    radius = int(SIZE * RADIUS_RATIO)

    # Background gradient verde
    gradient = vertical_gradient(SIZE, GREEN_TOP, GREEN_BOTTOM)

    # Squircle: prendiamo il gradient mascherato come forma
    mask = squircle_mask(SIZE, radius, padding)
    base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    base.paste(gradient, (0, 0), mask)

    # Highlight in alto: banda sottile (tipo "shine" iOS), molto trasparente
    hl_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(hl_layer)
    hl_top = padding + int(SIZE * 0.04)
    hl_bot = padding + int(SIZE * 0.16)
    hl_left = padding + int(SIZE * 0.10)
    hl_right = SIZE - padding - int(SIZE * 0.10)
    hl_draw.ellipse(
        (hl_left, hl_top, hl_right, hl_bot),
        fill=(255, 255, 255, 30),
    )
    hl_layer = hl_layer.filter(ImageFilter.GaussianBlur(radius=18))
    masked = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    masked.paste(hl_layer, (0, 0), mask)
    base.alpha_composite(masked)

    # Bordo interno sottile per dare definizione (stroke da 0.5%)
    ring = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.rounded_rectangle(
        (padding, padding, SIZE - padding, SIZE - padding),
        radius=radius,
        outline=(255, 255, 255, 28),
        width=max(2, int(SIZE * 0.004)),
    )
    base.alpha_composite(ring)

    # Nota musicale al centro
    draw_note(base)

    # Lieve ombra interna in basso per profondita (vignette)
    shade = Image.new("L", (SIZE, SIZE), 0)
    sd = ImageDraw.Draw(shade)
    sd.rounded_rectangle(
        (padding, padding, SIZE - padding, SIZE - padding),
        radius=radius, outline=255, width=int(SIZE * 0.025),
    )
    shade = shade.filter(ImageFilter.GaussianBlur(radius=int(SIZE * 0.025)))
    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    overlay.paste((0, 0, 0, 60), mask=shade)
    overlay = Image.new("RGBA", overlay.size, (0, 0, 0, 0)).convert("RGBA")
    # Skip vignette complicata — base e' gia' coerente

    return base


def export_iconset(master: Image.Image, outdir: Path) -> None:
    """Esporta le dimensioni standard macOS in outdir."""
    outdir.mkdir(parents=True, exist_ok=True)
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for px, name in sizes:
        img = master.resize((px, px), Image.LANCZOS)
        img.save(outdir / name, "PNG")


def build_icns(iconset_dir: Path, output_icns: Path) -> bool:
    """Usa iconutil di macOS per generare il .icns. Ritorna True se ok."""
    if not shutil.which("iconutil"):
        return False
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_icns)],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def build_ico(master: Image.Image, output_ico: Path) -> None:
    """Genera il .ico multi-size per Windows."""
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256)]
    master.save(output_ico, format="ICO",
                sizes=sizes, append_images=[])


def main():
    print(f">>> Genero icona master {SIZE}x{SIZE}...")
    master = make_master()
    master_path = HERE / "icon.png"
    master.save(master_path, "PNG")
    print(f"    {master_path}")

    iconset_dir = HERE / "icon.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    print(">>> Esporto iconset macOS...")
    export_iconset(master, iconset_dir)

    icns_path = HERE / "icon.icns"
    if build_icns(iconset_dir, icns_path):
        print(f"    {icns_path}")
    else:
        print("    SKIP icns (iconutil non disponibile)")

    print(">>> Genero icon.ico per Windows...")
    ico_path = HERE / "icon.ico"
    build_ico(master, ico_path)
    print(f"    {ico_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
