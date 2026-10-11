"""Fonctions spécifiques à Windows : clic souris, démarrage automatique, instance unique."""
import ctypes
import os
import subprocess
import sys
import time

IS_WIN = sys.platform == "win32"
TASK_NAME = "OCRTrigger"
NO_WINDOW = 0x08000000


def mouse_click(x, y, button="left", hold=0.06):
    u = ctypes.windll.user32
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    down, up = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
                "middle": (0x0020, 0x0040)}[button]
    u.mouse_event(down, 0, 0, 0, 0)
    time.sleep(hold)
    u.mouse_event(up, 0, 0, 0, 0)


# ---- clavier : SendInput par scancodes (les jeux DirectInput ignorent les touches « virtuelles »)
_VK = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
       "backspace": 0x08, "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12, "left": 0x25,
       "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
       "page up": 0x21, "page down": 0x22, "caps lock": 0x14, "left shift": 0xA0, "right shift": 0xA1,
       "left ctrl": 0xA2, "right ctrl": 0xA3, "left alt": 0xA4, "right alt": 0xA5, "windows": 0x5B,
       ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB,
       "\\": 0xDC, "]": 0xDD, "'": 0xDE}
_EXT = {0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0xA3, 0xA5}


def _vk(name):
    n = str(name).strip().lower()
    if n in _VK:
        return _VK[n]
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    if n.startswith("f") and n[1:].isdigit() and 1 <= int(n[1:]) <= 24:
        return 0x6F + int(n[1:])
    if n.startswith("num ") or n.startswith("numpad "):
        d = n.split()[-1]
        if d.isdigit():
            return 0x60 + int(d)
    if len(n) == 1 and IS_WIN:  # caractère propre à la disposition (AZERTY : ^ $ ù * ! : é & …)
        r = ctypes.windll.user32.VkKeyScanW(ord(n))
        if r != -1 and (r & 0xFF) != 0xFF:
            return r & 0xFF
    raise ValueError("touche inconnue : " + str(name))


class _KI(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _MI(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _IN(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("mi", _MI)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def key_event(name, down):
    """Appui / relâchement d'une touche par scancode (SendInput). Lève une exception si impossible."""
    if not IS_WIN:
        raise OSError("SendInput : Windows uniquement")
    u = ctypes.windll.user32
    try:
        vk = _vk(name)
        sc = u.MapVirtualKeyW(vk, 0)
        ext = vk in _EXT
    except ValueError:  # dernier recours : scancode donné par la lib keyboard
        import keyboard
        codes = keyboard.key_to_scan_codes(str(name))
        sc, ext = codes[0], False
        if sc > 0xFF:
            sc, ext = sc & 0xFF, True
    flags = 0x0008 | (0 if down else 0x0002) | (0x0001 if ext else 0)
    inp = _IN(type=1, ki=_KI(0, sc, flags, 0, 0))
    if u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_IN)) != 1:
        raise OSError("SendInput a échoué")


def send_key(combo, hold=0.06):
    """Appuie sur une touche ou un combo (« ctrl+f5 »), maintient `hold` s, relâche."""
    keys = [k.strip() for k in str(combo).split("+") if k.strip()]
    for k in keys:
        key_event(k, True)
        time.sleep(0.01)
    time.sleep(hold)
    for k in reversed(keys):
        key_event(k, False)


def single_instance():
    """True si c'est la seule instance. Garde le handle vivant tant que le process tourne."""
    if not IS_WIN:
        return True
    global _MUTEX
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\OCRTrigger_single_instance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _ps(script):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "erreur PowerShell").strip()[:300])


def _command():
    if getattr(sys, "frozen", False):
        return sys.executable, "--minimized"
    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        pyw = pyw[:-10] + "pythonw.exe"
    return pyw, '"%s" --minimized' % os.path.abspath(sys.argv[0])


def autostart_enabled():
    if not IS_WIN:
        return False
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True,
                       creationflags=NO_WINDOW)
    return r.returncode == 0


def set_autostart(enable):
    """Tâche planifiée à l'ouverture de session, niveau le plus élevé (pas de fenêtre UAC)."""
    if not IS_WIN:
        return
    if not enable:
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True,
                       creationflags=NO_WINDOW)
        return
    exe, args = _command()
    exe_q, args_q = exe.replace("'", "''"), args.replace("'", "''")
    _ps(
        "$a = New-ScheduledTaskAction -Execute '%s' -Argument '%s'; "
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit ([TimeSpan]::Zero); "
        "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest; "
        "Register-ScheduledTask -TaskName '%s' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null"
        % (exe_q, args_q, TASK_NAME))


def open_folder(path):
    if IS_WIN:
        os.startfile(path)  # noqa


def beep(freq=1000, ms=120):
    if IS_WIN:
        try:
            import winsound
            winsound.Beep(int(freq), int(ms))
        except Exception:
            pass


def click_through(widget):
    """Rend une fenêtre tk transparente aux clics (overlay) : le jeu garde la souris."""
    if not IS_WIN:
        return
    try:
        u = ctypes.windll.user32
        hwnd = u.GetParent(widget.winfo_id()) or widget.winfo_id()
        style = u.GetWindowLongW(hwnd, -20)
        u.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80)  # LAYERED | TRANSPARENT | TOOLWINDOW
    except Exception:
        pass


_SND = {}


def _wav(freq, ms, vol, sweep=0.0):
    import io
    import math
    import struct
    import wave
    rate, n = 22050, int(22050 * ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            env = math.sin(math.pi * i / n) ** 2
            fr = freq + sweep * i / n
            frames += struct.pack("<h", int(32767 * vol * env * math.sin(2 * math.pi * fr * i / rate)))
        f.writeframes(bytes(frames))
    return buf.getvalue()


def ui_sound(kind):
    """Petits sons d'interface (clic discret), non bloquants."""
    if not IS_WIN:
        return
    try:
        import winsound
        if not _SND:
            _SND.update(hover=_wav(2600, 14, 0.10), click=_wav(1500, 38, 0.22, -500),
                        page=_wav(700, 70, 0.18, 500))
        winsound.PlaySound(_SND[kind], winsound.SND_MEMORY | winsound.SND_ASYNC)
    except Exception:
        pass
