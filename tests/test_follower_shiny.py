"""Pruebas de tools/follower_shiny.py (python tests/test_follower_shiny.py). Datos sintéticos."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import follower_shiny as fs

red, dark_red, blue, gold, green = fs.c555(248, 0, 0), fs.c555(200, 0, 0), fs.c555(0, 0, 248), fs.c555(248, 200, 0), fs.c555(0, 248, 0)
sheet = {red: gold}                       # en la hoja, el rojo pasa a dorado
battle = {blue: green}                    # en el sprite de combate, el azul pasa a verde
pal, why = fs.shiny_palette([0x1234, red, blue, fs.c555(8, 8, 8), fs.c555(240, 0, 0)], sheet, battle)
assert pal[0] == 0x1234                   # transparente, igual
assert pal[1] == gold and pal[2] == green and pal[3] == fs.c555(8, 8, 8), pal
assert fs.rgb(pal[4]) == (30, 25, 0), fs.rgb(pal[4])   # casi rojo: dorado con la misma diferencia
assert why == {"hoja": 2, "combate": 1, "igual": 1}, why
assert fs.nearest(dark_red, sheet) is None             # demasiado lejos: no se da por el mismo
print("ok follower_shiny")
