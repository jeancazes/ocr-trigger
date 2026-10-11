"""Guide pas à pas : pastilles numérotées + infobulle HUD en surimpression (fond assombri, cible éclairée)."""
import math
import time
import tkinter as tk

from PIL import Image, ImageGrab, ImageTk

from hud import BG, PANEL, LINE, CYAN, BLUE, TEXT, MUTED, blend, HudButton
from i18n import t, guide_steps

CARD_W = 360


class Guide:
    def __init__(self, app, page, font):
        self.app, self.page, self.font = app, page, font
        self.steps = guide_steps(page)
        self.i, self.alive = 0, False
        self.wins, self.job, self.photo = [], None, None
        if not self.steps:
            return
        self.alive = True
        self.cv = tk.Canvas(app.root, highlightthickness=0, bd=0, bg=BG)
        for k, fn in (("<Right>", self.next), ("<Return>", self.next), ("<Left>", self.prev),
                      ("<Escape>", lambda e=None: self.finish(False))):
            self.cv.bind(k, lambda e, fn=fn: fn())
        self.goto(0)

    # ------------------------------------------------------------ navigation
    def goto(self, i):
        if not self.alive:
            return
        self.i = max(0, min(len(self.steps) - 1, i))
        self.cv.place_forget()  # on retire le voile pour photographier la page nette
        w = self.target(self.i)
        if w is not None:
            self.reveal(w)
        self.app.root.update_idletasks()
        self.cv.after(90, self.draw)

    def next(self):
        if self.i >= len(self.steps) - 1:
            self.finish(False)
        else:
            self.goto(self.i + 1)

    def prev(self):
        if self.i > 0:
            self.goto(self.i - 1)

    def finish(self, never):
        if not self.alive:
            return
        self.alive = False
        try:
            if self.job:
                self.cv.after_cancel(self.job)
            self.cv.destroy()
        except tk.TclError:
            pass
        self.app.guide_done(self.page, never)

    # ------------------------------------------------------------ géométrie
    def target(self, i):
        w = self.app.gt.get(self.steps[i]["key"])
        try:
            return w if w is not None and w.winfo_exists() else None
        except tk.TclError:
            return None

    @staticmethod
    def reveal(w):
        """Fait défiler le conteneur scrollable pour que la cible soit visible."""
        p = w
        while p is not None and not hasattr(p, "_parent_canvas"):
            p = getattr(p, "master", None)
        if p is None:
            return
        try:
            cvs = p._parent_canvas
            y = w.winfo_rooty() - p.winfo_rooty()
            top, vis = cvs.canvasy(0), cvs.winfo_height()
            if y < top + 8 or y + w.winfo_height() > top + vis - 8:
                cvs.yview_moveto(max(0.0, (y - 30) / max(1, p.winfo_height())))
                cvs.update_idletasks()
        except tk.TclError:
            pass

    def rect(self, i):
        w = self.target(i)
        r = self.app.root
        try:
            if w is None or not w.winfo_viewable():
                return None
            x, y = w.winfo_rootx() - r.winfo_rootx(), w.winfo_rooty() - r.winfo_rooty()
            ww, hh = w.winfo_width(), w.winfo_height()
        except tk.TclError:
            return None
        if ww < 10 or hh < 10:
            return None
        W, H = r.winfo_width(), r.winfo_height()
        vx0, vy0, vx1, vy1 = 0, 0, W, H
        p = w
        while p is not None and not hasattr(p, "_parent_canvas"):  # zone visible du conteneur scrollable
            p = getattr(p, "master", None)
        if p is not None:
            c = p._parent_canvas
            vx0, vy0 = c.winfo_rootx() - r.winfo_rootx(), c.winfo_rooty() - r.winfo_rooty()
            vx1, vy1 = vx0 + c.winfo_width(), vy0 + c.winfo_height()
        x0, y0 = max(vx0, x - 5), max(vy0, y - 5)
        x1, y1 = min(vx1, x + ww + 5), min(vy1, y + hh + 5)
        return (x0, y0, x1, y1) if x1 - x0 > 10 and y1 - y0 > 10 else None

    # ------------------------------------------------------------ dessin
    def draw(self):
        if not self.alive:
            return
        r, cv = self.app.root, self.cv
        try:
            r.update_idletasks()
            W, H = r.winfo_width(), r.winfo_height()
            rx, ry = r.winfo_rootx(), r.winfo_rooty()
            shot = ImageGrab.grab(bbox=(rx, ry, rx + W, ry + H)).convert("RGB")
        except Exception:
            return self.finish(False)  # capture impossible : on abandonne sans bruit
        rects = [self.rect(k) for k in range(len(self.steps))]
        dim = Image.blend(shot, Image.new("RGB", shot.size, (2, 5, 10)), 0.70)
        for rc in rects:
            if rc:
                dim.paste(shot.crop(rc), rc[:2])
        self.photo = ImageTk.PhotoImage(dim)
        for wdg in self.wins:
            wdg.destroy()
        self.wins = []
        cv.delete("all")
        cv.place(x=0, y=0, width=W, height=H)
        tk.Misc.tkraise(cv)
        cv.create_image(0, 0, image=self.photo, anchor="nw")
        cur = rects[self.i]
        self.frame_ids = []
        if cur:
            x0, y0, x1, y1 = cur
            self.frame_ids.append(cv.create_rectangle(x0, y0, x1, y1, outline=CYAN, width=2))
            for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
                self.frame_ids.append(cv.create_line(cx, cy + 14 * dy, cx, cy, cx + 14 * dx, cy, fill="#ffffff",
                                                     width=2))
        # pastilles numérotées (toutes les cibles visibles, l'étape courante est pleine)
        self.ring = None
        for k, rc in enumerate(rects):
            if not rc:
                continue
            px, py = max(14, rc[0]), max(14, rc[1])
            tag = f"p{k}"
            on = k == self.i
            if on:
                self.ring = cv.create_oval(px - 12, py - 12, px + 12, py + 12, outline=CYAN, width=2)
            cv.create_oval(px - 12, py - 12, px + 12, py + 12, fill=CYAN if on else BG, outline=CYAN, width=2,
                           tags=tag)
            cv.create_text(px, py, text=str(k + 1), fill=BG if on else CYAN, font=self.font(11, True), tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda e, k=k: self.goto(k))
            cv.tag_bind(tag, "<Enter>", lambda e: cv.configure(cursor="hand2"))
            cv.tag_bind(tag, "<Leave>", lambda e: cv.configure(cursor="arrow"))
        self.card(cur, W, H)
        cv.focus_set()
        self.pulse()

    def card(self, cur, W, H):
        cv, s = self.cv, self.steps[self.i]
        n = len(self.steps)
        poly = cv.create_polygon(0, 0, 1, 1, 2, 2, fill=PANEL, outline=LINE)
        ttl = cv.create_text(0, 0, text=f"{self.i + 1}/{n}  ·  {s['title']}", anchor="nw", fill=CYAN,
                             font=self.font(13, True), width=CARD_W - 90)
        body = cv.create_text(0, 0, text=s["body"], anchor="nw", fill=TEXT, font=self.font(11),
                              width=CARD_W - 36)
        tb, bb = cv.bbox(ttl), cv.bbox(body)
        th, bh = tb[3] - tb[1], bb[3] - bb[1]
        Hc = 16 + th + 8 + bh + 14 + 32 + 8 + 28 + 14
        cx, cy = self.place(cur, W, H, Hc)
        cv.coords(ttl, cx + 18, cy + 16)
        cv.coords(body, cx + 18, cy + 16 + th + 8)
        c = 14
        pts = [cx + c, cy, cx + CARD_W - 60, cy, cx + CARD_W - 52, cy + 7, cx + CARD_W - 24, cy + 7,
               cx + CARD_W - 16, cy, cx + CARD_W, cy, cx + CARD_W, cy + Hc - c, cx + CARD_W - c, cy + Hc,
               cx, cy + Hc, cx, cy + c]
        cv.coords(poly, *pts)
        cv.tag_raise(poly, "all")
        cv.tag_raise(ttl)
        cv.tag_raise(body)
        acc = [cv.create_line(cx, cy + c, cx + c, cy, cx + 70, cy, fill=CYAN, width=2),
               cv.create_line(cx + CARD_W, cy + Hc - c, cx + CARD_W - c, cy + Hc, cx + CARD_W - 60, cy + Hc,
                              fill=CYAN, width=2)]
        by = cy + 16 + th + 8 + bh + 14
        last = self.i == n - 1

        def put(txt, cmd, kind, w, h, x, y, anchor="nw"):
            b = HudButton(cv, txt, cmd, kind, w, h, self.font(11 if kind == "tiny" else 12, True))
            cv.create_window(x, y, window=b, anchor=anchor)
            self.wins.append(b)
            return b

        p = put(t("g_prev"), self.prev, "ghost", 120, 32, cx + 18, by)
        if self.i == 0:
            p.configure(state="disabled")
        put(t("g_done") if last else t("g_next"), self.next, "primary", 130, 32, cx + CARD_W - 18, by, "ne")
        put(t("g_never"), lambda: self.finish(True), "tiny", 150, 28, cx + 18, by + 40)
        put(t("g_skip"), lambda: self.finish(False), "tiny", 90, 28, cx + CARD_W - 18, by + 40, "ne")

    def place(self, cur, W, H, Hc):
        if not cur:
            return (W - CARD_W) // 2, (H - Hc) // 2
        x0, y0, x1, y1 = cur
        clampx = lambda x: max(10, min(W - CARD_W - 10, x))
        clampy = lambda y: max(10, min(H - Hc - 10, y))
        for x, y, ok in ((clampx(x0), y1 + 16, y1 + 16 + Hc <= H - 6),
                         (clampx(x0), y0 - Hc - 16, y0 - Hc - 16 >= 6),
                         (x1 + 16, clampy(y0), x1 + 16 + CARD_W <= W - 6),
                         (x0 - CARD_W - 16, clampy(y0), x0 - CARD_W - 16 >= 6)):
            if ok:
                return int(x), int(y)
        return W - CARD_W - 20, H - Hc - 20

    def pulse(self):
        if not self.alive:
            return
        try:
            k = (time.time() * 0.9) % 1
            if self.ring:
                c = self.cv.coords(self.ring)
                mx, my = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
                r = 12 + 10 * k
                self.cv.coords(self.ring, mx - r, my - r, mx + r, my + r)
                self.cv.itemconfigure(self.ring, outline=blend(CYAN, BG, k ** 0.7))
            glow = 0.5 + 0.5 * math.sin(time.time() * 4)
            if self.frame_ids:
                self.cv.itemconfigure(self.frame_ids[0], outline=blend(BLUE, CYAN, glow))
            self.job = self.cv.after(40, self.pulse)
        except tk.TclError:
            pass
