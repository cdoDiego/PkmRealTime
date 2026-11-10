"""Modelos para caminar de las especies que no tienen (para el acompañante), hechos con hojas estilo HGSS.

Uso:  python tools/follower_new.py --rom Mezcla.nds [--hojas <carpeta de hojas>]

B2/W2 tienen modelo para 620 Pokémon (TPOKE, a/2/0/8). Esta herramienta crea uno para cada especie de 1-721 que no lo
tiene, si su hoja (NNN.png de PokeAvatars: 4 filas abajo/izquierda/derecha/arriba de 4 cuadros de 64x64, dibujo HGSS
ampliado al doble) se puede reducir a 32x32 sin perder nada. Las que son más grandes necesitan un modelo de 64x64 y se
quedan fuera por ahora.

Cada modelo es una copia del de Eevee (8 texturas de 32x32 de 16 colores: espalda, frente, izquierda y derecha, con 2
pasos cada una) con el dibujo de la hoja. Va con el código 0x1300 + n (en la tabla desde la posición 0x3F0, con sitio
para 256: patches/follower.cpp, GetIndexOfObjID) y una entrada nueva en TPOKE (especie, cualquier sexo, forma 0).
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
                            POKEMON_INDEX, NEW_FIRST, NEW_SLOTS, NEW_INDEX)

TEMPLATE_CODE = 0x1086          # Eevee: modelo de 8 texturas (spriteControllerType 14)
TABLE_COUNT = NEW_INDEX         # registros del juego
FRAME = 32
# (fila, columna) de la hoja reducida para cada textura del modelo: arriba, abajo, izquierda, derecha; 2 pasos
FRAMES = [(3, 0), (3, 1), (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
MAX_NOT_DOUBLE = 100            # píxeles de 2x2 que no son iguales: más que esto, la hoja no está ampliada al doble
COLORS = 15


def _pil():
    from PIL import Image
    return Image


def halve(im):
    """La hoja reducida a la mitad (cada bloque de 2x2 a un píxel), o None si no está ampliada al doble."""
    Image = _pil()
    p = im.load()
    best = None
    for ox in (0, 1):
        for oy in (0, 1):
            bad = sum(1 for y in range(oy, im.height - 1, 2) for x in range(ox, im.width - 1, 2)
                      if not (p[x, y] == p[x + 1, y] == p[x, y + 1] == p[x + 1, y + 1]))
            if best is None or bad < best[0]:
                best = (bad, ox, oy)
    if best[0] > MAX_NOT_DOUBLE:
        return None
    _, ox, oy = best
    out = Image.new("RGBA", (im.width // 2, im.height // 2))
    out.paste(im.crop((ox, oy, im.width, im.height)).resize(((im.width - ox) // 2, (im.height - oy) // 2),
                                                           Image.NEAREST))
    return out


def frames_of(sheet) -> list | None:
    """Las 8 imágenes de 32x32 del modelo, o None si la hoja no sirve."""
    if sheet.size != (256, 256):
        return None
    half = halve(sheet.convert("RGBA"))
    if half is None:
        return None
    return [half.crop((c * FRAME, r * FRAME, c * FRAME + FRAME, r * FRAME + FRAME)) for r, c in FRAMES]


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
        raise ValueError("la plantilla no tiene 8 texturas de 32x32")
    d = bytearray(template)
    d[data:data + size] = tex
    colors = [struct.unpack_from("<H", template, pal)[0]] + [c555(*c) for c in palette]
    colors += [0] * (16 - len(colors))
    struct.pack_into("<16H", d, pal, *colors)
    return bytes(d)


def missing_species(tpoke: bytes, last: int = 721) -> list:
    have = {struct.unpack_from("<H", tpoke, i)[0] for i in range(0, len(tpoke) - 7, 8)}
    return [s for s in range(1, last + 1) if s not in have]


def add_models(table: bytes, gra: list, tpoke: bytes, sheets: str, log=print) -> tuple[bytes, list, bytes]:
    Image = _pil()
    count = struct.unpack_from("<I", table, 0)[0]
    if count != TABLE_COUNT or count != (len(table) - 4) // RECORD:
        raise ValueError(f"tabla de modelos inesperada ({count} registros; se esperan {TABLE_COUNT})")
    template_rec = table[4 + RECORD * (POKEMON_INDEX + TEMPLATE_CODE - 0x1000):][:RECORD]
    template = gra[struct.unpack_from("<H", template_rec, OFF_RES1)[0]]
    gra, records, entries, made, skipped = list(gra), bytearray(), bytearray(), [], []
    for species in missing_species(tpoke):
        path = os.path.join(sheets, f"{species:03d}.png")
        frames = frames_of(Image.open(path)) if os.path.exists(path) else None
        if frames is None or len(made) == NEW_SLOTS:
            skipped.append(species)
            continue
        code = NEW_FIRST + len(made)
        rec = bytearray(template_rec)
        struct.pack_into("<H", rec, 0, code)
        struct.pack_into("<H", rec, OFF_RES1, len(gra))
        gra.append(build_nsbtx(template, frames, palette_of(frames)))
        records += rec
        entries += struct.pack("<4H", species, 2, 0, code)
        made.append(species)
    for n in range(len(made), NEW_SLOTS):         # sitio reservado: nadie lo pide, pero la tabla sigue en orden
        rec = bytearray(template_rec)
        struct.pack_into("<H", rec, 0, NEW_FIRST + n)
        records += rec
    log(f"{len(made)} modelos nuevos ({NEW_FIRST:#x}-{NEW_FIRST + len(made) - 1:#x}); sin modelo (hoja grande o "
        f"sin hoja): {len(skipped)}")
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
