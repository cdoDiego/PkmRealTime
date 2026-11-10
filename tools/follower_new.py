"""Modelos para caminar de las especies que no tienen (para el acompañante), hechos con hojas estilo HGSS.

Uso:  python tools/follower_new.py --rom Mezcla.nds [--hojas <carpeta de hojas>]

B2/W2 tienen modelo para 620 Pokémon (TPOKE, a/2/0/8). Esta herramienta crea uno para cada especie de 1-721 que no lo
tiene, con su hoja (NNN.png de PokeAvatars: 4 filas abajo/izquierda/derecha/arriba de 4 cuadros). Las hojas están al
doble del tamaño del juego, así que se reducen a la mitad (en cada bloque de 2x2, el color que más se repite):
  - cuadros de 64x64 (casi todas): modelo normal de 32x32, copia del de Eevee (8 texturas: espalda, frente, izquierda y
    derecha, con 2 pasos);
  - cuadros de 128x128 (legendarios enormes): modelo grande de 64x64, copia de uno grande del juego (6 texturas; la
    derecha es la izquierda reflejada);
  - cuadros más pequeños: se centran en uno de 64x64 (con los pies abajo) y van como los normales.
El segundo paso de cada dirección es la columna 1 de la hoja, o la 2 si la hoja es un ciclo de 4 cuadros (step_column).
Cada uno va con el código 0x1300 + n (en la tabla desde la posición 0x3F0, con sitio para 256: patches/follower.cpp,
GetIndexOfObjID) y una entrada nueva en TPOKE (especie, cualquier sexo, forma 0).
Va antes de follower_models.py y follower_shiny.py (que hace también sus copias variocolor).
"""
import argparse
import os
import struct
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rom                                          # noqa: E402
from sprites_gen5 import build_narc, write_file     # noqa: E402
from follower_shiny import (c555, DEFAULT_SHEETS, MMODEL_TBL, MMODEL_GRA, TPOKE, RECORD, OFF_RES1,  # noqa: E402
                            POKEMON_FIRST, POKEMON_COUNT, POKEMON_INDEX, NEW_FIRST, NEW_SLOTS, NEW_INDEX)

TABLE_COUNT = NEW_INDEX         # registros del juego
OFF_SCENE, OFF_BILLBOARD, OFF_CONTROLLER = 3, 7, 9
SMALL = {"cell": 64, "frame": 32, "billboard": 0, "controller": 14,   # como Eevee
         # (fila, columna) de la hoja reducida para cada textura: arriba, abajo, izquierda, derecha; 2 pasos
         "frames": [(3, 0), (3, 1), (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]}
BIG = {"cell": 128, "frame": 64, "billboard": 2, "controller": 13,    # como Steelix o Lugia
       "frames": [(3, 0), (3, 1), (0, 0), (0, 1), (1, 0), (1, 1)]}
SCENE_GROUND = 10
COLORS = 15


def _pil():
    from PIL import Image
    return Image


def halve(im):
    """La imagen a la mitad: cada bloque de 2x2 da el color que más se repite (transparente si lo son 2 o más)."""
    Image = _pil()
    p = im.load()
    out = Image.new("RGBA", (im.width // 2, im.height // 2), (0, 0, 0, 0))
    q = out.load()
    for y in range(out.height):
        for x in range(out.width):
            block = [p[2 * x + dx, 2 * y + dy] for dy in (0, 1) for dx in (0, 1)]
            solid = [c for c in block if c[3] > 127]
            if len(solid) >= 3 or (len(solid) == 2 and block[0][3] > 127):
                q[x, y] = Counter(solid).most_common(1)[0][0]
    return out


def frames_of(sheet) -> tuple[list, dict] | None:
    """Las texturas del modelo y su tipo (SMALL o BIG), o None si la hoja no sirve."""
    Image = _pil()
    sheet = sheet.convert("RGBA")
    cell = sheet.width // 4
    if sheet.width != sheet.height or sheet.width % 4:
        return None
    kind = BIG if cell == BIG["cell"] else SMALL
    if cell < SMALL["cell"]:                       # se centra en cuadros de 64x64, con los pies abajo
        padded = Image.new("RGBA", (4 * SMALL["cell"], 4 * SMALL["cell"]), (0, 0, 0, 0))
        off = ((SMALL["cell"] - cell) // 2, SMALL["cell"] - cell)
        for r in range(4):
            for c in range(4):
                padded.paste(sheet.crop((c * cell, r * cell, c * cell + cell, r * cell + cell)),
                             (c * SMALL["cell"] + off[0], r * SMALL["cell"] + off[1]))
        sheet = padded
    elif cell not in (SMALL["cell"], BIG["cell"]):
        return None
    half, f = halve(sheet), kind["frame"]
    cell_of = lambda r, c: half.crop((c * f, r * f, c * f + f, r * f + f))   # noqa: E731
    return [cell_of(r, step_column(cell_of, r) if c == 1 else c) for r, c in kind["frames"]], kind


def step_column(cell_of, row: int) -> int:
    """El cuadro del segundo paso de una fila. Las hojas estilo HGSS repiten el primero en la columna 2 (quieto, paso,
    quieto, el otro paso): el paso es la 1. Las de Gen 6 (Xerneas, Yveltal...) son un ciclo de 4 donde la 1 apenas
    cambia (Yveltal de frente: igual que la 0): el paso contrario es la 2."""
    return 1 if cell_of(row, 0).tobytes() == cell_of(row, 2).tobytes() else 2


def palette_of(frames) -> list:
    """Hasta 15 colores (RGB) que son de la hoja: los que hay o, si son más, el más usado de cada grupo."""
    Image = _pil()
    count = Counter(px[:3] for f in frames for px in f.getdata() if px[3] > 127)
    if len(count) <= COLORS:
        return [c for c, _ in count.most_common()]
    colors = list(count)
    strip = Image.new("RGB", (len(colors), 1))
    strip.putdata(colors)
    groups = strip.quantize(COLORS, method=Image.Quantize.MEDIANCUT).getdata()
    best = {}
    for color, g in zip(colors, groups):
        if g not in best or count[color] > count[best[g]]:
            best[g] = color
    return list(best.values())


def nearest_index(color, palette) -> int:
    return 1 + min(range(len(palette)), key=lambda i: sum((a - b) ** 2 for a, b in zip(color, palette[i])))


def encode(frames, palette) -> bytes:
    """Texturas de 4 bits (dos píxeles por byte, el de la izquierda abajo), una tras otra; 0 = transparente."""
    out = bytearray()
    cache = {}
    for f in frames:
        idx = []
        for px in f.getdata():
            if px[3] <= 127:
                idx.append(0)
            else:
                if px[:3] not in cache:
                    cache[px[:3]] = nearest_index(px[:3], palette)
                idx.append(cache[px[:3]])
        out += bytes(idx[i] | (idx[i + 1] << 4) for i in range(0, len(idx), 2))
    return bytes(out)


def build_nsbtx(template: bytes, frames, palette) -> bytes:
    t = template.find(b"TEX0")
    data = t + struct.unpack_from("<I", template, t + 0x14)[0]
    size = struct.unpack_from("<H", template, t + 0x0C)[0] << 3
    pal = t + struct.unpack_from("<I", template, t + 0x38)[0]
    tex = encode(frames, palette)
    if len(tex) != size:
        raise ValueError("la plantilla no tiene las texturas que se esperan")
    d = bytearray(template)
    d[data:data + size] = tex
    colors = [struct.unpack_from("<H", template, pal)[0]] + [c555(*c) for c in palette]
    colors += [0] * (16 - len(colors))
    struct.pack_into("<16H", d, pal, *colors)
    return bytes(d)


def missing_species(tpoke: bytes, last: int = 721) -> list:
    have = {struct.unpack_from("<H", tpoke, i)[0] for i in range(0, len(tpoke) - 7, 8)}
    return [s for s in range(1, last + 1) if s not in have]


def template(table: bytes, gra: list, kind: dict) -> tuple[bytes, bytes]:
    """Registro y NSBTX de un modelo de Pokémon del juego del tipo pedido (en el suelo, del tamaño y control dados)."""
    for code in range(POKEMON_FIRST, POKEMON_FIRST + POKEMON_COUNT):
        rec = table[4 + RECORD * (POKEMON_INDEX + code - POKEMON_FIRST):][:RECORD]
        kind_of = (rec[OFF_SCENE], rec[OFF_BILLBOARD], rec[OFF_CONTROLLER])
        if kind_of == (SCENE_GROUND, kind["billboard"], kind["controller"]):
            return rec, gra[struct.unpack_from("<H", rec, OFF_RES1)[0]]
    raise ValueError(f"no hay un modelo del juego que sirva de plantilla ({kind['frame']}x{kind['frame']})")


def add_models(table: bytes, gra: list, tpoke: bytes, sheets: str, log=print) -> tuple[bytes, list, bytes]:
    Image = _pil()
    count = struct.unpack_from("<I", table, 0)[0]
    if count != TABLE_COUNT or count != (len(table) - 4) // RECORD:
        raise ValueError(f"tabla de modelos inesperada ({count} registros; se esperan {TABLE_COUNT})")
    templates = {id(k): template(table, gra, k) for k in (SMALL, BIG)}
    gra, records, entries, made, big, skipped = list(gra), bytearray(), bytearray(), [], [], []
    for species in missing_species(tpoke):
        path = os.path.join(sheets, f"{species:03d}.png")
        got = frames_of(Image.open(path)) if os.path.exists(path) else None
        if got is None or len(made) == NEW_SLOTS:
            skipped.append(species)
            continue
        frames, kind = got
        rec_tpl, nsbtx_tpl = templates[id(kind)]
        code = NEW_FIRST + len(made)
        rec = bytearray(rec_tpl)
        struct.pack_into("<H", rec, 0, code)
        struct.pack_into("<H", rec, OFF_RES1, len(gra))
        gra.append(build_nsbtx(nsbtx_tpl, frames, palette_of(frames)))
        records += rec
        entries += struct.pack("<4H", species, 2, 0, code)
        made.append(species)
        if kind is BIG:
            big.append(species)
    for n in range(len(made), NEW_SLOTS):         # sitio reservado: nadie lo pide, pero la tabla sigue en orden
        rec = bytearray(templates[id(SMALL)][0])
        struct.pack_into("<H", rec, 0, NEW_FIRST + n)
        records += rec
    log(f"{len(made)} modelos nuevos ({NEW_FIRST:#x}-{NEW_FIRST + len(made) - 1:#x}), {len(big)} grandes {big}; "
        f"sin modelo: {skipped}")
    return struct.pack("<I", count + NEW_SLOTS) + table[4:] + bytes(records), gra, tpoke + bytes(entries)


def apply(path: str, sheets: str, log=print) -> None:
    r = rom.Rom(path)
    table, gra, tpoke = add_models(r.narc(MMODEL_TBL)[0], r.narc(MMODEL_GRA), r.narc(TPOKE)[0], sheets, log)
    data = bytearray(r.data)
    log("tabla " + write_file(data, r, MMODEL_TBL, build_narc(r.file(MMODEL_TBL), [table])))
    log("texturas " + write_file(data, r, MMODEL_GRA, build_narc(r.file(MMODEL_GRA), gra)))
    log("TPOKE " + write_file(data, r, TPOKE, build_narc(r.file(TPOKE), [tpoke])))
    with open(path, "wb") as f:
        f.write(data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", required=True)
    ap.add_argument("--hojas", default=os.path.normpath(DEFAULT_SHEETS))
    a = ap.parse_args()
    if not os.path.isdir(a.hojas):
        sys.exit(f"no encuentro las hojas: {a.hojas}")
    apply(a.rom, a.hojas)


if __name__ == "__main__":
    main()
