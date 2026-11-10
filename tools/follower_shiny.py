"""Copias variocolor de los modelos de Pokémon que caminan (para el acompañante).

Uso:  python tools/follower_shiny.py --rom Mezcla.nds --hojas <carpeta de hojas>

B2/W2 solo traen la paleta normal de cada modelo (a/0/4/8, NSBTX de 16 colores). Esta herramienta añade, por cada
modelo de Pokémon (los del juego, 0x1000-0x126B, y los de follower_new.py, 0x1300-0x13FF), una copia con la paleta
variocolor y el código + 0x2000 (patches/follower.cpp la usa si el primero del equipo es variocolor y sabe dónde está
gracias a GetIndexOfObjID).

De dónde sale cada color variocolor:
  1. Hojas para caminar estilo HGSS (NNN.png y NNNs.png, NNN_F.png para la forma F; las de PokeAvatars): las dos tienen
     los mismos píxeles, así que cada color normal tiene su pareja variocolor. Cubren casi todo (95 % exactos).
  2. Si el color del modelo no está en la hoja (algunos de Gen 5, dibujados distinto): la paleta normal y la variocolor
     del sprite de combate de la especie (a/0/0/4, archivos 18 y 19).
  3. Si tampoco: se queda igual.
Va al final de la cadena (después de follower_new.py y follower_models.py; las copias heredan su desplazamiento).
"""
import argparse
import os
import struct
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rom                                                    # noqa: E402
from sprites_gen5 import build_narc, lz_decompress, write_file  # noqa: E402

MMODEL_TBL = "a/0/4/7"
MMODEL_GRA = "a/0/4/8"
TPOKE = "a/2/0/8"
SPRITES = "a/0/0/4"
RECORD = 28
OFF_RES1 = 16
POKEMON_FIRST, POKEMON_COUNT = 0x1000, 0x26C   # códigos de Pokémon y su sitio en la tabla (GetIndexOfObjID)
POKEMON_INDEX = 0x179
NEW_FIRST, NEW_SLOTS = 0x1300, 0x100          # modelos de follower_new.py
NEW_INDEX = 0x3F0                             # su sitio en la tabla: justo tras los 1008 del juego
SHINY_OFFSET = 0x2000                         # código variocolor = código normal + esto
SHINY_INDEX = NEW_INDEX + NEW_SLOTS           # las copias, tras los nuevos: primero las del juego y luego las nuevas
NEAR = 12            # distancia máxima (en 5 bits por canal, al cuadrado) para dar un color por el mismo
DEFAULT_SHEETS = os.path.join(os.path.dirname(ROOT), "..", "PokeAvatars", "src", "public", "img", "pokesprites")


# --- colores (BGR555 del DS)
def c555(r: int, g: int, b: int) -> int:
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def rgb(c: int) -> tuple:
    return c & 31, (c >> 5) & 31, (c >> 10) & 31


def dist(a: int, b: int) -> int:
    return sum((x - y) ** 2 for x, y in zip(rgb(a), rgb(b)))


def shift(target: int, src: int, ref: int) -> int:
    """target con la diferencia entre src y ref (para colores casi iguales: conserva el matiz del modelo)."""
    return c555(*(min(31, max(0, t + s - r)) << 3 for t, s, r in zip(rgb(target), rgb(src), rgb(ref))))


def nearest(color: int, pairs: dict):
    best = min(pairs, key=lambda k: dist(color, k), default=None)
    if best is None or dist(color, best) > NEAR:
        return None
    return shift(pairs[best], color, best)


def shiny_palette(palette: list, sheet_pairs: dict, battle_pairs: dict) -> tuple[list, Counter]:
    """La paleta variocolor (el color 0 es el transparente) y de dónde salió cada color."""
    out, why = [palette[0]], Counter()
    for c in palette[1:]:
        for name, pairs in (("hoja", sheet_pairs), ("combate", battle_pairs)):
            new = nearest(c, pairs)
            if new is not None:
                out.append(new)
                why[name] += 1
                break
        else:
            out.append(c)
            why["igual"] += 1
    return out, why


# --- NSBTX: la paleta (una sola, de 16 colores) dentro del bloque TEX0
def tex0_palette(nsbtx: bytes) -> tuple[int, list]:
    t = nsbtx.find(b"TEX0")
    size = struct.unpack_from("<I", nsbtx, t + 0x30)[0] << 3
    pos = t + struct.unpack_from("<I", nsbtx, t + 0x38)[0]
    return pos, [struct.unpack_from("<H", nsbtx, pos + 2 * i)[0] & 0x7FFF for i in range(size // 2)]


def with_palette(nsbtx: bytes, palette: list) -> bytes:
    pos, _ = tex0_palette(nsbtx)
    d = bytearray(nsbtx)
    struct.pack_into(f"<{len(palette)}H", d, pos, *palette)
    return bytes(d)


# --- fuentes de las parejas normal → variocolor
def sheet_pairs(folder: str, species: int, form: int) -> dict:
    from PIL import Image
    names = [(f"{species:03d}_{form}.png", f"{species:03d}s_{form}.png")] if form else []
    names.append((f"{species:03d}.png", f"{species:03d}s.png"))
    for normal, shiny in names:
        a, b = os.path.join(folder, normal), os.path.join(folder, shiny)
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        ia, ib = Image.open(a).convert("RGBA"), Image.open(b).convert("RGBA")
        if ia.size != ib.size:
            continue
        seen = defaultdict(Counter)
        for pa, pb in zip(ia.getdata(), ib.getdata()):
            if pa[3] > 127 and pb[3] > 127:
                seen[c555(*pa[:3])][c555(*pb[:3])] += 1
        return {k: v.most_common(1)[0][0] for k, v in seen.items()}
    return {}


def nclr_colors(d: bytes) -> list:
    if d[:1] in (b"\x10", b"\x11"):
        d = lz_decompress(d)
    pos = d.find(b"TTLP") + 0x18
    return [struct.unpack_from("<H", d, pos + 2 * i)[0] & 0x7FFF for i in range(16)]


def battle_pairs(sprites: list, species: int) -> dict:
    base = species * 20
    if base + 19 >= len(sprites):
        return {}
    normal, shiny = nclr_colors(sprites[base + 18]), nclr_colors(sprites[base + 19])
    return {n: s for n, s in zip(normal[1:], shiny[1:])}


# --- tabla de modelos
def add_shiny(table: bytes, gra: list, tpoke: bytes, sheets: str, sprites: list, log=print) -> tuple[bytes, list]:
    count = struct.unpack_from("<I", table, 0)[0]
    uids = {struct.unpack_from("<H", table, 4 + RECORD * i)[0] for i in range(count)}
    if any(u >= POKEMON_FIRST + SHINY_OFFSET for u in uids if u != 0xFFFF):
        raise ValueError("la ROM ya tiene los modelos variocolor")
    if count != (len(table) - 4) // RECORD or count != SHINY_INDEX:
        raise ValueError(f"tabla de modelos inesperada ({count} registros; follower.cpp espera {SHINY_INDEX}: "
                         "¿falta follower_new.py?)")
    by_code = {}
    for i in range(0, len(tpoke) - 7, 8):
        species, _, form, code = struct.unpack_from("<4H", tpoke, i)
        by_code.setdefault(code, (species, form))
    gra, records, total = list(gra), bytearray(), Counter()
    slots = [(c, POKEMON_INDEX + c - POKEMON_FIRST) for c in range(POKEMON_FIRST, POKEMON_FIRST + POKEMON_COUNT)]
    slots += [(c, NEW_INDEX + c - NEW_FIRST) for c in range(NEW_FIRST, NEW_FIRST + NEW_SLOTS)]
    for code, index in slots:
        rec = bytearray(table[4 + RECORD * index:][:RECORD])
        res = struct.unpack_from("<H", rec, OFF_RES1)[0]
        nsbtx = gra[res]
        if code in by_code:
            species, form = by_code[code]
            _, pal = tex0_palette(nsbtx)
            new_pal, why = shiny_palette(pal, sheet_pairs(sheets, species, form), battle_pairs(sprites, species))
            total.update(why)
            nsbtx = with_palette(nsbtx, new_pal)
        struct.pack_into("<H", rec, 0, code + SHINY_OFFSET)
        struct.pack_into("<H", rec, OFF_RES1, len(gra))
        gra.append(nsbtx)
        records += rec
    new_table = struct.pack("<I", count + len(slots)) + table[4:] + bytes(records)
    log(f"{len(slots)} modelos variocolor (código + {SHINY_OFFSET:#x}); colores: {dict(total)}")
    return new_table, gra


def apply(path: str, sheets: str, log=print) -> None:
    r = rom.Rom(path)
    table, gra = add_shiny(r.narc(MMODEL_TBL)[0], r.narc(MMODEL_GRA), r.narc(TPOKE)[0], sheets, r.narc(SPRITES), log)
    data = bytearray(r.data)
    log("tabla " + write_file(data, r, MMODEL_TBL, build_narc(r.file(MMODEL_TBL), [table])))
    log("texturas " + write_file(data, r, MMODEL_GRA, build_narc(r.file(MMODEL_GRA), gra)))
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
