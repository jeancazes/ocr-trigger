"""Dessin de l'icône OCR Trigger (viseur HUD cyan) — généré par code, aucune image à fournir."""
from PIL import Image, ImageDraw, ImageFilter

CYAN = (25, 230, 255, 255)
BLUE = (31, 143, 255, 255)
DARK = (6, 12, 20, 255)


def draw_icon(size=256):
    S = 512
    c = S // 2

    def reticle(d, col1, col2, w1=18, w2=12):
        d.ellipse((c - 150, c - 150, c + 150, c + 150), outline=col1, width=w1)
        d.ellipse((c - 78, c - 78, c + 78, c + 78), outline=col2, width=w2)
        for box in ((c - 9, 58, c + 9, c - 96), (c - 9, c + 96, c + 9, S - 58),
                    (58, c - 9, c - 96, c + 9), (c + 96, c - 9, S - 58, c + 9)):
            x1, y1, x2, y2 = box
            d.rectangle((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)), fill=col1)
        d.ellipse((c - 17, c - 17, c + 17, c + 17), fill=col1)

    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=96, fill=DARK, outline=CYAN, width=10)

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    reticle(ImageDraw.Draw(glow), CYAN, BLUE)
    glow = glow.filter(ImageFilter.GaussianBlur(16))
    base = Image.alpha_composite(base, glow)

    top = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    reticle(ImageDraw.Draw(top), CYAN, BLUE)
    base = Image.alpha_composite(base, top)
    return base.resize((size, size), Image.LANCZOS)
