"""Génère icon.ico (et icon.png) pour la compilation de l'exe : python make_icon.py"""
from iconart import draw_icon

img = draw_icon(256)
img.save("icon.png")
img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon.ico et icon.png créés")
