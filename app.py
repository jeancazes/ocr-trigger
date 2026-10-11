"""OCR Trigger 2.0 - lit une zone de l'écran (même en plein écran) et déclenche touches / clics.
Interface HUD (CustomTkinter). Windows uniquement ; l'exe demande les droits administrateur.
"""
import os
import sys

if sys.stdout is None:  # exe --noconsole
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import ctypes
import queue
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk

import winutil
from recorder import Recorder
from engine import Engine, VERSION, NEW_RULE, NEW_SERIES, DEFAULT_SECS, app_dir, clone
from i18n import t, set_lang
from iconart import draw_icon

try:
    import keyboard
except Exception:
    keyboard = None
try:
    import pystray
except Exception:
    pystray = None

ERR_LOG = os.path.join(app_dir(), "error.log")

BG, PANEL, PANEL2, SEL = "#04070c", "#0a111b", "#0f1a29", "#0c2638"
LINE, CYAN, BLUE = "#16324a", "#19e6ff", "#1f8fff"
TEXT, MUTED = "#d6ecff", "#6f8aa3"
OK, WARN, BAD = "#2dffb0", "#ffb020", "#ff4d5e"
FONT, MONO = "Segoe UI", "Consolas"


# ---------------------------------------------------------------- widgets
def font(size=12, bold=False, mono=False):
    return ctk.CTkFont(family=MONO if mono else FONT, size=size, weight="bold" if bold else "normal")


def label(p, text="", color=TEXT, size=12, bold=False, mono=False, **kw):
    return ctk.CTkLabel(p, text=text, text_color=color, font=font(size, bold, mono), **kw)


def entry(p, var=None, width=110, **kw):
    return ctk.CTkEntry(p, textvariable=var, width=width, height=30, corner_radius=4, fg_color=BG,
                        border_color=LINE, border_width=1, text_color=TEXT, font=font(12, mono=True), **kw)


def button(p, text, cmd, kind="ghost", width=None, **kw):
    st = {"primary": dict(fg_color="#0b3a52", border_color=CYAN, text_color=CYAN, hover_color="#0e4d6e"),
          "ghost": dict(fg_color=PANEL2, border_color=LINE, text_color=TEXT, hover_color=SEL),
          "danger": dict(fg_color=PANEL2, border_color=BAD, text_color=BAD, hover_color="#2a0f16"),
          "tiny": dict(fg_color=PANEL2, border_color=LINE, text_color=MUTED, hover_color=SEL)}[kind]
    if width:
        kw["width"] = width
    return ctk.CTkButton(p, text=text, command=cmd, height=28 if kind == "tiny" else 32, corner_radius=4,
                         border_width=1, font=font(11 if kind == "tiny" else 12, True), **st, **kw)


def panel(p, **kw):
    return ctk.CTkFrame(p, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=6, **kw)


def section(p, text):
    return label(p, text, CYAN, 11, True)


def valuebox(p, text="", width=170):
    return ctk.CTkLabel(p, text=text, width=width, height=30, corner_radius=4, fg_color=BG, text_color=CYAN,
                        font=font(12, True, True), anchor="w", padx=8)


def switch(p, text, var, cmd=None):
    return ctk.CTkSwitch(p, text=text, variable=var, command=cmd, font=font(12), text_color=TEXT,
                         progress_color=CYAN, button_color=TEXT, button_hover_color="#ffffff", fg_color=LINE)


def option(p, values, var=None, cmd=None, width=170):
    return ctk.CTkOptionMenu(p, values=values or [""], variable=var, command=cmd, width=width, height=30,
                             corner_radius=4, fg_color=BG, button_color=LINE, button_hover_color=SEL,
                             text_color=TEXT, font=font(12), dropdown_fg_color=PANEL2,
                             dropdown_hover_color=SEL, dropdown_text_color=TEXT)


def to_float(s):
    return float(str(s).replace(",", ".").strip())


# ---------------------------------------------------------------- application
class App:
    def __init__(self, minimized=False):
        self.q = queue.Queue()
        self.log_lines = []
        self.gen = 0
        self.page = "rules"
        self.msg_job = None
        self.float_win = None
        self.ov = None
        self.rec = None
        self.rec_hk = None
        self.tray = None
        self.quitting = False
        self.minimized = minimized

        self.eng = Engine(log=self.log, notify=lambda: self.post(self.refresh_state))
        set_lang(self.eng.cfg.get("lang", "fr"))

        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk(fg_color=BG)
        self.root.title("OCR Trigger")
        self.root.geometry("1040x700")
        self.root.minsize(940, 640)
        self.logo = draw_icon(64)
        self.logo_tk = ImageTk.PhotoImage(self.logo)
        self.root.after(300, lambda: self.root.iconphoto(True, self.logo_tk))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.build_ui()
        self.poll()
        self.start_tray()
        self.eng.start()
        if winutil.IS_WIN:
            try:
                self.eng.cfg["autostart"] = winutil.autostart_enabled()
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    self.log(t("log_not_admin"))
            except Exception:
                pass
        if minimized:
            self.root.after(100, self.hide_window)

    # ---------- thread-safe plumbing
    def post(self, fn):
        self.q.put(fn)

    def poll(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except Exception:
                    self.crash_log()
        except queue.Empty:
            pass
        if not self.quitting:
            self.root.after(50, self.poll)

    @staticmethod
    def crash_log():
        try:
            with open(ERR_LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S\n") + traceback.format_exc() + "\n")
        except Exception:
            pass

    def log(self, msg):
        line = time.strftime("%H:%M:%S  ") + str(msg)
        self.log_lines.append(line)
        del self.log_lines[:-500]
        self.post(lambda: self._log_ui(line))

    def _log_ui(self, line):
        tb = getattr(self, "log_box", None)
        if tb is not None and tb.winfo_exists():
            tb.configure(state="normal")
            tb.insert("end", line + "\n")
            tb.see("end")
            tb.configure(state="disabled")

    def set_msg(self, text, color=WARN):
        self.msg.configure(text=text, text_color=color)
        if self.msg_job:
            self.root.after_cancel(self.msg_job)
        self.msg_job = self.root.after(6000, lambda: self.msg.configure(text=""))

    # ---------- layout
    def build_ui(self):
        self.gen += 1
        keep = (getattr(self, "r_i", None), getattr(self, "s_i", None))
        for w in self.root.winfo_children():
            w.destroy()
        self.float_win = None
        self.ov = None
        r = self.root
        r.grid_columnconfigure(1, weight=1)
        r.grid_rowconfigure(2, weight=1)

        # header
        head = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, height=64)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.grid_columnconfigure(2, weight=1)
        logo = ctk.CTkImage(self.logo, self.logo, size=(40, 40))
        ctk.CTkLabel(head, image=logo, text="").grid(row=0, column=0, padx=(14, 10), pady=10, rowspan=2)
        label(head, t("app_title"), CYAN, 18, True).grid(row=0, column=1, sticky="sw", pady=(8, 0))
        label(head, t("subtitle"), MUTED, 11).grid(row=1, column=1, sticky="nw")
        self.status = label(head, "", MUTED, 14, True)
        self.status.grid(row=0, column=3, rowspan=2, padx=14)
        self.btn_main = button(head, "", self.eng.toggle, "primary", width=150)
        self.btn_main.grid(row=0, column=4, rowspan=2, padx=(0, 14))
        self.hint = label(head, "", MUTED, 11)
        self.hint.grid(row=0, column=2, rowspan=2, sticky="e", padx=10)
        ctk.CTkFrame(r, fg_color=CYAN, height=2, corner_radius=0).grid(row=1, column=0, columnspan=2, sticky="ew")

        # sidebar
        side = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, width=190)
        side.grid(row=2, column=0, sticky="ns")
        side.grid_propagate(False)
        self.nav = {}
        for i, (key, icon) in enumerate([("rules", "◎"), ("series", "⏱"), ("preview", "▣"),
                                         ("settings", "⚙"), ("log", "☰")]):
            b = ctk.CTkButton(side, text=f"  {icon}   {t('nav_' + key)}", anchor="w", height=42,
                              corner_radius=0, fg_color="transparent", hover_color=SEL, text_color=TEXT,
                              font=font(13, True), command=lambda k=key: self.show(k))
            b.grid(row=i, column=0, sticky="ew", pady=(10 if i == 0 else 0, 0))
            self.nav[key] = b
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(6, weight=1)
        self.seg = ctk.CTkSegmentedButton(side, values=["FR", "EN"], command=self.change_lang, width=120,
                                          fg_color=BG, selected_color="#0b3a52", selected_hover_color="#0e4d6e",
                                          unselected_color=BG, unselected_hover_color=SEL, text_color=CYAN,
                                          font=font(11, True))
        self.seg.set(self.eng.cfg.get("lang", "fr").upper())
        self.seg.grid(row=7, column=0, pady=14)

        # pages
        self.content = ctk.CTkFrame(r, fg_color=BG, corner_radius=0)
        self.content.grid(row=2, column=1, sticky="nsew", padx=12, pady=12)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages = {}
        for name, builder in [("rules", self.build_rules), ("series", self.build_series),
                              ("preview", self.build_preview), ("settings", self.build_settings),
                              ("log", self.build_log)]:
            f = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
            f.grid(row=0, column=0, sticky="nsew")
            self.pages[name] = f
            builder(f)

        # footer
        foot = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, height=28)
        foot.grid(row=3, column=0, columnspan=2, sticky="ew")
        foot.grid_columnconfigure(0, weight=1)
        self.msg = label(foot, "", WARN, 11)
        self.msg.grid(row=0, column=0, sticky="w", padx=12, pady=3)
        self.f_ocr = label(foot, "", MUTED, 11)
        self.f_ocr.grid(row=0, column=1, padx=10)
        self.f_cap = label(foot, "", MUTED, 11)
        self.f_cap.grid(row=0, column=2, padx=10)

        self.show(self.page)
        self.refresh_state()
        for line in self.log_lines:
            self._log_ui(line)
        if keep[0] is not None:
            self.select_rule(keep[0])
        if keep[1] is not None:
            self.select_series(keep[1])

    def show(self, name):
        self.page = name
        self.pages[name].tkraise()
        for k, b in self.nav.items():
            b.configure(fg_color=SEL if k == name else "transparent", text_color=CYAN if k == name else TEXT)
        if name == "preview":
            self.refresh_preview_rules()

    def change_lang(self, code):
        code = code.lower()
        self.eng.cfg["lang"] = code
        set_lang(code)
        self.eng.save()
        self.build_ui()
        self.sync_tray()

    def refresh_state(self):
        if not hasattr(self, "status") or not self.status.winfo_exists():
            return
        e = self.eng
        self.status.configure(text="● " + t("status_on" if e.active else "status_off"),
                              text_color=OK if e.active else MUTED)
        self.btn_main.configure(text=t("btn_stop" if e.active else "btn_start"))
        self.hint.configure(text=t("hotkey_hint", key=(e.cfg["global_hotkey"] or "—").upper()))
        self.f_ocr.configure(text={"ready": t("ocr_ready"), "loading": t("ocr_loading"),
                                   "error": t("ocr_error")}[e.ocr_state],
                             text_color={"ready": OK, "loading": WARN, "error": BAD}[e.ocr_state])
        self.f_cap.configure(text=t("cap_dxgi" if e.capture_mode == "dxgi" else "cap_gdi"),
                             text_color=OK if e.capture_mode == "dxgi" else WARN)
        self.refresh_rule_list()
        self.refresh_series_list()
        self.sync_tray()
        self.sync_overlay()

    # ---------- capture helpers
    def capture_key(self, setter, btn):
        if keyboard is None:
            return
        old = btn.cget("text")
        btn.configure(text=t("press_key"), state="disabled")

        def work():
            try:
                k = keyboard.read_hotkey(suppress=False)
            except Exception:
                k = None

            def done():
                if btn.winfo_exists():
                    btn.configure(text=old, state="normal")
                if k:
                    setter(k)
            self.post(done)
        threading.Thread(target=work, daemon=True).start()

    def pick(self, mode, cb):
        """Capture différée : fenêtre masquée, compte à rebours, capture DXGI figée, sélection."""
        try:
            delay = max(0, int(to_float(self.eng.cfg.get("delay", 5))))
        except ValueError:
            delay = 5
        self.root.withdraw()
        cd = tk.Toplevel(self.root)
        cd.overrideredirect(True)
        cd.attributes("-topmost", True)
        cd.configure(bg=BG, highlightbackground=CYAN, highlightthickness=1)
        lb = tk.Label(cd, bg=BG, fg=CYAN, font=(FONT, 14, "bold"), padx=16, pady=8)
        lb.pack()
        cd.geometry("+30+30")

        def tick(n):
            if n <= 0:
                cd.destroy()
                self.root.after(250, grab)
                return
            lb.config(text=t("countdown", n=n))
            self.root.after(1000, lambda: tick(n - 1))

        def grab():
            try:
                f = self.eng.grab_frame()
                img = Image.fromarray(np.ascontiguousarray(f[:, :, :3][:, :, ::-1]))
            except Exception as e:
                self.root.deiconify()
                self.set_msg(str(e), BAD)
                return
            self.overlay(img, mode, cb)

        tick(delay)

    def overlay(self, img, mode, cb):
        W, H = img.size
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.geometry(f"{W}x{H}+0+0")
        top.attributes("-topmost", True)
        cv = tk.Canvas(top, width=W, height=H, highlightthickness=0, cursor="crosshair", bg="black")
        cv.pack()
        dim = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.35)
        ph = ImageTk.PhotoImage(dim)
        cv.create_image(0, 0, image=ph, anchor="nw")
        cv.ph = ph
        txt = t("pick_rect" if mode == "rect" else "pick_point")
        cv.create_rectangle(W // 2 - 300, 20, W // 2 + 300, 60, fill=BG, outline=CYAN)
        cv.create_text(W // 2, 40, text=txt, fill=CYAN, font=(FONT, 13, "bold"))
        st = {"x": 0, "y": 0, "id": None}

        def close(result=None):
            top.destroy()
            self.root.deiconify()
            if result is not None:
                cb(result)

        def press(e):
            if mode == "point":
                close((e.x, e.y))
                return
            st["x"], st["y"] = e.x, e.y
            st["id"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline=CYAN, width=2)

        def drag(e):
            if st["id"]:
                cv.coords(st["id"], st["x"], st["y"], e.x, e.y)

        def release(e):
            if mode != "rect" or not st["id"]:
                return
            x1, x2 = sorted((st["x"], e.x))
            y1, y2 = sorted((st["y"], e.y))
            if x2 - x1 < 5 or y2 - y1 < 5:
                cv.delete(st["id"])
                st["id"] = None
                return
            close([x1, y1, x2 - x1, y2 - y1])

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", release)
        for w in (top, cv):
            w.bind("<Escape>", lambda e: close())
            w.bind("<Button-3>", lambda e: close())
        top.focus_force()
        cv.focus_set()

    # ---------- generic list
    def fill_list(self, frame, rows, sel, on_select):
        for w in frame.winfo_children():
            w.destroy()
        for i, (title, sub, on) in enumerate(rows):
            b = ctk.CTkButton(frame, text=f"{'●' if on else '○'}  {title}\n     {sub}", anchor="w", height=50,
                              corner_radius=4, border_width=1, font=font(12, i == sel),
                              fg_color=SEL if i == sel else PANEL2, hover_color=SEL,
                              border_color=CYAN if i == sel else LINE,
                              text_color=TEXT if on else MUTED, command=lambda i=i: on_select(i))
            b.pack(fill="x", pady=2)

    @staticmethod
    def swap(show, hide):
        hide.grid_remove()
        show.grid()

    def field(self, parent, row, text, widget_builder):
        label(parent, text, MUTED, 11).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        w = widget_builder
        w.grid(row=row, column=1, sticky="w", pady=5)
        return w

    # ================================================================ RULES
    def build_rules(self, page):
        self.r_i = None
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(0, weight=1)
        left = panel(page, width=270)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        section(top, t("rules_title")).pack(side="left")
        button(top, t("new_item"), self.new_rule, "primary", width=100).pack(side="right")
        self.r_list = ctk.CTkScrollableFrame(left, fg_color="transparent", width=230)
        self.r_list.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 6))

        right = panel(page)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        self.r_none = label(right, t("none_selected"), MUTED, 12)
        self.r_none.grid(row=0, column=0)
        ed = ctk.CTkFrame(right, fg_color="transparent")
        self.r_ed = ed
        ed.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        ed.grid_columnconfigure(1, weight=1)
        self.rv = {"name": tk.StringVar(), "text": tk.StringVar(), "cooldown": tk.StringVar(),
                   "enabled": tk.BooleanVar()}
        self.r_key, self.r_hot, self.r_region = "", "", [0, 0, 300, 100]
        section(ed, t("ed_rule")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.field(ed, 1, t("f_name"), entry(ed, self.rv["name"], 260))
        self.field(ed, 2, "", switch(ed, t("f_enabled"), self.rv["enabled"]))
        self.field(ed, 3, t("f_text"), entry(ed, self.rv["text"], 380))
        label(ed, t("f_text_hint"), MUTED, 10).grid(row=4, column=1, sticky="w")

        kf = ctk.CTkFrame(ed, fg_color="transparent")
        self.r_key_lbl = valuebox(kf)
        self.r_key_lbl.pack(side="left")
        self.r_key_btn = button(kf, t("btn_set"), lambda: self.capture_key(self.set_rkey, self.r_key_btn), width=90)
        self.r_key_btn.pack(side="left", padx=6)
        self.field(ed, 5, t("f_key"), kf)
        self.field(ed, 6, t("f_cooldown"), entry(ed, self.rv["cooldown"], 80))

        hf = ctk.CTkFrame(ed, fg_color="transparent")
        self.r_hot_lbl = valuebox(hf)
        self.r_hot_lbl.pack(side="left")
        self.r_hot_btn = button(hf, t("btn_set"), lambda: self.capture_key(self.set_rhot, self.r_hot_btn), width=90)
        self.r_hot_btn.pack(side="left", padx=6)
        button(hf, t("btn_clear"), lambda: self.set_rhot(""), "tiny", width=70).pack(side="left")
        self.field(ed, 7, t("f_hotkey"), hf)

        zf = ctk.CTkFrame(ed, fg_color="transparent")
        self.r_reg_lbl = valuebox(zf, width=250)
        self.r_reg_lbl.pack(side="left")
        button(zf, t("btn_pick_zone"), lambda: self.pick("rect", self.set_rregion), "primary", width=150).pack(
            side="left", padx=6)
        self.field(ed, 8, t("f_region"), zf)

        bf = ctk.CTkFrame(ed, fg_color="transparent")
        bf.grid(row=9, column=0, columnspan=2, sticky="w", pady=(18, 0))
        button(bf, t("btn_test"), self.test_rule, width=130).pack(side="left", padx=(0, 8))
        button(bf, t("btn_save"), self.save_rule, "primary", width=130).pack(side="left", padx=(0, 8))
        button(bf, t("btn_delete"), self.delete_rule, "danger", width=130).pack(side="left")
        self.swap(self.r_none, self.r_ed)
        self.refresh_rule_list()

    def set_rkey(self, k):
        self.r_key = k
        self.r_key_lbl.configure(text=k or "—")

    def set_rhot(self, k):
        self.r_hot = k
        self.r_hot_lbl.configure(text=k or "—")

    def set_rregion(self, r):
        self.r_region = list(r)
        x, y, w, h = r
        self.r_reg_lbl.configure(text=t("region_fmt", x=x, y=y, w=w, h=h))
        self.log(t("log_zone", r=r))

    def refresh_rule_list(self):
        if not hasattr(self, "r_list") or not self.r_list.winfo_exists():
            return
        rows = [(r["name"] or "—", t("rule_summary", text=r["text"] or "…", key=r["key"] or "…"), r["enabled"])
                for r in self.eng.cfg["rules"]]
        self.fill_list(self.r_list, rows, self.r_i, self.select_rule)

    def select_rule(self, i):
        rules = self.eng.cfg["rules"]
        if i is None or i >= len(rules):
            self.r_i = None
            self.swap(self.r_none, self.r_ed)
            return self.refresh_rule_list()
        self.r_i = i
        r = rules[i]
        self.rv["name"].set(r["name"])
        self.rv["text"].set(r["text"])
        self.rv["cooldown"].set(str(r["cooldown"]))
        self.rv["enabled"].set(r["enabled"])
        self.set_rkey(r["key"])
        self.set_rhot(r["hotkey"])
        self.set_rregion(r["region"])
        self.swap(self.r_ed, self.r_none)
        self.refresh_rule_list()

    def new_rule(self):
        rules = self.eng.cfg["rules"]
        r = clone(NEW_RULE)
        r["name"] = t("rule_default_name", n=len(rules) + 1)
        rules.append(r)
        self.eng.save()
        self.select_rule(len(rules) - 1)

    def save_rule(self):
        if self.r_i is None:
            return self.set_msg(t("need_item"))
        try:
            cd = to_float(self.rv["cooldown"].get())
        except ValueError:
            return self.set_msg(t("err_num"), BAD)
        r = self.eng.cfg["rules"][self.r_i]
        r.update(name=self.rv["name"].get().strip(), text=self.rv["text"].get().strip(), key=self.r_key,
                 hotkey=self.r_hot, cooldown=cd, enabled=self.rv["enabled"].get(), region=list(self.r_region))
        self.eng.save()
        self.eng.register_hotkeys()
        self.log(t("log_saved", name=r["name"]))
        self.set_msg(t("log_saved", name=r["name"]), OK)
        self.refresh_rule_list()

    def delete_rule(self):
        if self.r_i is None:
            return self.set_msg(t("need_item"))
        self.eng.cfg["rules"].pop(self.r_i)
        self.eng.last.clear()
        self.eng.last_text.clear()
        self.eng.save()
        self.eng.register_hotkeys()
        self.select_rule(None)

    def test_rule(self):
        if self.eng.ocr is None:
            return self.set_msg(t("no_ocr_yet"))
        region = list(self.r_region)

        def work():
            try:
                txt = self.eng.read_region(region)
                self.log(t("log_test", txt=txt))
                self.post(lambda: self.set_msg(t("log_test", txt=txt), CYAN))
            except Exception as e:
                self.log(str(e))
        threading.Thread(target=work, daemon=True).start()

    # ================================================================ SERIES
    def build_series(self, page):
        self.s_i = None
        self.st_i = None
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(0, weight=1)
        left = panel(page, width=270)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        section(top, t("nav_series").upper()).pack(side="left")
        button(top, t("new_item"), self.new_series, "primary", width=100).pack(side="right")
        self.s_list = ctk.CTkScrollableFrame(left, fg_color="transparent", width=230)
        self.s_list.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 6))

        right = panel(page)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        self.s_none = label(right, t("none_selected"), MUTED, 12)
        self.s_none.grid(row=0, column=0)
        ed = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.s_ed = ed
        ed.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        ed.grid_columnconfigure(1, weight=1)
        self.sv = {k: tk.StringVar() for k in ("name", "interval", "jitter", "repeat", "duration")}
        self.sv["enabled"] = tk.BooleanVar()
        self.s_hot = ""
        section(ed, t("ed_series")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.field(ed, 1, t("f_name"), entry(ed, self.sv["name"], 260))
        ef = ctk.CTkFrame(ed, fg_color="transparent")
        switch(ef, t("f_enabled"), self.sv["enabled"]).pack(side="left")
        self.s_cd = label(ef, "", CYAN, 12, True, mono=True)
        self.s_cd.pack(side="left", padx=24)
        self.field(ed, 2, "", ef)
        self.root.after(500, lambda g=self.gen: self.cd_tick(g))
        hf = ctk.CTkFrame(ed, fg_color="transparent")
        self.s_hot_lbl = valuebox(hf)
        self.s_hot_lbl.pack(side="left")
        self.s_hot_btn = button(hf, t("btn_set"), lambda: self.capture_key(self.set_shot, self.s_hot_btn), width=90)
        self.s_hot_btn.pack(side="left", padx=6)
        button(hf, t("btn_clear"), lambda: self.set_shot(""), "tiny", width=70).pack(side="left")
        self.field(ed, 3, t("f_hotkey"), hf)
        nums = ctk.CTkFrame(ed, fg_color="transparent")
        for c, (k, txt, w) in enumerate([("interval", "s_interval", 80), ("jitter", "s_jitter", 80),
                                         ("repeat", "s_repeat", 80), ("duration", "s_duration", 80)]):
            label(nums, t(txt), MUTED, 10).grid(row=0, column=c, sticky="w", padx=(0, 10))
            entry(nums, self.sv[k], w).grid(row=1, column=c, sticky="w", padx=(0, 10))
        nums.grid(row=4, column=0, columnspan=2, sticky="w", pady=6)

        section(ed, t("steps_title")).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.st_list = ctk.CTkScrollableFrame(ed, fg_color=BG, height=150, border_width=1, border_color=LINE)
        self.st_list.grid(row=6, column=0, columnspan=2, sticky="ew")
        rf = ctk.CTkFrame(ed, fg_color="transparent")
        rf.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.rec_btn = button(rf, t("btn_rec_stop") if self.rec else t("btn_rec"), self.toggle_record, "danger",
                              width=230)
        self.rec_btn.pack(side="left")
        label(rf, t("rec_hint", key="F10"), MUTED, 10).pack(side="left", padx=10)

        # formulaire d'étape
        sf = ctk.CTkFrame(ed, fg_color=PANEL2, border_color=LINE, border_width=1, corner_radius=4)
        sf.grid(row=8, column=0, columnspan=2, sticky="ew", pady=8)
        self.type_names = {"key": t("type_key"), "hold": t("type_hold"), "click": t("type_click"),
                           "wait": t("type_wait")}
        self.btn_names = {"left": t("btn_left"), "right": t("btn_right"), "middle": t("btn_middle")}
        self.stv = {"type": tk.StringVar(value=self.type_names["key"]), "secs": tk.StringVar(value="0.06"),
                    "btn": tk.StringVar(value=self.btn_names["left"])}
        self.st_key, self.st_pt = "", None
        self.sr = {}
        r0 = ctk.CTkFrame(sf, fg_color="transparent")
        label(r0, t("step_type"), MUTED, 11).pack(side="left", padx=(0, 10))
        option(r0, list(self.type_names.values()), self.stv["type"], self.step_type_changed, 170).pack(side="left")
        r0.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        r1 = ctk.CTkFrame(sf, fg_color="transparent")
        label(r1, t("f_key"), MUTED, 11).pack(side="left", padx=(0, 10))
        self.st_key_lbl = valuebox(r1, "—", 130)
        self.st_key_lbl.pack(side="left")
        self.st_key_btn = button(r1, t("btn_set"), lambda: self.capture_key(self.set_stkey, self.st_key_btn), width=80)
        self.st_key_btn.pack(side="left", padx=6)
        self.sr["key"] = r1
        r2 = ctk.CTkFrame(sf, fg_color="transparent")
        label(r2, t("step_secs"), MUTED, 11).pack(side="left", padx=(0, 10))
        entry(r2, self.stv["secs"], 80).pack(side="left")
        self.sr["secs"] = r2
        r3 = ctk.CTkFrame(sf, fg_color="transparent")
        label(r3, t("step_pt"), MUTED, 11).pack(side="left", padx=(0, 10))
        self.st_pt_lbl = valuebox(r3, "—", 130)
        self.st_pt_lbl.pack(side="left")
        button(r3, t("btn_pick_pt"), lambda: self.pick("point", self.set_stpt), "primary", width=140).pack(
            side="left", padx=6)
        option(r3, list(self.btn_names.values()), self.stv["btn"], None, 100).pack(side="left")
        self.sr["pt"] = r3
        r4 = ctk.CTkFrame(sf, fg_color="transparent")
        button(r4, t("btn_add_step"), self.add_step, "primary", width=150).pack(side="left", padx=(0, 8))
        button(r4, t("btn_upd_step"), self.upd_step, width=210).pack(side="left")
        r4.grid(row=4, column=0, sticky="w", padx=10, pady=(4, 8))
        self.step_type_changed()

        bf = ctk.CTkFrame(ed, fg_color="transparent")
        bf.grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        button(bf, t("btn_save"), self.save_series, "primary", width=130).pack(side="left", padx=(0, 8))
        button(bf, t("btn_delete"), self.delete_series, "danger", width=130).pack(side="left")
        self.swap(self.s_none, self.s_ed)
        self.refresh_series_list()

    def code_of(self, names, shown):
        return next((k for k, v in names.items() if v == shown), next(iter(names)))

    def step_type_changed(self, _=None):
        kind = self.code_of(self.type_names, self.stv["type"].get())
        layout = {"key": ("key", "secs"), "hold": ("key", "secs"), "click": ("pt",), "wait": ("secs",)}[kind]
        for n, w in self.sr.items():
            w.grid_forget()
        for row, n in enumerate(layout, start=1):
            self.sr[n].grid(row=row, column=0, sticky="w", padx=10, pady=2)
        if kind in DEFAULT_SECS and self.st_i is None:
            self.stv["secs"].set(str(DEFAULT_SECS[kind]))

    def set_stkey(self, k):
        self.st_key = k
        self.st_key_lbl.configure(text=k or "—")

    def set_stpt(self, p):
        self.st_pt = tuple(p)
        self.st_pt_lbl.configure(text=f"{p[0]}, {p[1]}")
        self.log(t("log_point", p=p))

    def set_shot(self, k):
        self.s_hot = k
        self.s_hot_lbl.configure(text=k or "—")

    def refresh_series_list(self):
        if not hasattr(self, "s_list") or not self.s_list.winfo_exists():
            return
        rows = []
        for i, s in enumerate(self.eng.cfg["series"]):
            tag = " ✓" if i in self.eng.finished else ""
            rows.append(((s["name"] or "—") + tag, t("series_summary", iv=s["interval"], j=s["jitter"],
                                                    n=len(s["steps"])), s["enabled"]))
        self.fill_list(self.s_list, rows, self.s_i, self.select_series)

    def select_series(self, i):
        series = self.eng.cfg["series"]
        if i is None or i >= len(series):
            self.s_i = None
            self.swap(self.s_none, self.s_ed)
            return self.refresh_series_list()
        self.s_i, self.st_i = i, None
        s = series[i]
        self.sv["name"].set(s["name"])
        self.sv["interval"].set(str(s["interval"]))
        self.sv["jitter"].set(str(s["jitter"]))
        self.sv["repeat"].set(str(s["repeat_max"]))
        self.sv["duration"].set(str(s["duration_max"]))
        self.sv["enabled"].set(s["enabled"])
        self.set_shot(s["hotkey"])
        self.swap(self.s_ed, self.s_none)
        self.refresh_steps()
        self.refresh_series_list()

    def new_series(self):
        series = self.eng.cfg["series"]
        s = clone(NEW_SERIES)
        s["name"] = t("series_default_name", n=len(series) + 1)
        series.append(s)
        self.eng.save()
        self.select_series(len(series) - 1)

    def save_series(self):
        if self.s_i is None:
            return self.set_msg(t("need_item"))
        try:
            vals = dict(interval=to_float(self.sv["interval"].get()), jitter=to_float(self.sv["jitter"].get()),
                        repeat_max=int(to_float(self.sv["repeat"].get())),
                        duration_max=to_float(self.sv["duration"].get()))
        except ValueError:
            return self.set_msg(t("err_num"), BAD)
        s = self.eng.cfg["series"][self.s_i]
        s.update(vals, name=self.sv["name"].get().strip(), hotkey=self.s_hot, enabled=self.sv["enabled"].get())
        self.eng.finished.discard(self.s_i)
        self.eng.save()
        self.eng.register_hotkeys()
        self.eng.sync_series()
        self.log(t("log_saved", name=s["name"]))
        self.set_msg(t("log_saved", name=s["name"]), OK)
        self.refresh_series_list()

    def delete_series(self):
        if self.s_i is None:
            return self.set_msg(t("need_item"))
        self.eng.stop_all_series()
        self.eng.cfg["series"].pop(self.s_i)
        self.eng.save()
        self.eng.register_hotkeys()
        self.eng.sync_series()
        self.select_series(None)

    def cd_tick(self, gen):
        if gen != self.gen or self.quitting:
            return
        try:
            nr = self.eng.next_run.get(self.s_i) if self.s_i is not None else None
            if nr and self.eng.active:
                self.s_cd.configure(text="⏳ " + t("next_in", s=max(0, int(nr - time.time() + 0.99))))
            else:
                self.s_cd.configure(text="")
        except Exception:
            pass
        self.root.after(500, lambda: self.cd_tick(gen))

    # ---- enregistreur
    def toggle_record(self):
        if self.rec is None:
            if self.s_i is None:
                return self.set_msg(t("need_item"))
            if keyboard is None:
                return
            if self.eng.active:
                self.eng.set_active(False)
            self.rec = Recorder("f10")
            self.rec.start()
            self.rec_hk = keyboard.add_hotkey("f10", lambda: self.post(lambda: self.finish_record(False)))
            self.rec_btn.configure(text=t("btn_rec_stop"))
            self.log(t("log_rec_start", key="F10"))
        else:
            self.finish_record(True)

    def finish_record(self, from_button=False):
        if self.rec is None:
            return
        steps = self.rec.stop()
        self.rec = None
        try:
            keyboard.remove_hotkey(self.rec_hk)
        except Exception:
            pass
        if from_button and steps and steps[-1]["type"] == "click":
            steps.pop()  # le clic sur le bouton Arrêter
        if self.rec_btn.winfo_exists():
            self.rec_btn.configure(text=t("btn_rec"))
        if self.s_i is not None and self.s_i < len(self.eng.cfg["series"]):
            self.eng.cfg["series"][self.s_i]["steps"].extend(steps)
            self.eng.save()
            self.refresh_steps()
            self.refresh_series_list()
        self.log(t("log_rec_done", n=len(steps)))
        self.show_window()

    # ---- steps
    def step_label(self, st):
        k = st["type"]
        if k == "key":
            return t("step_lbl_key", key=st["key"], s=st.get("secs", DEFAULT_SECS["key"]))
        if k == "hold":
            return t("step_lbl_hold", key=st["key"], s=st.get("secs", DEFAULT_SECS["hold"]))
        if k == "click":
            return t("step_lbl_click", b=self.btn_names[st["button"]], x=st["x"], y=st["y"])
        return t("step_lbl_wait", s=st.get("secs", 1.0))

    def refresh_steps(self):
        for w in self.st_list.winfo_children():
            w.destroy()
        if self.s_i is None:
            return
        steps = self.eng.cfg["series"][self.s_i]["steps"]
        if not steps:
            label(self.st_list, t("no_steps"), MUTED, 11).pack(pady=8)
        for i, st in enumerate(steps):
            row = ctk.CTkFrame(self.st_list, fg_color=SEL if i == self.st_i else "transparent", corner_radius=4)
            row.pack(fill="x", pady=1)
            b = ctk.CTkButton(row, text=f"{i + 1}.  {self.step_label(st)}", anchor="w", height=28,
                              fg_color="transparent", hover_color=SEL, text_color=TEXT, font=font(12, mono=True),
                              command=lambda i=i: self.select_step(i))
            b.pack(side="left", fill="x", expand=True)
            for txt, d, kind in (("✕", 0, "tiny"), ("▼", 1, "tiny"), ("▲", -1, "tiny")):
                cmd = (lambda i=i: self.del_step(i)) if d == 0 else (lambda i=i, d=d: self.move_step(i, d))
                button(row, txt, cmd, kind, width=30).pack(side="right", padx=2, pady=1)

    def select_step(self, i):
        st = self.eng.cfg["series"][self.s_i]["steps"][i]
        self.st_i = i
        self.stv["type"].set(self.type_names[st["type"]])
        self.stv["secs"].set(str(st.get("secs", DEFAULT_SECS[st["type"]])))
        self.set_stkey(st.get("key", ""))
        if st["type"] == "click":
            self.set_stpt((st["x"], st["y"]))
            self.stv["btn"].set(self.btn_names[st["button"]])
        self.step_type_changed()
        self.refresh_steps()

    def form_step(self):
        kind = self.code_of(self.type_names, self.stv["type"].get())
        st = {"type": kind}
        if kind in ("key", "hold"):
            if not self.st_key:
                self.set_msg(t("err_key"), BAD)
                return None
            st["key"] = self.st_key
        if kind == "click":
            if not self.st_pt:
                self.set_msg(t("err_pt"), BAD)
                return None
            st.update(x=self.st_pt[0], y=self.st_pt[1], button=self.code_of(self.btn_names, self.stv["btn"].get()))
        else:
            try:
                st["secs"] = max(0.0, to_float(self.stv["secs"].get()))
            except ValueError:
                self.set_msg(t("err_secs"), BAD)
                return None
        return st

    def add_step(self):
        if self.s_i is None:
            return self.set_msg(t("need_item"))
        st = self.form_step()
        if st:
            self.eng.cfg["series"][self.s_i]["steps"].append(st)
            self.eng.save()
            self.refresh_steps()
            self.refresh_series_list()

    def upd_step(self):
        if self.s_i is None or self.st_i is None:
            return self.set_msg(t("need_item"))
        st = self.form_step()
        if st:
            self.eng.cfg["series"][self.s_i]["steps"][self.st_i] = st
            self.eng.save()
            self.refresh_steps()

    def del_step(self, i):
        self.eng.cfg["series"][self.s_i]["steps"].pop(i)
        self.st_i = None
        self.eng.save()
        self.refresh_steps()
        self.refresh_series_list()

    def move_step(self, i, d):
        steps = self.eng.cfg["series"][self.s_i]["steps"]
        j = i + d
        if 0 <= j < len(steps):
            steps[i], steps[j] = steps[j], steps[i]
            self.st_i = j
            self.eng.save()
            self.refresh_steps()

    # ================================================================ PREVIEW
    def build_preview(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        box = panel(page)
        box.grid(row=0, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=12)
        section(top, t("prev_title")).pack(side="left", padx=(0, 20))
        label(top, t("prev_rule"), MUTED, 11).pack(side="left", padx=(0, 8))
        self.pv_var = tk.StringVar()
        self.pv_menu = option(top, [""], self.pv_var, None, 220)
        self.pv_menu.pack(side="left")
        button(top, t("prev_floating"), self.toggle_float, "primary", width=170).pack(side="right")
        self.pv_img = tk.Label(box, bg="black", bd=0)
        self.pv_img.grid(row=1, column=0, padx=14, pady=4)
        self.pv_txt = label(box, "", CYAN, 12, mono=True, wraplength=700, justify="left")
        self.pv_txt.grid(row=2, column=0, sticky="w", padx=14, pady=8)
        self.root.after(500, lambda g=self.gen: self.preview_tick(g))

    def refresh_preview_rules(self):
        names = [r["name"] or f"#{i + 1}" for i, r in enumerate(self.eng.cfg["rules"])]
        self.pv_menu.configure(values=names or [t("prev_no_rule")])
        if self.pv_var.get() not in names:
            self.pv_var.set(names[0] if names else t("prev_no_rule"))

    def pv_index(self):
        names = [r["name"] or f"#{i + 1}" for i, r in enumerate(self.eng.cfg["rules"])]
        v = self.pv_var.get()
        return names.index(v) if v in names else None

    def render(self, widget, region, maxw, maxh):
        x, y, w, h = region
        w, h = max(1, w), max(1, h)
        arr = self.eng.crop(region)
        img = Image.fromarray(np.ascontiguousarray(arr[:, :, ::-1]))
        k = min(maxw / w, maxh / h, 3.0)
        img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
        ph = ImageTk.PhotoImage(img)
        widget.configure(image=ph)
        widget.image = ph

    def preview_tick(self, gen):
        if gen != self.gen or self.quitting:
            return
        try:
            i = self.pv_index()
            if i is not None and (self.page == "preview" or self.float_win is not None):
                region = self.eng.cfg["rules"][i]["region"]
                if self.page == "preview":
                    self.render(self.pv_img, region, 720, 330)
                    txt = self.eng.last_text.get(i)
                    self.pv_txt.configure(text=t("prev_ocr", txt=txt) if txt else t("prev_hint"))
                if self.float_win is not None:
                    self.render(self.float_lbl, region, 480, 300)
        except Exception:
            pass
        self.root.after(500, lambda: self.preview_tick(gen))

    def toggle_float(self):
        if self.float_win is not None:
            self.float_win.destroy()
            self.float_win = None
            return
        w = tk.Toplevel(self.root)
        w.title("OCR Trigger — " + t("nav_preview"))
        w.attributes("-topmost", True)
        w.configure(bg="black")
        self.float_lbl = tk.Label(w, bg="black", bd=0)
        self.float_lbl.pack()
        self.float_win = w

        def closed(_=None):
            if self.float_win is w:
                self.float_win = None
            w.destroy()
        w.protocol("WM_DELETE_WINDOW", closed)

    # ================================================================ SETTINGS
    def build_settings(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        box = ctk.CTkScrollableFrame(page, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=6)
        box.grid(row=0, column=0, sticky="nsew")
        box.grid_columnconfigure(1, weight=1)
        c = self.eng.cfg
        self.gv = {"interval": tk.StringVar(value=str(c["interval"])),
                   "ocr_pause": tk.StringVar(value=str(c["ocr_pause"])),
                   "delay": tk.StringVar(value=str(c["delay"])),
                   "autostart": tk.BooleanVar(value=bool(c["autostart"])),
                   "tray": tk.BooleanVar(value=bool(c["tray"])),
                   "overlay": tk.BooleanVar(value=bool(c.get("overlay"))),
                   "sound": tk.BooleanVar(value=bool(c.get("sound")))}
        section(box, t("set_general")).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        gf = ctk.CTkFrame(box, fg_color="transparent")
        self.g_hot_lbl = valuebox(gf, c["global_hotkey"] or "—")
        self.g_hot_lbl.pack(side="left")
        self.g_hot_btn = button(gf, t("btn_set"), lambda: self.capture_key(self.set_ghot, self.g_hot_btn), width=90)
        self.g_hot_btn.pack(side="left", padx=6)
        rows = [(t("set_global_hotkey"), gf), (t("set_interval"), entry(box, self.gv["interval"], 80)),
                (t("set_ocr_pause"), entry(box, self.gv["ocr_pause"], 80)),
                (t("set_delay"), entry(box, self.gv["delay"], 80))]
        for i, (txt, w) in enumerate(rows, start=1):
            label(box, txt, MUTED, 11).grid(row=i, column=0, sticky="w", padx=(16, 14), pady=5)
            w.grid(row=i, column=1, sticky="w", pady=5)
        button(box, t("btn_save"), self.save_settings, "primary", width=130).grid(row=5, column=0, sticky="w",
                                                                                   padx=16, pady=8)
        section(box, t("set_system")).grid(row=6, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        switch(box, t("set_autostart"), self.gv["autostart"], self.toggle_autostart).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=16, pady=5)
        switch(box, t("set_tray"), self.gv["tray"], self.save_tray).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=16, pady=5)
        switch(box, t("set_overlay"), self.gv["overlay"], self.save_overlay).grid(
            row=9, column=0, columnspan=2, sticky="w", padx=16, pady=5)
        switch(box, t("set_sound"), self.gv["sound"], self.save_sound).grid(
            row=10, column=0, columnspan=2, sticky="w", padx=16, pady=5)
        bf = ctk.CTkFrame(box, fg_color="transparent")
        bf.grid(row=11, column=0, columnspan=2, sticky="w", padx=16, pady=8)
        button(bf, t("set_open_cfg"), lambda: winutil.open_folder(app_dir()), width=250).pack(side="left", padx=(0, 8))
        button(bf, t("set_quit"), self.quit_app, "danger", width=200).pack(side="left")
        section(box, t("set_about")).grid(row=12, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        label(box, t("about_text", v=VERSION), MUTED, 11, justify="left").grid(
            row=13, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))

    def set_ghot(self, k):
        self.eng.cfg["global_hotkey"] = k
        self.g_hot_lbl.configure(text=k or "—")
        self.eng.save()
        self.eng.register_hotkeys()
        self.refresh_state()

    def save_settings(self):
        try:
            c = self.eng.cfg
            c["interval"] = max(0.1, to_float(self.gv["interval"].get()))
            c["ocr_pause"] = max(0.0, to_float(self.gv["ocr_pause"].get()))
            c["delay"] = max(0, int(to_float(self.gv["delay"].get())))
        except ValueError:
            return self.set_msg(t("err_num"), BAD)
        self.eng.save()
        self.set_msg("OK", OK)

    def save_tray(self):
        self.eng.cfg["tray"] = bool(self.gv["tray"].get())
        self.eng.save()

    def save_overlay(self):
        self.eng.cfg["overlay"] = bool(self.gv["overlay"].get())
        self.eng.save()
        self.sync_overlay()

    def save_sound(self):
        self.eng.cfg["sound"] = bool(self.gv["sound"].get())
        self.eng.save()
        if self.eng.cfg["sound"]:
            self.eng.beep(True)

    def sync_overlay(self):
        want = bool(self.eng.cfg.get("overlay"))
        if want and self.ov is None:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.attributes("-alpha", 0.85)
            w.configure(bg=BG, highlightbackground=CYAN, highlightthickness=1)
            w.geometry("+16+16")
            self.ov_lbl = tk.Label(w, bg=BG, font=(FONT, 11, "bold"), padx=10, pady=3)
            self.ov_lbl.pack()
            self.ov = w
            w.update_idletasks()
            winutil.click_through(w)
        elif not want and self.ov is not None:
            self.ov.destroy()
            self.ov = None
        if self.ov is not None:
            on = self.eng.active
            self.ov_lbl.config(text="● OCR " + t("status_on" if on else "status_off"), fg=OK if on else MUTED)

    def toggle_autostart(self):
        want = bool(self.gv["autostart"].get())

        def work():
            try:
                winutil.set_autostart(want)
                self.eng.cfg["autostart"] = want
                self.eng.save()
                self.log(t("log_autostart_on" if want else "log_autostart_off"))
            except Exception as e:
                self.log(t("log_autostart_err", e=e))
                self.post(lambda: self.gv["autostart"].set(not want))
        threading.Thread(target=work, daemon=True).start()

    # ================================================================ LOG
    def build_log(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        box = panel(page)
        box.grid(row=0, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        section(top, t("log_title")).pack(side="left")
        button(top, t("btn_clear_log"), self.clear_log, "ghost", width=100).pack(side="right")
        self.log_box = ctk.CTkTextbox(box, fg_color=BG, text_color=TEXT, font=font(12, mono=True),
                                      border_width=1, border_color=LINE, corner_radius=4)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.log_box.configure(state="disabled")

    def clear_log(self):
        self.log_lines.clear()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ================================================================ TRAY / WINDOW
    def start_tray(self):
        if pystray is None:
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem(lambda i: t("tray_show"), lambda i, m=None: self.post(self.show_window), default=True),
                pystray.MenuItem(lambda i: t("tray_stop") if self.eng.active else t("tray_start"),
                                 lambda i, m=None: self.eng.toggle()),
                pystray.MenuItem(lambda i: t("tray_quit"), lambda i, m=None: self.post(self.quit_app)))
            self.tray = pystray.Icon("OCRTrigger", self.logo, "OCR Trigger", menu)
            self.tray.run_detached()
        except Exception as e:
            self.tray = None
            self.log(str(e))

    def sync_tray(self):
        if self.tray is not None:
            try:
                self.tray.title = "OCR Trigger — " + t("status_on" if self.eng.active else "status_off")
                self.tray.update_menu()
            except Exception:
                pass

    def hide_window(self):
        if self.tray is not None:
            self.root.withdraw()
        else:
            self.root.iconify()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self):
        if self.eng.cfg.get("tray", True) and self.tray is not None:
            self.root.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        if self.quitting:
            return
        self.quitting = True
        try:
            self.eng.shutdown()
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    global FONT, MONO
    if not winutil.single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(0, t("single_instance"), "OCR Trigger", 0x40)
        except Exception:
            print(t("single_instance"))
        return
    try:
        tmp = tk.Tk()
        families = set(tkfont.families(tmp))
        tmp.destroy()
    except Exception:
        families = set()
    if "Bahnschrift" in families:
        FONT = "Bahnschrift"
    elif "Segoe UI" not in families and families:
        FONT = "DejaVu Sans" if "DejaVu Sans" in families else FONT
    if "Consolas" not in families and families:
        MONO = "DejaVu Sans Mono" if "DejaVu Sans Mono" in families else MONO
    try:
        app = App(minimized="--minimized" in sys.argv)
        app.root.mainloop()
    except Exception:
        App.crash_log()
        raise
    os._exit(0)


if __name__ == "__main__":
    main()
