"""Pruebas de tools/follower_new.py (python tests/test_follower_new.py). Hojas sintéticas."""
import os, struct, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import follower_new as fn
try:
    from PIL import Image
except ImportError:                                # Pillow solo hace falta para las herramientas de imágenes
    print("ok follower_new (sin Pillow: se salta)"); sys.exit(0)

RED, BLUE = (248, 0, 0, 255), (0, 0, 248, 255)
# hoja de 128x128 "real" (4x4 cuadros de 32) con un píxel distinto por fila, ampliada al doble; estilo HGSS: la
# columna 2 repite la 0
small = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
for row in range(4):
    for col in range(4):
        small.putpixel((col * 32 + row, row * 32 + (0 if col == 2 else col)), RED if row % 2 else BLUE)
sheet = small.resize((256, 256), Image.NEAREST)
frames, kind = fn.frames_of(sheet)
assert kind is fn.SMALL and len(frames) == 8 and all(f.size == (32, 32) for f in frames)
assert frames[0].getpixel((3, 0)) == RED          # primera textura: fila 3 (arriba), columna 0
assert frames[3].getpixel((0, 1)) == BLUE         # cuarta: fila 0 (abajo), columna 1

cycle = Image.new("RGBA", (128, 128), (0, 0, 0, 0))  # ciclo de 4 (Gen 6): el segundo paso es la columna 2
for row in range(4):
    for col in range(4):
        cycle.putpixel((col * 32 + row, row * 32 + col), BLUE)
cframes, _ = fn.frames_of(cycle.resize((256, 256), Image.NEAREST))
assert cframes[3].getpixel((0, 2)) == BLUE and cframes[3].getpixel((0, 1))[3] == 0

big, kind = fn.frames_of(sheet.resize((512, 512), Image.NEAREST))   # cuadros de 128: modelo grande
assert kind is fn.BIG and len(big) == 6 and big[0].size == (64, 64)
small, kind = fn.frames_of(sheet.resize((192, 192), Image.NEAREST)) # cuadros de 48: centrados, pies abajo
assert kind is fn.SMALL and small[0].size == (32, 32)
assert fn.frames_of(Image.new("RGBA", (300, 200))) is None

block = Image.new("RGBA", (2, 2), (0, 0, 0, 0))     # bloque de 2x2: el color que más se repite
for xy in ((0, 0), (1, 0), (0, 1)): block.putpixel(xy, RED)
block.putpixel((1, 1), BLUE)
assert fn.halve(block).getpixel((0, 0)) == RED
thin = Image.new("RGBA", (2, 2), (0, 0, 0, 0)); thin.putpixel((1, 1), BLUE)
assert fn.halve(thin).getpixel((0, 0))[3] == 0      # un solo píxel de cuatro: transparente

pal = fn.palette_of(frames)
assert sorted(pal) == sorted([RED[:3], BLUE[:3]])
tex = fn.encode(frames[:1], pal)
assert len(tex) == 512 and tex[1] == (fn.nearest_index(RED[:3], pal) << 4)   # píxel 3 = byte 1, mitad alta

many = [Image.new("RGBA", (32, 32))]
for i in range(40):
    many[0].putpixel((i % 32, i // 32), (i * 6, 255 - i * 6, 0, 255))
pal = fn.palette_of(many)
seen = {px[:3] for px in many[0].getdata() if px[3]}
assert len(pal) <= 15 and all(c in seen for c in pal)   # 15 como mucho, y todos de la hoja

tpoke = struct.pack("<8H", 1, 2, 0, 0x1000, 3, 0, 0, 0x1001)
assert fn.missing_species(tpoke, 4) == [2, 4]
print("ok follower_new")
