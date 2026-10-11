@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :err
python make_icon.py || goto :err
python -m PyInstaller --noconfirm --clean --onefile --noconsole --uac-admin --name OCR_Trigger --icon icon.ico ^
  --collect-all customtkinter --collect-all rapidocr_onnxruntime --collect-all dxcam --collect-all comtypes ^
  --hidden-import pystray._win32 app.py || goto :err
echo.
echo OK : dist\OCR_Trigger.exe
pause
exit /b 0
:err
echo Erreur pendant la compilation.
pause
