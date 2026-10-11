"""Mises à jour : interroge la dernière release GitHub, télécharge le .exe et se remplace au redémarrage."""
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = "jeancazes/ocr-trigger"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET = "OCR_Trigger.exe"
UA = {"User-Agent": "OCR-Trigger-updater", "Accept": "application/vnd.github+json"}


def parse(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def newer(a, b):
    """True si la version a est plus récente que b."""
    pa, pb = parse(a), parse(b)
    n = max(len(pa), len(pb))
    return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


def check(current, timeout=8):
    """Renvoie None (à jour) ou {tag, notes, url, page}. Lève une exception si le réseau échoue."""
    req = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    tag = d.get("tag_name", "")
    if not tag or not newer(tag, current):
        return None
    url = next((a["browser_download_url"] for a in d.get("assets", []) if a.get("name") == ASSET), "")
    notes = (d.get("body") or "").strip()
    return {"tag": tag, "notes": notes, "url": url, "page": d.get("html_url") or PAGE}


def can_self_update():
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def download(url, dest, progress=lambda p: None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                progress(got / total)
    if os.path.getsize(dest) < 1_000_000:
        raise OSError("fichier téléchargé incomplet")


def apply_and_restart(new_path):
    """Lance un petit script qui remplace l'exe une fois l'appli fermée, puis la relance."""
    exe = sys.executable
    bat = os.path.join(os.path.dirname(new_path), "ocr_trigger_update.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(f'''@echo off
set n=0
timeout /t 2 /nobreak >nul
:retry
move /y "{new_path}" "{exe}" >nul 2>&1
if errorlevel 1 (
  set /a n+=1
  if %n% GEQ 20 goto end
  timeout /t 1 /nobreak >nul
  goto retry
)
start "" "{exe}"
:end
del "%~f0"
''')
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000, close_fds=True)
