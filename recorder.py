"""Enregistreur d'actions clavier / souris -> étapes de série."""
import time

try:
    import keyboard
except Exception:
    keyboard = None
try:
    import mouse
except Exception:
    mouse = None

MIN_WAIT = 0.3   # pauses plus courtes ignorées
HOLD_MIN = 0.4   # appui plus long = "maintenir"


def build_steps(events, stop_key="f10"):
    """events : liste (t, kind, name, x, y) kind = kdown/kup/mdown. Retourne la liste d'étapes."""
    acts, down = [], {}
    for t, kind, name, x, y in events:
        if name == stop_key:
            continue
        if kind == "kdown":
            down.setdefault(name, t)
        elif kind == "kup" and name in down:
            t0 = down.pop(name)
            dur = max(0.02, t - t0)
            if dur >= HOLD_MIN:
                acts.append((t0, t, {"type": "hold", "key": name, "secs": round(dur, 2)}))
            else:
                acts.append((t0, t, {"type": "key", "key": name, "secs": round(max(dur, 0.04), 2)}))
        elif kind == "mdown":
            acts.append((t, t + 0.06, {"type": "click", "x": x, "y": y, "button": name}))
    acts.sort(key=lambda a: a[0])
    steps, last_end = [], None
    for a0, a1, st in acts:
        if last_end is not None and a0 - last_end >= MIN_WAIT:
            steps.append({"type": "wait", "secs": round(a0 - last_end, 1)})
        steps.append(st)
        last_end = max(last_end or a1, a1)
    return steps


class Recorder:
    def __init__(self, stop_key="f10"):
        self.stop_key = stop_key
        self.events = []
        self.running = False
        self._hk = self._mh = None

    def start(self):
        self.events, self.running = [], True
        if keyboard is not None:
            self._hk = keyboard.hook(self._on_key)
        if mouse is not None:
            self._mh = mouse.hook(self._on_mouse)

    def _on_key(self, e):
        self.events.append((time.time(), "kdown" if e.event_type == "down" else "kup", e.name, 0, 0))

    def _on_mouse(self, e):
        if getattr(e, "event_type", "") == "down" and hasattr(e, "button"):
            x, y = mouse.get_position()
            self.events.append((time.time(), "mdown", e.button, x, y))

    def stop(self):
        self.running = False
        try:
            if self._hk is not None:
                keyboard.unhook(self._hk)
            if self._mh is not None:
                mouse.unhook(self._mh)
        except Exception:
            pass
        return build_steps(self.events, self.stop_key)
