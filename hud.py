"""Widgets HUD (style RSI / Star Citizen) : cadres à coins coupés et encoches, boutons flat animés."""
import math
import time
import tkinter as tk

BG, PANEL, PANEL2, SEL = "#04070c", "#0a111b", "#0f1a29", "#0c2638"
LINE, CYAN, BLUE = "#16324a", "#19e6ff", "#1f8fff"
TEXT, MUTED = "#d6ecff", "#6f8aa3"
OK, WARN, BAD = "#2dffb0", "#ffb020", "#ff4d5e"


SOUND = {"fn": None, "last": 0.0}


def play(kind):
    fn = SOUND["fn"]
    now = time.time()
    if fn and now - SOUND["last"] > 0.07:
        SOUND["last"] = now
        fn(kind)


def _rgb(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


def blend(c1, c2, t):
    a, b = _rgb(c1), _rgb(c2)
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def bg_of(w):
    """Couleur de fond réelle d'un widget (tk ou customtkinter), pour y poser un canvas."""
    while w is not None:
        try:
            c = w.cget("fg_color")
            if isinstance(c, (tuple, list)):
                c = c[-1]
            if c and c != "transparent":
                return c
        except Exception:
            try:
                return w.cget("bg")
            except Exception:
                pass
        w = getattr(w, "master", None)
    return BG


def ease(t):
    return 1 - (1 - t) ** 3


# ------------------------------------------------------------------ cadre
class HudPanel(tk.Frame):
    """Cadre à coins coupés (haut-gauche / bas-droite), encoches et accents cyan."""

    def __init__(self, parent, width=None, **kw):
        outer = bg_of(parent)
        opts = {"bg": PANEL}
        if width:
            opts["width"] = width
        super().__init__(parent, highlightthickness=0, bd=0, **opts)
        self.outer = outer
        self.cv = tk.Canvas(self, bg=outer, highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.lower(self.cv)
        self.bind("<Configure>", self._draw)

    def _draw(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 60:
            return
        c, cv = 14, self.cv
        cv.delete("all")
        path = [(c, 1), (w - 70, 1), (w - 62, 8), (w - 34, 8), (w - 26, 1), (w - 2, 1), (w - 2, h - c),
                (w - c, h - 2), (70, h - 2), (62, h - 9), (34, h - 9), (26, h - 2), (1, h - 2), (1, c)]
        flat = [v for p in path for v in p]
        cv.create_polygon(flat, fill=PANEL, outline=LINE)
        # accents lumineux : angle haut-gauche, angle bas-droite, repère latéral
        cv.create_line(1, c, c, 1, 70 if w > 200 else c + 20, 1, fill=CYAN, width=2)
        cv.create_line(w - 2, h - c, w - c, h - 2, w - 52, h - 2, fill=CYAN, width=2)
        cv.create_line(w - 2, 22, w - 2, 44, fill=BLUE, width=3)
        cv.create_line(1, h - 46, 1, h - 24, fill=BLUE, width=3)
        for i in range(3):  # petits crans décoratifs
            x = c + 80 + i * 6
            cv.create_line(x, 1, x - 3, 5, fill=BLUE)


# ------------------------------------------------------------------ bouton
KINDS = {
    "primary": ("#0b3a52", "#0f5a80", CYAN, CYAN),
    "ghost": (PANEL2, SEL, TEXT, BLUE),
    "danger": ("#1a0d14", "#3a1220", BAD, BAD),
    "tiny": (PANEL2, SEL, MUTED, BLUE),
    "nav": (PANEL, SEL, TEXT, CYAN),
    "item": (PANEL2, SEL, TEXT, CYAN),
}


class HudButton(tk.Canvas):
    """Bouton flat à un coin coupé : fondu au survol, bordure qui se dessine, balayage lumineux, appui."""

    def __init__(self, parent, text, command, kind="ghost", width=120, height=32, font=None, font2=None):
        self.parent_bg = bg_of(parent)
        super().__init__(parent, width=width, height=height, bg=self.parent_bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.W, self.H = width, height
        self.text, self.command, self.kind = text, command, kind
        self.font, self.font2 = font, font2 or font
        self.fill, self.hover, self.fg, self.accent = KINDS[kind]
        self.enabled, self.selected, self.pressed = True, False, False
        self.hv = self.target = 0.0
        self.sw = 1.0
        self._last = 0.0
        self._job = None
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._conf)
        self.draw()

    # ----- API compatible avec les boutons précédents
    def configure(self, cnf=None, **kw):
        cnf = dict(cnf or {}, **kw)
        for k in ("text", "command"):
            if k in cnf:
                setattr(self, k, cnf.pop(k))
        if "state" in cnf:
            self.enabled = cnf.pop("state") != "disabled"
            super().configure(cursor="hand2" if self.enabled else "arrow")
        if cnf:
            super().configure(cnf)
        self.draw()

    config = configure

    def cget(self, key):
        if key == "text":
            return self.text
        if key == "state":
            return "normal" if self.enabled else "disabled"
        return super().cget(key)

    def set_selected(self, v):
        if v != self.selected:
            self.selected = v
            self.draw()

    # ----- géométrie
    def _poly(self):
        w, h = self.W, self.H
        if self.kind == "nav":
            return [(0, 0), (w, 0), (w, h), (0, h)]
        c = 7 if h <= 30 else 9
        return [(0, 0), (w, 0), (w, h - c), (w - c, h), (0, h)]

    def _conf(self, e):
        if (e.width, e.height) != (self.W, self.H) and e.width > 4:
            self.W, self.H = e.width, e.height
            self.draw()

    @staticmethod
    def _walk(pts, dist):
        """Points du début du contour sur une longueur `dist`."""
        out, left = [pts[0]], dist
        for a, b in zip(pts, pts[1:]):
            seg = math.dist(a, b)
            if left >= seg:
                out.append(b)
                left -= seg
            else:
                f = left / seg if seg else 0
                out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
                break
        return out

    # ----- dessin
    def draw(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.delete("all")
        w, h = self.W, self.H
        poly = self._poly()
        hv = ease(self.hv)
        base = self.hover if self.selected else self.fill
        f = blend(base, self.hover, hv)
        if self.pressed:
            f = blend(f, "#ffffff", 0.22)
        self.create_polygon([v for p in poly for v in p], fill=f, outline="")
        # balayage lumineux
        if 0 <= self.sw < 1:
            bw, sk = max(26, w // 5), 14
            x0 = -bw - sk + (w + bw + sk * 2) * ease(self.sw)
            band = [(x0 + sk, 0), (x0 + sk + bw, 0), (x0 + bw, h), (x0, h)]
            band = [(min(max(x, 0), w), y) for x, y in band]
            self.create_polygon([v for p in band for v in p], fill=blend(f, self.accent, 0.28), outline="")
        if self.kind != "nav" and len(poly) == 5:  # recouvre le coin coupé
            c = h - poly[2][1]
            self.create_polygon(w - c, h, w, h - c, w, h, fill=self.parent_bg, outline="")
        # bordure qui se dessine depuis le coin haut-gauche (dans les deux sens)
        if hv > 0.01 and self.enabled:
            ring = poly + [poly[0]]
            total = sum(math.dist(a, b) for a, b in zip(ring, ring[1:]))
            col = blend(f, self.accent, 0.9)
            for pts in (ring, ring[::-1]):
                seg = self._walk(pts, total / 2 * hv)
                if len(seg) > 1:
                    self.create_line([v for p in seg for v in p], fill=col, width=1)
        # barre latérale (nav)
        if self.kind == "nav":
            bw = 4 * max(hv * 0.6, 1.0 if self.selected else 0.0)
            if bw > 0.2:
                self.create_rectangle(0, 5, bw, h - 5, fill=CYAN, outline="")
        elif self.selected and self.kind == "item":
            self.create_rectangle(0, 5, 3, h - 5, fill=CYAN, outline="")
        # texte
        color = self.fg if self.enabled else MUTED
        if self.kind == "nav" and self.selected:
            color = CYAN
        dy = 1 if self.pressed else 0
        lines = str(self.text).split("\n")
        if self.kind in ("nav", "item"):
            x = 16 if self.kind == "nav" else 14
            if len(lines) == 2:
                self.create_text(x, h * 0.34 + dy, text=lines[0], anchor="w", fill=color, font=self.font)
                self.create_text(x, h * 0.72 + dy, text=lines[1], anchor="w", fill=MUTED, font=self.font2)
            else:
                self.create_text(x, h / 2 + dy, text=self.text, anchor="w", fill=color, font=self.font)
        else:
            self.create_text(w / 2 - 2, h / 2 + dy, text=self.text, fill=color, font=self.font)

    # ----- animation (une boucle `after` qui s'arrête dès que tout est stable)
    def _run(self):
        if self._job is None:
            self._last = time.time()
            self._job = self.after(16, self._tick)

    def _tick(self):
        self._job = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        now = time.time()
        dt, self._last = min(0.06, now - self._last), now
        step = dt / 0.16
        if self.hv < self.target:
            self.hv = min(self.target, self.hv + step)
        elif self.hv > self.target:
            self.hv = max(self.target, self.hv - step)
        if self.sw < 1:
            self.sw = min(1.0, self.sw + dt / 0.55)
        self.draw()
        if self.hv != self.target or self.sw < 1:
            self._job = self.after(16, self._tick)

    def _enter(self, e):
        if not self.enabled:
            return
        self.target = 1.0
        play("hover")
        if self.sw >= 1:
            self.sw = 0.0
        self._run()

    def _leave(self, e):
        self.target, self.pressed = 0.0, False
        self._run()

    def _press(self, e):
        if self.enabled:
            self.pressed = True
            self.draw()

    def _release(self, e):
        was = self.pressed
        self.pressed = False
        self.draw()
        if was and self.enabled and 0 <= e.x <= self.W and 0 <= e.y <= self.H and self.command:
            play("click")
            self.command()
