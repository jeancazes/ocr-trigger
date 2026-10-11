# OCR Trigger 2.0
Lit une zone de l'écran (plein écran OK, capture DXGI) → touche / clic. Séries minutées avec hasard ±%.
FR / EN, icône dans la zone de notification, démarrage avec Windows.

## Obtenir l'exe (GitHub Actions)
1. Crée un dépôt vide `ocr-trigger` sur github.com
2. Dans ce dossier :
   git init && git add . && git commit -m "OCR Trigger" && git branch -M main
   git remote add origin https://github.com/TON_COMPTE/ocr-trigger.git && git push -u origin main
3. Onglet **Actions** → dernier run → **Artifacts** → `OCR_Trigger` → `OCR_Trigger.exe` (portable) + `OCR_Trigger_Setup.exe` (installeur)
4. Release : `git tag v2.0.0 && git push --tags` → les 2 .exe dans **Releases**

## Compiler en local
`build.bat` → `dist\OCR_Trigger.exe` (Python 3.11 recommandé)

## Dev
`Lancer.bat` (admin auto) ou `python app.py`

## Notes
- L'exe demande les droits admin (UAC) pour que le jeu reçoive les touches.
- Exe non signé : SmartScreen → « Informations complémentaires » → « Exécuter quand même ».
- Config : %APPDATA%\OCRTrigger\config.json — erreurs : error.log
- Vérifie les CGU de Star Citizen avant d'automatiser des actions.
- Enregistreur : bouton « Enregistrer » dans une série, F10 pour arrêter.
- Voyant HUD : visible en plein écran fenêtré sans bordure (pas en plein écran exclusif).
