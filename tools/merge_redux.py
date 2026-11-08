"""Junta Volt White 2 Redux con White2Upgrade: los datos y parches de Redux encima de una ROM de White2Upgrade.

Uso:  python tools/merge_redux.py --original W2.nds --redux Redux.nds --base White2Upgrade.nds --salida Mezcla.nds

Las tres ROMs son de W2 USA. Se compara Redux con la original y solo se lleva lo que Redux cambió:
- Archivos que White2Upgrade no toca: el de Redux entero (guiones, objetos, encuentros, textos de la historia...).
- Archivos que tocan los dos: entrada por entrada, Redux donde cambió y White2Upgrade en el resto, con estos ajustes:
  - especies (datos, movimientos por nivel, evoluciones): las formas de la original (685-708) están en otro número en
    White2Upgrade (722 en adelante), y los campos de formas (0x1C-0x20) son los de White2Upgrade, que añade megas;
  - evoluciones: White2Upgrade usa 8 huecos (48 bytes) y añade evoluciones a especies nuevas (Eevee -> Sylveon);
  - textos: línea por línea (nombres y descripciones de movimientos, mensajes "X usó Y");
  - iconos (a/0/0/7): si los dos cambian el mismo, se queda el de White2Upgrade (usa su propio mapa de paletas).
- Código (arm9 y overlays 36, 166 y 167), solo lo que no es del tipo Hada: White2Upgrade pone su propio tipo Hada en
  las mismas direcciones que Redux, y su arranque ya está arreglado. Se lleva el variocolor 1/512, la lista de MT, las
  MO que se pueden olvidar, gráficos de objetos, clases de entrenador, Grutas Ocultas, polvaredas y Recogida.

Movimientos: Redux pone algunos nuevos encima de viejos (Moonblast en Mist Ball...). Se quedan así, aunque
White2Upgrade también tenga Moonblast en otro número (585): las especies de Redux usan el suyo y las de Gen 6 el otro.
"""
import argparse
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rom                              # noqa: E402
import rom_compare as rc                # noqa: E402
from sprites_gen5 import build_narc, crc16, write_file   # noqa: E402

SPECIES = 649                       # especies de la original
FORMS_ORIG = range(685, 709)        # formas en los datos de especie de la original
FORM_FIELDS = slice(0x1C, 0x21)     # personal: primer dato de forma (u16), sprite de forma (u16), nº de formas (u8)
BY_SPECIES = ("a/0/1/6", "a/0/1/8", "a/0/1/9")   # datos, movimientos por nivel, evoluciones (índice de especie/forma)
TEXT_BY_LINE = {16, 402, 403}       # mensajes de movimientos, descripciones y nombres
KEEP_BASE = {"a/0/0/7"}             # iconos
ARM9_FROM = 0x02005000              # antes: arranque (Redux y White2Upgrade lo arreglan cada uno a su manera)
ARM9_SKIP = {0x02093BF0}            # código de Redux para los iconos del tipo Hada (solo lo llama su overlay 255)
OVERLAYS = {36: None, 166: None,    # None = todo lo que cambia; si no, solo esas zonas
            167: [(0x021C7FF2, 1), (0x021DA2F4, 8)]}   # el resto del 167 es el tipo Hada


def text_lines(d: bytes) -> list:
    """Líneas de un archivo de texto de Gen 5 sin descifrar: [(bytes cifrados, campo extra)]."""
    sections, n = struct.unpack_from("<HH", d, 0)
    if sections != 1:
        raise ValueError("texto con varias secciones")
    sec = struct.unpack_from("<I", d, 0x0C)[0]
    out = []
    for i in range(n):
        off, length, extra = struct.unpack_from("<IHH", d, sec + 4 + 8 * i)
        out.append((d[sec + off:sec + off + 2 * length], extra))
    return out


def build_text(lines: list) -> bytes:
    """Archivo de texto con esas líneas (ya cifradas): una sección, como los del juego."""
    table, data = bytearray(), bytearray()
    start = 4 + 8 * len(lines)
    for blob, extra in lines:
        table += struct.pack("<IHH", start + len(data), len(blob) // 2, extra)
        data += blob
    while len(data) % 4:                    # la sección ocupa múltiplos de 4 bytes
        data += b"\0"
    section = struct.pack("<I", 4 + len(table) + len(data)) + table + data
    return struct.pack("<HHIII", 1, len(lines), len(section), 0, 0x10) + section


def merge_lines(o: bytes, r: bytes, b: bytes) -> bytes:
    lo, lr, lb = text_lines(o), text_lines(r), text_lines(b)
    out = list(lb)
    for i in range(min(len(lo), len(lr))):
        if lr[i] != lo[i]:
            if i < len(out):
                out[i] = lr[i]
    return build_text(out)


def form_map(po: list, pb: list) -> dict:
    """Número de cada forma de la original en la base: {685: 722, ...}."""
    out = {}
    for i in range(1, SPECIES + 1):
        so, n = struct.unpack_from("<H", po[i], 0x1C)[0], po[i][0x20]
        sb = struct.unpack_from("<H", pb[i], 0x1C)[0]
        if so:
            for k in range(n - 1):
                out[so + k] = sb + k
    return out


def evolutions(e: bytes) -> list:
    return [struct.unpack_from("<HHH", e, k) for k in range(0, len(e), 6)]


def merge_evolution(r: bytes, b: bytes) -> bytes:
    """Las de Redux, en el formato de la base (más huecos), y las de la base hacia especies nuevas (> 649)."""
    er, eb = evolutions(r), evolutions(b)
    slots = len(eb)
    out = er + [(0, 0, 0)] * (slots - len(er))
    for ev in eb:
        if ev[0] and ev[2] > SPECIES and ev not in out:
            free = next((k for k, x in enumerate(out) if not x[0]), None)
            if free is None:
                raise ValueError(f"sin hueco para la evolución {ev}")
            out[free] = ev
    return b"".join(struct.pack("<HHH", *x) for x in out)


def merge_species(path: str, o: list, r: list, b: list, fmap: dict, log) -> list:
    out = list(b)
    n = 0
    for i in range(min(len(o), len(r))):
        if r[i] == o[i]:
            continue
        j = i if i <= SPECIES else fmap.get(i)
        if j is None:                          # huecos sin usar de la original (650-684)
            continue
        if path == "a/0/1/6":
            e = bytearray(r[i])
            e[FORM_FIELDS] = b[j][FORM_FIELDS]
            out[j] = bytes(e)
        elif path == "a/0/1/9":
            out[j] = merge_evolution(r[i], b[j])
        else:
            out[j] = r[i]
        n += 1
    log(f"{path}: {n} entradas de Redux")
    return out


def merge_narc(path: str, o: list, r: list, b: list, log) -> list:
    out, n, kept = list(b), 0, 0
    for i in range(min(len(o), len(r))):
        if r[i] == o[i]:
            continue
        if path == rom.TEXT and i in TEXT_BY_LINE:
            out[i] = merge_lines(o[i], r[i], b[i])
        elif b[i] != o[i] and path in KEEP_BASE:
            kept += 1
            continue
        else:
            out[i] = r[i]
        n += 1
    extra = r[len(o):]                         # entradas que Redux añade al final (entrenadores nuevos...)
    if extra and b[len(o):len(o) + len(extra)] == extra:   # las mismas (p. ej. la paleta del tipo Hada)
        extra = []
    if extra:
        if len(b) != len(o):
            raise ValueError(f"{path}: Redux y la base añaden entradas distintas")
        out += extra
    log(f"{path}: {n} entradas de Redux" + (f", {len(extra)} nuevas" if extra else "")
        + (f", {kept} se quedan de la base" if kept else ""))
    return out


def patch_code(data: bytearray, base: rom.Rom, orig_path: str, redux_path: str, log) -> None:
    """Las zonas de código de Redux sobre el arm9 y los overlays de la base (sin comprimir en White2Upgrade)."""
    _, _, ram, ao, oo = rc.load(orig_path)
    _, _, _, ar, orr = rc.load(redux_path)
    off, _, bram, size = struct.unpack_from("<IIII", data, 0x20)
    if bram != ram or size != len(ao):
        raise ValueError("el arm9 de la base no está sin comprimir en su sitio")

    def apply(where, file_off, region_ram, a, n, new):
        cur = bytes(data[file_off + a - region_ram:file_off + a - region_ram + n])
        old = new[1]
        if cur != old:
            raise ValueError(f"{where} {a:#x}: la base no tiene ahí lo de la original")
        data[file_off + a - region_ram:file_off + a - region_ram + n] = new[0]

    regs = [(a, n) for a, n in rc.diff_regions(ao, ar, ram) if a >= ARM9_FROM and a not in ARM9_SKIP]
    for a, n in regs:
        apply("arm9", off, ram, a, n, (ar[a - ram:a - ram + n], ao[a - ram:a - ram + n]))
    log(f"arm9: {len(regs)} zonas ({sum(n for _, n in regs)} bytes)")
    ovt, ovt_size = struct.unpack_from("<II", data, 0x50)
    fat = struct.unpack_from("<I", data, 0x48)[0]
    for i in range(0, ovt_size, 32):
        oid, o_ram, o_size, _, _, _, fid, flags = struct.unpack_from("<8I", data, ovt + i)
        if oid not in OVERLAYS:
            continue
        if flags >> 24 & 1:
            raise ValueError(f"overlay {oid} comprimido en la base")
        start = struct.unpack_from("<I", data, fat + 8 * fid)[0]
        r0, _, d0 = oo[oid]
        r1, _, d1 = orr[oid]
        lo, hi = max(r0, r1), min(r0 + len(d0), r1 + len(d1))
        regs = OVERLAYS[oid] or rc.diff_regions(d0[lo - r0:hi - r0], d1[lo - r1:hi - r1], lo)
        for a, n in regs:
            apply(f"ov{oid}", start, o_ram, a, n, (d1[a - r1:a - r1 + n], d0[a - r0:a - r0 + n]))
        log(f"overlay {oid}: {len(regs)} zonas")


def merge(orig_path: str, redux_path: str, base_path: str, out_path: str, log=print) -> None:
    o, r, b = rom.Rom(orig_path), rom.Rom(redux_path), rom.Rom(base_path)
    if not (o.code == r.code == b.code == "IRDO"):
        raise SystemExit("las tres ROMs tienen que ser de W2 USA (IRDO)")
    data = bytearray(b.data)
    fmap = form_map(o.personal(), b.personal())
    whole, merged = [], []
    for path in sorted(o._paths):
        if path not in r._paths or path not in b._paths or r.file(path) == o.file(path):
            continue
        if b.file(path) == o.file(path):
            write_file(data, b, path, r.file(path))
            whole.append(path)
            continue
        fo, fr, fb = o.narc(path), r.narc(path), b.narc(path)
        if path in BY_SPECIES:
            new = merge_species(path, fo, fr, fb, fmap, log)
        else:
            new = merge_narc(path, fo, fr, fb, log)
        if new != fb:
            write_file(data, b, path, build_narc(b.file(path), new))
        merged.append(path)
    log(f"enteros de Redux: {len(whole)} ({', '.join(whole)})")
    patch_code(data, b, orig_path, redux_path, log)
    struct.pack_into("<H", data, 0x15E, crc16(bytes(data[:0x15E])))
    with open(out_path, "wb") as f:
        f.write(data)
    log(f"guardado en {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--original", required=True)
    ap.add_argument("--redux", required=True)
    ap.add_argument("--base", required=True, help="ROM de White2Upgrade (con sprites o sin ellos)")
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    merge(a.original, a.redux, a.base, a.salida)


if __name__ == "__main__":
    main()
