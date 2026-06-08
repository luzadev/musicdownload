"""Genera i loghi brand MusicTools partendo dall'icona master.

Produce:
  - logo_mark.png                1024x1024   solo squircle + nota, bg trasparente
  - logo_horizontal_dark.png     2400x720    mark + "MusicTools" testo bianco (per bg scuri)
  - logo_horizontal_light.png    2400x720    mark + "MusicTools" testo nero  (per bg chiari)
  - logo_stacked.png             1280x1600   mark sopra + testo sotto, bianco (per bg scuri)

Lo squircle riuso quello generato da generate_icon.py (assets/icon.png),
cosi' resta coerente con l'icona dell'app.
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ICON_PATH = HERE / "icon.png"

ARIAL_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

WHITE = (255, 255, 255)
BLACK = (10, 10, 10)


def font(size: int, *, black: bool = True) -> ImageFont.FreeTypeFont:
    path = ARIAL_BLACK if black else ARIAL_BOLD
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def load_mark(target_size: int) -> Image.Image:
    """Carica l'icona master e la riscala alla dimensione richiesta.

    L'icona originale ha sfondo trasparente fuori dallo squircle
    (vedi generate_icon.py), quindi va bene per overlay su qualunque bg.
    """
    if not ICON_PATH.exists():
        raise FileNotFoundError(
            f"icon.png non trovata: rilancia prima 'python3 assets/generate_icon.py'"
        )
    icon = Image.open(ICON_PATH).convert("RGBA")
    if icon.size != (target_size, target_size):
        icon = icon.resize((target_size, target_size), Image.LANCZOS)
    return icon


def measure_text(text: str, f: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """Ritorna (larghezza, altezza) effettiva del testo."""
    bbox = f.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_text_top_left(canvas: Image.Image, text: str, top_left: tuple[int, int],
                       f: ImageFont.FreeTypeFont, color: tuple) -> None:
    """Disegna testo con angolo top-left = top_left (compensa font bbox)."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    bbox = f.getbbox(text)
    x = top_left[0] - bbox[0]
    y = top_left[1] - bbox[1]
    draw.text((x, y), text, font=f, fill=(*color, 255))


def make_mark(path: Path) -> None:
    mark = load_mark(1024)
    mark.save(path, "PNG", optimize=True)
    print(f"[ok] mark -> {path}")


def make_horizontal(path: Path, text_color: tuple) -> None:
    """Layout: mark a sinistra + testo. Canvas si autodimensiona al testo."""
    H = 720
    mark_size = int(H * 0.92)
    pad_left = 60
    gap = 70
    pad_right = 80

    text = "MusicTools"
    f = font(260, black=True)
    tw, th = measure_text(text, f)

    W = pad_left + mark_size + gap + tw + pad_right

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Mark a sinistra, centrato verticalmente
    mark = load_mark(mark_size)
    mark_y = (H - mark_size) // 2
    canvas.alpha_composite(mark, (pad_left, mark_y))

    # Testo allineato top-left calcolato in modo che la sua baseline
    # sia visivamente centrata sull'altezza dello squircle.
    text_x = pad_left + mark_size + gap
    text_y = (H - th) // 2
    draw_text_top_left(canvas, text, (text_x, text_y), f, text_color)

    canvas.save(path, "PNG", optimize=True)
    name = "dark" if text_color == WHITE else "light"
    print(f"[ok] horizontal ({name}) -> {path}  [{W}x{H}]")


def make_stacked(path: Path, text_color: tuple) -> None:
    """Mark sopra + 'MusicTools' sotto. Canvas autodimensionato al testo."""
    mark_size = 1024
    f = font(180, black=True)
    text = "MusicTools"
    tw, th = measure_text(text, f)

    pad = 80
    gap = 50
    W = max(mark_size, tw) + 2 * pad
    H = pad + mark_size + gap + th + pad

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    mark = load_mark(mark_size)
    mark_x = (W - mark_size) // 2
    canvas.alpha_composite(mark, (mark_x, pad))

    text_x = (W - tw) // 2
    text_y = pad + mark_size + gap
    draw_text_top_left(canvas, text, (text_x, text_y), f, text_color)

    canvas.save(path, "PNG", optimize=True)
    name = "dark" if text_color == WHITE else "light"
    print(f"[ok] stacked ({name}) -> {path}  [{W}x{H}]")


def main() -> None:
    make_mark(HERE / "logo_mark.png")
    make_horizontal(HERE / "logo_horizontal_dark.png", WHITE)   # per sfondi scuri
    make_horizontal(HERE / "logo_horizontal_light.png", BLACK)  # per sfondi chiari
    make_stacked(HERE / "logo_stacked_dark.png", WHITE)         # per sfondi scuri
    make_stacked(HERE / "logo_stacked_light.png", BLACK)        # per sfondi chiari
    # rimuovo eventuale vecchio file senza suffisso
    old = HERE / "logo_stacked.png"
    if old.exists():
        old.unlink()


if __name__ == "__main__":
    main()
