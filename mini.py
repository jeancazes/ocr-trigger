"""Mini-widget HUD par-dessus le jeu : miniature de la zone OCR, voyants, texte lu, dernière action."""
import time
import tkinter as tk

from PIL import Image, ImageTk

from hud import BG, LINE, CYAN, BLUE, TEXT, MUTED, OK, WARN
from engine import text_matches
from i18n import t

TW, TH = 120, 64  # taille max de la miniature


def light_cols(eng, i, now):
    """Couleurs des 4 voyants (partagées par le mini-widget et l'aperçu)."""
    r = eng.cfg["rules"][i] if i is not None and 0 <= i < len(eng.cfg["rules"]) else None
    txt = eng.last_text.get(i, "") if r else ""
    hit = bool(r) and bool(txt) and text_matches(r["text"], txt)
    ht = max(eng.last.get(i, 0), 0) if r else 0
    return hit, {"ocr": OK if eng.ocr_on else MUTED, "txt": CYAN if hit else MUTED,
                 "act": WARN if now - max(ht, 0) < 1.5 or now - eng.hit_time < 1.5 else MUTED,
                 "ser": BLUE if eng.series_on else MUTED}


class Band(tk.Frame):
    """Bandeau d'infos : voyants + texte OCR lu + dernières actions (heure : OCR --> touche)."""

    def __init__(self, parent, font, mono, size=10, nlog=5):
        super().__init__(parent, bg=BG)
        self.nlog = nlog
        self.cv = tk.Canvas(self, height=24, width=420, bg=BG, highlightthickness=0, bd=0)
        self.cv.pack(anchor="w", padx=4, pady=(4, 0))
        self.dots = {}
        for n, (k, key) in enumerate((("ocr", "mini_l_ocr"), ("txt", "mini_l_txt"),
                                      ("act", "mini_l_act"), ("ser", "mini_l_ser"))):
            x = 6 + n * 100
            self.dots[k] = self.cv.create_oval(x, 6, x + 13, 19, fill=MUTED, outline=LINE)
            self.cv.create_text(x + 20, 13, text=t(key), anchor="w", fill=MUTED, font=(font, size - 1, "bold"))
        self.txt = tk.Label(self, bg=BG, fg=TEXT, font=(mono, size), anchor="w", justify="left", wraplength=560)
        self.txt.pack(fill="x", padx=6)
        self.logs = tk.Label(self, bg=BG, fg=MUTED, font=(mono, size - 1), anchor="w", justify="left")
        self.logs.pack(fill="x", padx=6, pady=(0, 4))

    def update_state(self, eng, i):
        now = time.time()
        hit, cols = light_cols(eng, i, now)
        for k, c in cols.items():
            self.cv.itemconfigure(self.dots[k], fill=c)
        txt = (eng.last_text.get(i, "") if i is not None else "").strip().replace("\n", " ")
        self.txt.configure(text=t("prev_ocr", txt=txt) if txt else t("prev_hint"), fg=CYAN if hit else TEXT)
        lines = eng.hit_log[-self.nlog:][::-1]
        self.logs.configure(text="\n".join(lines) if lines else "—",
                            fg=WARN if now - eng.hit_time < 1.5 else MUTED)


class Mini:
    def __init__(self, app, font, mono):
        self.app, self.font, self.mono = app, font, mono
        self.win = None
        self.job = None
        self.shot_id = None
        self.photo = None
        self.drag = (0, 0)

    # ----- cycle de vie
    def build(self):
        root = self.app.root
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.92)
        w.configure(bg=BG, highlightbackground=CYAN, highlightthickness=1)
        pos = self.app.eng.cfg.get("mini_pos") or [16, 64]
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        x, y = max(0, min(int(pos[0]), sw - 60)), max(0, min(int(pos[1]), sh - 40))
        w.geometry(f"+{x}+{y}")
        top = tk.Frame(w, bg=BG)
        top.pack(fill="x", padx=5, pady=(5, 2))
        self.thumb = tk.Label(top, bg="#000000", width=TW, height=TH, bd=0, highlightbackground=LINE,
                              highlightthickness=1, image=self._blank(), compound="center")
        self.thumb.pack(side="left", anchor="n")
        self.lights = tk.Canvas(top, width=64, height=TH, bg=BG, highlightthickness=0, bd=0)
        self.lights.pack(side="left", padx=(6, 0))
        self.dots = {}
        for n, (k, key) in enumerate((("ocr", "mini_l_ocr"), ("txt", "mini_l_txt"),
                                      ("act", "mini_l_act"), ("ser", "mini_l_ser"))):
            y0 = 8 + n * 16
            self.dots[k] = self.lights.create_oval(2, y0 - 5, 12, y0 + 5, fill=MUTED, outline=LINE)
            self.lights.create_text(18, y0, text=t(key), anchor="w", fill=MUTED, font=(self.font, 7, "bold"))
        self.seen = tk.Label(w, bg=BG, fg=CYAN, font=(self.mono, 8), anchor="w", width=34)
        self.seen.pack(fill="x", padx=6)
        self.logl = tk.Label(w, bg=BG, fg=MUTED, font=(self.mono, 8), anchor="w", width=34)
        self.logl.pack(fill="x", padx=6, pady=(0, 5))
        for wd in (w, top, self.thumb, self.lights, self.seen, self.logl):
            wd.bind("<ButtonPress-1>", self._press)
            wd.bind("<B1-Motion>", self._move)
            wd.bind("<ButtonRelease-1>", self._release)
        self.win = w

    def _blank(self):
        if not hasattr(self, "_blank_img"):
            self._blank_img = tk.PhotoImage(width=1, height=1)
        return self._blank_img

    def destroy(self):
        if self.job:
            try:
                self.app.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None

    def start(self):
        if self.job is None:
            self.tick()

    # ----- déplacement à la souris
    def _press(self, e):
        self.drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _move(self, e):
        self.win.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def _release(self, e):
        self.app.eng.cfg["mini_pos"] = [self.win.winfo_x(), self.win.winfo_y()]
        self.app.eng.save()

    # ----- mise à jour (4 fois par seconde)
    def tick(self):
        self.job = None
        app = self.app
        if app.quitting:
            return
        eng = app.eng
        want = bool(eng.cfg.get("mini")) and eng.ocr_on
        if want and self.win is None:
            self.build()
        elif not want and self.win is not None:
            self.destroy()
        if self.win is not None:
            try:
                self.refresh()
            except Exception:
                app.crash_log()
        if bool(eng.cfg.get("mini")) or self.win is not None:
            self.job = app.root.after(250, self.tick)

    def refresh(self):
        eng, now = self.app.eng, time.time()
        rules = eng.cfg["rules"]
        i = int(eng.cfg.get("mini_rule", 0) or 0)
        r = rules[i] if 0 <= i < len(rules) else None
        txt = eng.last_text.get(i, "") if r else ""
        hit = bool(r) and bool(txt) and text_matches(r["text"], txt)
        shot = eng.last_shot.get(i) if r else None
        if shot is not None and id(shot) != self.shot_id:
            self.shot_id = id(shot)
            img = Image.fromarray(shot[:, :, ::-1])
            img.thumbnail((TW, TH))
            self.photo = ImageTk.PhotoImage(img)
            self.thumb.configure(image=self.photo, width=img.width, height=img.height)
        elif shot is None and r is None:
            self.thumb.configure(image=self._blank(), text=t("mini_none"), fg=MUTED, width=TW, height=TH)
        cv = self.lights
        col = {"ocr": OK if eng.ocr_on else MUTED, "txt": CYAN if hit else MUTED,
               "act": WARN if now - eng.hit_time < 1.5 else MUTED,
               "ser": BLUE if eng.series_on else MUTED}
        for k, c in col.items():
            cv.itemconfigure(self.dots[k], fill=c)
        shown = txt.strip().replace("\n", " ")
        self.seen.configure(text=f"{t('mini_seen')}: {shown[:26]}" if shown else f"{t('mini_seen')}: {t('mini_wait')}",
                            fg=CYAN if hit else TEXT)
        self.logl.configure(text=eng.hit_line or "—", fg=WARN if now - eng.hit_time < 1.5 else MUTED)
