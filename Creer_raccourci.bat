@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\OCR Trigger.lnk'); $s.TargetPath='%~dp0Lancer.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,25'; $s.WindowStyle=7; $s.Description='OCR Trigger (admin auto)'; $s.Save()"
if errorlevel 1 (
  echo Erreur lors de la creation du raccourci.
) else (
  echo Raccourci "OCR Trigger" cree sur le Bureau.
)
pause
