@echo off
REM --- Relance automatiquement en administrateur si necessaire ---
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0"

REM --- Installe les dependances si elles manquent ---
python -c "import keyboard, mss, numpy, PIL, dxcam, rapidocr_onnxruntime" >nul 2>&1
if errorlevel 1 (
  echo Installation des dependances...
  python -m pip install keyboard mss numpy pillow dxcam rapidocr-onnxruntime
)

REM --- Lance l'appli ---
python app.py
if errorlevel 1 (
  echo.
  echo Erreur au lancement (voir le message ci-dessus).
  pause
)
