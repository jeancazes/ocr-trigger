"""Moteur OCR Trigger (sans interface) : config, capture écran, OCR, règles, séries d'actions."""
import json
import os
import random
import shutil
import sys
import threading
import time
import unicodedata

import numpy as np

import winutil
from i18n import t

try:
    import keyboard
except Exception:  # pragma: no cover
    keyboard = None
try:  # capture DXGI : fonctionne avec le plein écran (mss/GDI = écran noir)
    import dxcam
except Exception:
    dxcam = None
try:
    import mss
except Exception:  # pragma: no cover
    mss = None

APP_NAME = "OCRTrigger"
VERSION = "2.0.0"

DEFAULT = {"lang": "fr", "global_hotkey": "f9", "interval": 0.5, "ocr_pause": 3.0, "delay": 5,
           "tray": True, "autostart": False, "overlay": False, "sound": False, "rules": [], "series": []}
NEW_RULE = {"name": "", "enabled": True, "region": [0, 0, 300, 100], "text": "", "key": "",
            "cooldown": 2.0, "hotkey": ""}
NEW_SERIES = {"name": "", "enabled": True, "interval": 30.0, "jitter": 25.0, "repeat_max": 0,
              "duration_max": 0.0, "hotkey": "", "steps": []}
DEFAULT_SECS = {"key": 0.06, "hold": 2.0, "wait": 1.0, "click": 0.0}


def app_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def program_dir():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0]))


CONFIG = os.path.join(app_dir(), "config.json")


def clone(x):
    return json.loads(json.dumps(x))


def load_config():
    if not os.path.exists(CONFIG):  # reprise de l'ancienne config (à côté du programme)
        old = os.path.join(program_dir(), "config.json")
        if os.path.exists(old):
            try:
                shutil.copy(old, CONFIG)
            except Exception:
                pass
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    for k, v in DEFAULT.items():
        cfg.setdefault(k, clone(v))
    for r in cfg["rules"]:
        for k, v in NEW_RULE.items():
            r.setdefault(k, clone(v))
    for s in cfg["series"]:
        for k, v in NEW_SERIES.items():
            s.setdefault(k, clone(v))
    return cfg


def save_config(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG)


def norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def text_matches(pattern, text):
    """True si l'un des motifs (séparés par |) est contenu dans le texte lu."""
    nt = norm(text)
    return any(p.strip() and norm(p.strip()) in nt for p in str(pattern).split("|"))


class Engine:
    def __init__(self, log=print, notify=lambda: None):
        self.log = log
        self.notify = notify
        self.cfg = load_config()
        self.active = False
        self.ocr = None
        self.ocr_state = "loading"  # loading / ready / error
        self.ocr_lock = threading.Lock()
        self.cam = None
        self.capture_mode = "gdi"
        self.last = {}
        self.last_text = {}
        self.runners = {}
        self.finished = set()
        self.next_run = {}
        self.ocr_pause_until = 0.0
        self._quit = threading.Event()

    # ---------- démarrage / arrêt ----------
    def start(self):
        self.init_capture()
        self.register_hotkeys()
        threading.Thread(target=self.loop, daemon=True).start()
        threading.Thread(target=self.load_ocr, daemon=True).start()

    def shutdown(self):
        self._quit.set()
        self.stop_all_series()
        try:
            if self.cam is not None:
                self.cam.stop()
        except Exception:
            pass
        try:
            if keyboard is not None:
                keyboard.unhook_all()
        except Exception:
            pass

    def save(self):
        save_config(self.cfg)

    def beep(self, high=True):
        if self.cfg.get("sound"):
            threading.Thread(target=winutil.beep, args=(1400 if high else 800, 120), daemon=True).start()

    # ---------- OCR ----------
    def load_ocr(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR()
            self.ocr_state = "ready"
            self.log(t("log_ocr_ready"))
        except Exception as e:
            self.ocr_state = "error"
            self.log(t("log_ocr_err", e=e))
        self.notify()

    # ---------- capture ----------
    def init_capture(self):
        self.cam = None
        err = ""
        if dxcam is not None:
            try:
                self.cam = dxcam.create(output_idx=0, output_color="BGR")
                self.cam.start(target_fps=10, video_mode=True)
                self.capture_mode = "dxgi"
                self.log(t("log_cap_dxgi"))
                return
            except Exception as e:
                self.cam = None
                err = str(e)
        self.capture_mode = "gdi"
        self.log(t("log_cap_gdi", e=err))

    def grab_frame(self):
        """Image BGR de l'écran principal entier."""
        if self.cam is not None:
            try:
                f = self.cam.get_latest_frame()
                if f is not None:
                    return f
            except Exception:
                pass
        with mss.mss() as sct:
            return np.array(sct.grab(sct.monitors[1]))[:, :, :3]

    def crop(self, region):
        x, y, w, h = region
        return np.ascontiguousarray(self.grab_frame()[y:y + h, x:x + w, :3])

    def read_region(self, region):
        shot = self.crop(region)
        with self.ocr_lock:
            res, _ = self.ocr(shot)
        return " ".join(r[1] for r in res) if res else ""

    # ---------- boucle des règles OCR ----------
    def loop(self):
        while not self._quit.wait(max(0.1, float(self.cfg["interval"]))):
            if not self.active or self.ocr is None:
                continue
            for i, r in enumerate(list(self.cfg["rules"])):
                if not r["enabled"] or not r["text"] or not r["key"]:
                    continue
                try:
                    txt = self.read_region(r["region"])
                except Exception as e:
                    self.log(t("log_rule_read_err", name=r["name"], e=e))
                    continue
                self.last_text[i] = txt
                if text_matches(r["text"], txt):
                    now = time.time()
                    if now - self.last.get(i, 0) >= float(r["cooldown"]):
                        self.last[i] = now
                        self.ocr_pause_until = now + float(self.cfg.get("ocr_pause", 3))
                        keyboard.send(r["key"])
                        self.beep(True)
                        self.log(t("log_rule_hit", name=r["name"], text=r["text"], key=r["key"]))

    # ---------- raccourcis ----------
    def register_hotkeys(self):
        if keyboard is None:
            return
        try:  # bug de la lib keyboard : listener pas encore initialisé au 1er appel
            keyboard.unhook_all_hotkeys()
        except AttributeError:
            pass
        try:
            if self.cfg["global_hotkey"]:
                keyboard.add_hotkey(self.cfg["global_hotkey"], self.toggle)
            for i, r in enumerate(self.cfg["rules"]):
                if r["hotkey"]:
                    keyboard.add_hotkey(r["hotkey"], lambda i=i: self.toggle_rule(i))
            for i, s in enumerate(self.cfg["series"]):
                if s["hotkey"]:
                    keyboard.add_hotkey(s["hotkey"], lambda i=i: self.toggle_series(i))
        except Exception as e:
            self.log(t("log_hotkey_err", e=e))

    # ---------- activation ----------
    def set_active(self, value):
        self.active = bool(value)
        self.finished.clear()
        self.sync_series()
        self.log(t("log_started" if self.active else "log_stopped"))
        self.notify()

    def toggle(self):
        self.set_active(not self.active)

    def toggle_rule(self, i):
        if i < len(self.cfg["rules"]):
            r = self.cfg["rules"][i]
            r["enabled"] = not r["enabled"]
            self.save()
            self.log(t("log_active" if r["enabled"] else "log_inactive", name=r["name"]))
            self.notify()

    def toggle_series(self, i):
        if i < len(self.cfg["series"]):
            s = self.cfg["series"][i]
            s["enabled"] = not s["enabled"]
            self.finished.discard(i)
            self.save()
            self.sync_series()
            self.log(t("log_active" if s["enabled"] else "log_inactive", name=s["name"]))
            self.notify()

    # ---------- séries d'actions ----------
    @staticmethod
    def rnd(v, j):
        """v ± j (j = fraction : 0.25 pour ±25 %)."""
        return max(0.0, float(v) * (1 + random.uniform(-j, j)))

    def stop_all_series(self):
        for _, stop in list(self.runners.values()):
            stop.set()
        self.runners.clear()
        self.finished.clear()

    def sync_series(self):
        for i, s in enumerate(self.cfg["series"]):
            want = self.active and s["enabled"] and i not in self.finished
            r = self.runners.get(i)
            alive = r is not None and r[0].is_alive()
            if want and not alive:
                stop = threading.Event()
                th = threading.Thread(target=self.run_series, args=(i, s, stop), daemon=True)
                self.runners[i] = (th, stop)
                th.start()
            elif not want and alive:
                r[1].set()

    def wait_ocr_free(self, stop):
        while time.time() < self.ocr_pause_until:
            if stop.wait(0.1):
                return False
        return True

    def run_series(self, i, s, stop):
        t0, count = time.time(), 0
        self.log(t("log_series_started", name=s["name"]))
        while not stop.is_set():
            j = float(s["jitter"]) / 100
            w = max(0.05, self.rnd(s["interval"], j))
            self.next_run[i] = time.time() + w
            if stop.wait(w):
                break
            if not self.wait_ocr_free(stop):
                break
            dmax = float(s["duration_max"])
            if dmax > 0 and time.time() - t0 > dmax * 60:
                self.log(t("log_series_dur", name=s["name"]))
                self.finished.add(i)
                break
            self.log(t("log_series_run", name=s["name"], n=count + 1))
            self.beep(False)
            for st in list(s["steps"]):
                if stop.is_set() or not self.wait_ocr_free(stop):
                    break
                try:
                    self.do_step(st, j, stop)
                except Exception as e:
                    self.log(t("log_series_err", name=s["name"], e=e))
            count += 1
            rmax = int(float(s["repeat_max"]))
            if rmax > 0 and count >= rmax:
                self.log(t("log_series_rep", name=s["name"], n=count))
                self.finished.add(i)
                break
        self.next_run.pop(i, None)
        self.notify()

    def do_step(self, st, j, stop):
        kind = st["type"]
        if kind in ("key", "hold"):
            keyboard.press(st["key"])
            try:
                stop.wait(self.rnd(st.get("secs", DEFAULT_SECS[kind]), j))
            finally:
                keyboard.release(st["key"])
        elif kind == "click":
            winutil.mouse_click(st["x"], st["y"], st["button"], self.rnd(0.06, j))
        elif kind == "wait":
            stop.wait(self.rnd(st.get("secs", 1.0), j))
