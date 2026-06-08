"""Genera le immagini prodotto per Lemon Squeezy.

Produce:
  - ls_thumbnail.png    1024x1024  (thumbnail prodotto + checkout)
  - ls_cover.png        1920x1080  (cover/hero per la pagina prodotto)
  - ls_og.png           1200x630   (Open Graph per social share)

La nota musicale e' disegnata geometricamente (no glyph Unicode)
per essere indipendente dai font installati sul sistema.
"""

from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent

GREEN_LIGHT = (29, 185, 84)
GREEN_DARK = (19, 122, 55)
BG_TOP = (10, 50, 26)
BG_BOTTOM = (6, 6, 6)
WHITE = (255, 255, 255)
MUTED = (190, 190, 190)

ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
ARIAL_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
ARIAL_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"


def font(size: int, *, black: bool = False, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = ARIAL_BLACK if black else (ARIAL_BOLD if bold else ARIAL_REG)
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def vgradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    """Gradient verticale tra due colori (RGB)."""
    w, h = size
    img = Image.new("RGB", size, top)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def radial_glow(size: tuple[int, int], center: tuple[int, int],
                radius: int, color: tuple, opacity: int = 90) -> Image.Image:
    """Glow radiale soft (RGBA)."""
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = center
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(*color, opacity),
    )
    return glow.filter(ImageFilter.GaussianBlur(radius // 3))


def draw_text_centered(canvas: Image.Image, text: str, center: tuple[int, int],
                       size_px: int, color=WHITE, *, black: bool = True,
                       bold: bool = True) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    f = font(size_px, black=black, bold=bold)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = center[0] - tw // 2 - bbox[0]
    y = center[1] - th // 2 - bbox[1]
    draw.text((x, y), text, font=f, fill=(*color, 255))


def draw_text_left(canvas: Image.Image, text: str, anchor: tuple[int, int],
                   size_px: int, color=WHITE, *, black: bool = True,
                   bold: bool = True) -> None:
    """Disegna testo allineato a sinistra (anchor = baseline-left)."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    f = font(size_px, black=black, bold=bold)
    bbox = draw.textbbox(anchor, text, font=f)
    draw.text(anchor, text, font=f, fill=(*color, 255))


def draw_pill(canvas: Image.Image, center: tuple[int, int], text: str,
              pad_x: int, pad_y: int, font_size: int,
              fill=(255, 255, 255, 30), text_color=WHITE,
              *, bold: bool = True) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    f = font(font_size, bold=bold, black=False)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pill_w = tw + 2 * pad_x
    pill_h = th + 2 * pad_y
    x0 = center[0] - pill_w // 2
    y0 = center[1] - pill_h // 2
    draw.rounded_rectangle(
        [x0, y0, x0 + pill_w, y0 + pill_h],
        radius=pill_h // 2,
        fill=fill,
    )
    tx = center[0] - tw // 2 - bbox[0]
    ty = center[1] - th // 2 - bbox[1]
    draw.text((tx, ty), text, font=f, fill=(*text_color, 255))


def draw_music_note(canvas: Image.Image, center: tuple[int, int],
                    size_px: int, color=WHITE) -> None:
    """Disegna una nota musicale stilizzata (due crome connesse).

    Geometria approssimativa:
      - 2 teste ellittiche (sinistra e destra)
      - 2 aste verticali sottili
      - barra orizzontale curva in alto che le connette
    Tutto scalato in funzione di size_px (larghezza disegno).
    """
    cx, cy = center
    W = size_px
    head_w = int(W * 0.30)        # larghezza testa
    head_h = int(head_w * 0.74)   # altezza testa (ovale schiacciata)
    stem_w = max(int(W * 0.035), 6)
    stem_h = int(W * 0.78)
    spacing = int(W * 0.40)       # distanza tra le 2 aste

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Posizioni delle 2 aste
    left_stem_x = cx - spacing // 2
    right_stem_x = cx + spacing // 2

    top_y = cy - stem_h // 2
    bot_y = cy + stem_h // 2

    # Aste (rettangoli verticali)
    d.rounded_rectangle(
        [left_stem_x - stem_w // 2, top_y, left_stem_x + stem_w // 2, bot_y],
        radius=stem_w // 2, fill=color + (255,),
    )
    d.rounded_rectangle(
        [right_stem_x - stem_w // 2, top_y, right_stem_x + stem_w // 2, bot_y],
        radius=stem_w // 2, fill=color + (255,),
    )

    # Barra orizzontale spessa in alto che unisce le aste (ramo)
    bar_thick = max(int(W * 0.09), 14)
    d.rounded_rectangle(
        [left_stem_x - stem_w // 2 - 4, top_y,
         right_stem_x + stem_w // 2 + 4, top_y + bar_thick],
        radius=bar_thick // 3, fill=color + (255,),
    )
    # Seconda barra subito sotto (la nota doppia ha sempre 2 ramificazioni)
    second_bar_y = top_y + int(bar_thick * 1.6)
    d.rounded_rectangle(
        [left_stem_x - stem_w // 2 - 4, second_bar_y,
         right_stem_x + stem_w // 2 + 4, second_bar_y + int(bar_thick * 0.7)],
        radius=bar_thick // 3, fill=color + (255,),
    )

    # Teste ellittiche: in basso, leggermente a sinistra dell'asta (inclinate)
    def head_at(stem_x: int) -> None:
        # Centro testa: poco sotto al fondo dell'asta, leggermente a sinistra
        hx = stem_x - int(head_w * 0.42)
        hy = bot_y - int(head_h * 0.20)
        # Disegnata su layer rotato per dare l'inclinazione
        tmp = Image.new("RGBA", (head_w + 40, head_h + 40), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        td.ellipse([10, 10, 10 + head_w, 10 + head_h], fill=color + (255,))
        rotated = tmp.rotate(-22, resample=Image.BICUBIC, expand=True)
        rw, rh = rotated.size
        layer.alpha_composite(rotated, (hx - rw // 2 + head_w // 2, hy - rh // 2 + head_h // 2))

    head_at(left_stem_x)
    head_at(right_stem_x)

    # Glow morbido sotto la nota per profondita'
    glow_src = layer.filter(ImageFilter.GaussianBlur(W // 22))
    # Riduco un po' l'alpha del glow
    alpha = glow_src.split()[3].point(lambda a: int(a * 0.45))
    glow = Image.merge("RGBA", (*glow_src.split()[:3], alpha))
    canvas.alpha_composite(glow)
    canvas.alpha_composite(layer)


# ============================================================
# Thumbnail 1024x1024
# ============================================================
def make_thumbnail(path: Path) -> None:
    W = H = 1024
    img = vgradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    img.alpha_composite(radial_glow((W, H), (W // 2, H // 2 - 80), 430, GREEN_LIGHT, 100))

    # Eyebrow in cima (testo semplice, no pill)
    draw_text_centered(img, "DESKTOP APP - MAC e WINDOWS", (W // 2, 165),
                       size_px=30, color=GREEN_LIGHT, black=False, bold=True)

    # Nota geometrica centrale
    draw_music_note(img, (W // 2, H // 2 - 40), 360, color=WHITE)

    # Titolo grande
    draw_text_centered(img, "MusicTools", (W // 2, H - 280),
                       size_px=110, color=WHITE, black=True)

    # Tagline
    draw_text_centered(img, "Scarica - Modifica - Registra", (W // 2, H - 195),
                       size_px=38, color=MUTED, black=False, bold=True)

    # Pill prezzo in basso
    draw_pill(img, (W // 2, H - 100), "Licenza a vita 39,90 EUR",
              pad_x=26, pad_y=14, font_size=30,
              fill=GREEN_LIGHT + (255,), text_color=(10, 10, 10), bold=True)

    img.convert("RGB").save(path, "PNG", optimize=True)
    print(f"[ok] thumbnail -> {path}")


# ============================================================
# Cover/Hero 1920x1080
# ============================================================
def make_cover(path: Path) -> None:
    W, H = 1920, 1080
    img = vgradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    # Glow grosso a sinistra (zona del testo)
    img.alpha_composite(radial_glow((W, H), (W // 3, H // 2), 640, GREEN_LIGHT, 85))
    # Glow secondario a destra (zona nota)
    img.alpha_composite(radial_glow((W, H), (int(W * 0.78), H // 2), 380, GREEN_LIGHT, 55))

    LEFT_X = 140
    # Eyebrow testo semplice
    draw_text_left(img, "DESKTOP APP", (LEFT_X, 220),
                   size_px=30, color=GREEN_LIGHT, black=False, bold=True)

    # Heading 2 righe (sinistra)
    draw_text_left(img, "La tua musica.", (LEFT_X, 310),
                   size_px=120, color=WHITE, black=True)
    draw_text_left(img, "In un'unica app.", (LEFT_X, 460),
                   size_px=120, color=GREEN_LIGHT, black=True)

    # Sub-tagline
    draw_text_left(img, "Scarica da Spotify e YouTube.", (LEFT_X, 640),
                   size_px=42, color=MUTED, black=False, bold=True)
    draw_text_left(img, "Registra audio. Modifica metadati.", (LEFT_X, 700),
                   size_px=42, color=MUTED, black=False, bold=True)

    # Pill prezzo (sinistra, basso)
    draw_pill(img, (LEFT_X + 320, H - 160), "Licenza a vita - 39,90 EUR",
              pad_x=30, pad_y=18, font_size=40,
              fill=GREEN_LIGHT + (255,), text_color=(10, 10, 10), bold=True)

    # Nota grande a destra
    draw_music_note(img, (int(W * 0.78), H // 2 - 20), 540, color=WHITE)

    img.convert("RGB").save(path, "PNG", optimize=True)
    print(f"[ok] cover -> {path}")


# ============================================================
# OG image 1200x630
# ============================================================
def make_og(path: Path) -> None:
    W, H = 1200, 630
    img = vgradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    img.alpha_composite(radial_glow((W, H), (W // 2, H // 2 - 50), 420, GREEN_LIGHT, 95))

    # Nota in alto centro
    draw_music_note(img, (W // 2, 180), 180, color=WHITE)

    # Titolo
    draw_text_centered(img, "MusicTools", (W // 2, 360),
                       size_px=92, color=WHITE, black=True)
    # Tagline
    draw_text_centered(img, "Scarica - Modifica - Registra", (W // 2, 440),
                       size_px=32, color=MUTED, black=False, bold=True)

    # Pill prezzo in basso
    draw_pill(img, (W // 2, H - 80), "Licenza a vita 39,90 EUR - Mac e Windows",
              pad_x=24, pad_y=13, font_size=28,
              fill=GREEN_LIGHT + (255,), text_color=(10, 10, 10), bold=True)

    img.convert("RGB").save(path, "PNG", optimize=True)
    print(f"[ok] og -> {path}")


def main() -> None:
    make_thumbnail(OUT_DIR / "ls_thumbnail.png")
    make_cover(OUT_DIR / "ls_cover.png")
    make_og(OUT_DIR / "ls_og.png")


if __name__ == "__main__":
    main()
