"""Sprites estilo Gen 5 (de Pokémon Showdown) en la ROM de B2/W2, fijos o animados (EXPERIMENTAL).

Necesita Pillow (solo esta herramienta):  pip install pillow

  python tools/sprites_gen5.py descargar sylveon
      baja a sprites_showdown/ los GIF animados (gen5ani: frente, espalda y variocolor) y los PNG fijos (gen5)
  python tools/sprites_gen5.py convertir --rom W2.nds --salida prueba.nds --especie 25 --nombre sylveon
      pone el sprite de Sylveon en lugar del de la especie 25 (Pikachu); --fijo usa solo los PNG
      --bloque auto|8|16: tamaño de las piezas (auto: 16 si conserva al menos la mitad de los fotogramas; menos cortes)
  python tools/sprites_gen5.py lote --rom White2Upgrade.nds --salida gen6.nds --desde 650 --hasta 721
      todas las especies del rango, con el nombre que tienen en la ROM; baja lo que falte y escribe la ROM una vez
      (sin GIF animado quedan fijas; sin PNG en Showdown se saltan)

Cómo funciona (validado en el juego el 06-nov, ver DOCUMENTACION.md "Sprites de especies nuevas"):
- El combate dibuja cada sprite (MCSS, src/system/mcss.c de la decomp) con rectángulos de una textura de 256x128 a 4
  bits (archivos 2 y 11 de los 20 de cada especie en a/0/0/4). Cada nodo de la multi-celda (NMCR) tiene su animación
  de celdas (NANR), y cada celda es un rectángulo de esa textura (archivo bin, 8 y 17).
- Los GIF de Showdown son fotograma a fotograma: se cortan en cuadritos de 8x8, los únicos van a la textura (máx. 512)
  y cada posición de la rejilla es un nodo que en cada fotograma muestra su cuadrito. Si no caben, se quitan fotogramas.
- Frente y espalda comparten una paleta de 15 colores + transparente (18 y 19: normal y variocolor).
- Los pies quedan en el punto de apoyo del sprite, como en los originales.
- Si el archivo de sprites ya no cabe en su sitio, va al final de la ROM y la zona DSi de la cabecera (0x90/0x92) se lleva
  al final: melonDS (BizHawk) bloquea la zona DSi de las tarjetas DSi en modo DS. La ROM resultante ya no sirve en modo DSi.
"""
import argparse
import os
import struct
import sys
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import rom

SPRITES = "a/0/0/4"            # 20 archivos por especie
FILES_PER_SPECIES = 20
TILES_MAX = 512                # cuadritos de 8x8 en la textura de 256x128 (con --bloque 16: 128 de 16x16)
FX = 4096                      # fx32: 1.0
# x de cada pieza = 1/4096 de píxel (invisible). En los originales el byte bajo siempre es 0: el parche de White2Upgrade
# tools/w2u_build/patches/mcss_depth.cpp reconoce así las piezas convertidas y no las va mandando al fondo (cortes)
PIECE_MARK = 0x01
CACHE = os.path.join(ROOT, "sprites_showdown")
SHOWDOWN = "https://play.pokemonshowdown.com/sprites/"
VIEWS = {  # vista: (carpeta de GIF animado, carpeta de PNG fijo)
    "frente": ("gen5ani", "gen5"), "frente_shiny": ("gen5ani-shiny", "gen5-shiny"),
    "espalda": ("gen5ani-back", "gen5-back"), "espalda_shiny": ("gen5ani-back-shiny", "gen5-back-shiny"),
}
# 96x96 de los archivos 0 y 9 (pantallas 2D): cuadros de 8x8 en el orden de 4 piezas OAM (64x64, 32x64, 64x32, 32x32)
OAM_BLOCKS = [(0, 0, 8, 8), (8, 0, 4, 8), (0, 8, 8, 4), (8, 8, 4, 4)]


# --- compresión LZ (formatos 0x10 y 0x11 del descompresor del juego)
def lz_decompress(d: bytes) -> bytes:
    if d[0] not in (0x10, 0x11):
        raise ValueError("no es LZ10/LZ11")
    size, pos = int.from_bytes(d[1:4], "little"), 4
    if size == 0:
        size, pos = int.from_bytes(d[4:8], "little"), 8
    lz11, out = d[0] == 0x11, bytearray()
    while len(out) < size:
        flags = d[pos]; pos += 1
        for b in range(8):
            if len(out) >= size:
                break
            if not flags & (0x80 >> b):
                out.append(d[pos]); pos += 1
                continue
            if lz11:
                t = d[pos] >> 4
                if t == 0:
                    n = (((d[pos] & 0xF) << 4) | (d[pos + 1] >> 4)) + 0x11
                    disp = (((d[pos + 1] & 0xF) << 8) | d[pos + 2]) + 1; pos += 3
                elif t == 1:
                    n = (((d[pos] & 0xF) << 12) | (d[pos + 1] << 4) | (d[pos + 2] >> 4)) + 0x111
                    disp = (((d[pos + 2] & 0xF) << 8) | d[pos + 3]) + 1; pos += 4
                else:
                    n, disp = t + 1, (((d[pos] & 0xF) << 8) | d[pos + 1]) + 1; pos += 2
            else:
                n, disp = (d[pos] >> 4) + 3, (((d[pos] & 0xF) << 8) | d[pos + 1]) + 1; pos += 2
            for _ in range(n):
                out.append(out[-disp])
    return bytes(out)


def lz11(data: bytes) -> bytes:
    """Compresión LZ11 (copias cortas, medianas y largas); da casi el mismo tamaño que los archivos del juego."""
    out = bytearray([0x11]) + len(data).to_bytes(3, "little")
    i, n = 0, len(data)
    while i < n:
        flag_pos = len(out); out.append(0); flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len, best_disp = 0, 0
            lim = min(0x10110, n - i)
            for disp in range(1, min(i, 0x1000) + 1):
                if data[i - disp] != data[i]:
                    continue
                l = 0
                while l < lim and data[i + l - disp] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len, best_disp = l, disp
                    if l == lim:
                        break
            if best_len < 3:
                out.append(data[i]); i += 1
                continue
            flags |= 0x80 >> bit
            d = best_disp - 1
            if best_len <= 16:
                out += bytes([((best_len - 1) << 4) | (d >> 8), d & 0xFF])
            elif best_len <= 0x110:
                l = best_len - 0x11
                out += bytes([l >> 4, ((l & 0xF) << 4) | (d >> 8), d & 0xFF])
            else:
                l = best_len - 0x111
                out += bytes([0x10 | (l >> 12), (l >> 4) & 0xFF, ((l & 0xF) << 4) | (d >> 8), d & 0xFF])
            i += best_len
        out[flag_pos] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)


# --- gráficos: NCGR (píxeles), NCLR (paleta)
def ncgr_pixels(d: bytes) -> bytes:
    if d[0] in (0x10, 0x11):
        d = lz_decompress(d)
    size = struct.unpack_from("<I", d, 0x28)[0]
    off = 0x18 + struct.unpack_from("<I", d, 0x2C)[0]       # relativo a los datos del bloque CHAR
    return d[off:off + size]


def ncgr_replace(template: bytes, pix4: list) -> bytes:
    """El mismo encabezado que el original de la ROM, con los píxeles nuevos (4 bits); comprimido si el original lo está."""
    d = lz_decompress(template) if template[0] in (0x10, 0x11) else template
    size = struct.unpack_from("<I", d, 0x28)[0]
    off = 0x18 + struct.unpack_from("<I", d, 0x2C)[0]
    assert len(pix4) == size * 2, (len(pix4), size * 2)
    raw = bytes(pix4[i] | pix4[i + 1] << 4 for i in range(0, len(pix4), 2))
    new = d[:off] + raw + d[off + size:]
    return lz11(new) if template[0] in (0x10, 0x11) else new


def bgr555(c) -> int:
    return (c[0] >> 3) | (c[1] >> 3) << 5 | (c[2] >> 3) << 10


def nclr_replace(template: bytes, palette) -> bytes:
    d = bytearray(template)
    pos = d.find(b"TTLP") + 0x18
    for i in range(16):
        struct.pack_into("<H", d, pos + 2 * i, bgr555(palette[i]) if i < len(palette) else 0)
    return bytes(d)


def tiled96(idx: list) -> list:
    out = []
    for bx, by, bw, bh in OAM_BLOCKS:
        for ty in range(bh):
            for tx in range(bw):
                for q in range(64):
                    out.append(idx[((by + ty) * 8 + q // 8) * 96 + (bx + tx) * 8 + q % 8])
    return out


def c5(c):
    return (c[0] >> 3 << 3, c[1] >> 3 << 3, c[2] >> 3 << 3)   # lo que el DS puede mostrar (5 bits por canal)


# --- fotogramas
def _pil():
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("falta Pillow:  pip install pillow")
    return Image


def load_frames(path: str) -> list:
    """[(imagen RGBA, ms)] de un GIF (o un PNG: un solo fotograma)."""
    Image = _pil()
    im, frames = Image.open(path), []
    try:
        while True:
            frames.append((im.convert("RGBA").copy(), im.info.get("duration", 100) or 100))
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    return frames


def find_offset(frames, static_png):
    """Dónde va el GIF dentro del lienzo de 96x96 del PNG fijo: la posición con más píxeles iguales al primer fotograma."""
    st = _pil().open(static_png).convert("RGBA").load()
    f0 = frames[0][0]
    w, h = f0.size
    fp = f0.load()
    opaque = [(x, y) for y in range(h) for x in range(w) if fp[x, y][3]][::5]
    best = (-1, 0, 0)
    for oy in range(-10, 97 - h + 10):
        for ox in range(-10, 97 - w + 10):
            m = sum(1 for x, y in opaque if 0 <= x + ox < 96 and 0 <= y + oy < 96 and st[x + ox, y + oy][3]
                    and st[x + ox, y + oy][:3] == fp[x, y][:3])
            if m > best[0]:
                best = (m, ox, oy)
    ratio = best[0] / max(1, len(opaque))
    if ratio >= 0.5:
        return ratio, best[1], best[2]
    # El GIF no se parece al fijo (otra pose, p. ej. Greninja): si ya es de 96x96 va tal cual; si no, centrado en
    # horizontal y con los pies a la altura de los del fijo.
    if (w, h) == (96, 96):
        return ratio, 0, 0
    st_feet = max((y for y in range(96) for x in range(96) if st[x, y][3]), default=80)
    gif_feet = max(y for x, y in opaque) if opaque else h - 1
    return ratio, (96 - w) // 2, st_feet - gif_feet


def on_canvas(frames, ox, oy):
    Image = _pil()
    out = []
    for im, ms in frames:
        c = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        c.paste(im, (ox, oy), im)
        out.append((list(c.getdata()), ms))
    return out


def palettes(normal_frames, shiny_frames):
    """Una paleta (15 + transparente) para todos los fotogramas de frente y espalda: si hay más colores, se juntan los dos
    más parecidos. La variocolor tiene los mismos índices: el color que ocupa el lugar de cada uno en los variocolor."""
    count = Counter(c5(p) for px, _ in normal_frames for p in px if p[3])
    merge = {c: c for c in count}
    live = dict(count)
    while len(live) > 15:
        cs = list(live)
        a, b = min(((x, y) for i, x in enumerate(cs) for y in cs[i + 1:]), key=lambda xy: sum((p - q) ** 2 for p, q in zip(*xy)))
        keep, drop = (a, b) if live[a] >= live[b] else (b, a)
        live[keep] += live.pop(drop)
        for k, v in merge.items():
            if v == drop:
                merge[k] = keep
    colors = sorted(live, key=lambda c: -live[c])
    votes = {c: Counter() for c in colors}
    for (pa, _), (pb, _) in zip(normal_frames, shiny_frames):
        for a, b in zip(pa, pb):
            if a[3] and b[3]:
                votes[merge[c5(a)]][c5(b)] += 1
    normal = [(0, 0, 0)] + colors
    rare = [(0, 0, 0)] + [votes[c].most_common(1)[0][0] if votes[c] else c for c in colors]
    look = {c: i + 1 for i, c in enumerate(colors)}
    return normal, rare, (lambda px: [look[merge[c5(p)]] if p[3] else 0 for p in px]), len(count)


def ds_durations(ms_list):
    """Duraciones en fotogramas del DS (60/s), redondeando el tiempo acumulado para que no se desfase."""
    out, acc, prev = [], 0, 0
    for ms in ms_list:
        acc += ms
        out.append(max(1, round(acc * 60 / 1000) - prev)); prev += out[-1]
    return out


def capacity(block: int = 8) -> int:
    return (256 // block) * (128 // block)


def tile_grid(frames_idx, block: int = 8):
    """Cuadritos únicos (0 = vacío) y, por cada posición de la rejilla con dibujo, qué cuadrito tiene en cada fotograma."""
    tiles, grid = {bytes(block * block): 0}, {}
    n = 96 // block
    for f, px in enumerate(frames_idx):
        for gy in range(n):
            for gx in range(n):
                t = bytes(px[(gy * block + y) * 96 + gx * block + x] for y in range(block) for x in range(block))
                if t not in tiles:
                    tiles[t] = len(tiles)
                grid.setdefault((gx, gy), [0] * len(frames_idx))[f] = tiles[t]
    nodes = [(pos, seq) for pos, seq in sorted(grid.items(), key=lambda kv: (kv[0][1], kv[0][0])) if any(seq)]
    return tiles, nodes


def fit_frames(frames_idx, durs, block: int = 8):
    """Junta fotogramas iguales seguidos y, si los cuadritos no caben en la textura, usa uno de cada 2, 3..."""
    merged = []
    for px, d in zip(frames_idx, durs):
        if merged and merged[-1][0] == px:
            merged[-1][1] += d
        else:
            merged.append([px, d])
    frames_idx, durs = [m[0] for m in merged], [m[1] for m in merged]
    step = 1
    while True:
        sub = list(range(0, len(frames_idx), step))
        f2, d2 = [frames_idx[i] for i in sub], [sum(durs[i:i + step]) for i in sub]
        tiles, nodes = tile_grid(f2, block)
        if len(tiles) <= capacity(block):
            return f2, d2, tiles, nodes, step
        step += 1


def texture(tiles, block: int = 8) -> list:
    px = [0] * (256 * 128)
    per_row = 256 // block
    for t, i in tiles.items():
        tx, ty = (i % per_row) * block, (i // per_row) * block
        for y in range(block):
            px[(ty + y) * 256 + tx:(ty + y) * 256 + tx + block] = list(t[y * block:(y + 1) * block])
    return px


# --- formatos de animación de NitroSDK (cabecera de 16 bytes + bloques, como en la ROM)
def _nitro(magic, blocks):
    body = b"".join(blocks)
    return magic + struct.pack("<HHIHH", 0xFEFF, 0x0100, 16 + len(body), 16, len(blocks)) + body


def _block(magic, data):
    data = bytes(data)
    while len(data) % 4:
        data += b"\0"
    return magic + struct.pack("<I", 8 + len(data)) + data


def _labels():
    return _block(b"LBAL", struct.pack("<I", 0) + b"CellAnime0\0")


def _uext():
    return _block(b"TXEU", struct.pack("<I", 0))


def _anim(kind, sequences):
    """KNBA de NANR (kind 1) o NMAR (kind 2): secuencias [(duración, índice)], elemento solo índice, en bucle."""
    elems, elem_off, frames, seqs = bytearray(), {}, bytearray(), bytearray()
    for seq in sequences:
        first = len(frames)
        for dur, idx in seq:
            if idx not in elem_off:
                elem_off[idx] = len(elems); elems += struct.pack("<HH", idx, 0xCCCC)
            frames += struct.pack("<IHH", elem_off[idx], dur, 0xBEEF)
        seqs += struct.pack("<HHHHII", len(seq), 0, 0, kind, 2, first)
    off_fr = 0x18 + len(seqs)
    head = struct.pack("<HHIIIII", len(sequences), sum(len(s) for s in sequences), 0x18, off_fr, off_fr + len(frames), 0, 0)
    return _block(b"KNBA", head + seqs + frames + elems)


def make_nanr(sequences) -> bytes:
    return lz11(_nitro(b"RNAN", [_anim(1, sequences), _labels(), _uext()]))


def make_nmar(total) -> bytes:
    """La multi-celda dura el ciclo entero: si dura menos, al repetirse reinicia los nodos y el sprite queda quieto."""
    return _nitro(b"RAMN", [_anim(2, [[(total, 0)]]), _labels()])


def make_nmcr(nodes_xy) -> bytes:
    """Una multi-celda con un nodo por posición: (secuencia k, x, y, atributo 0x20 | k << 8)."""
    hier = b"".join(struct.pack("<HhhH", k, x, y, 0x20 | (k << 8)) for k, (x, y) in enumerate(nodes_xy))
    mc = struct.pack("<HHI", len(nodes_xy), len(nodes_xy), 0)
    head = struct.pack("<HHIIII", 1, 0xBEEF, 0x14, 0x14 + len(mc), 0, 0)
    return _nitro(b"RCMN", [_block(b"KBCM", head + mc + hier)])


def make_ncer(n) -> bytes:
    """Celdas de 8x8 (una pieza cada una): MCSS dibuja con el archivo bin, pero la animación necesita las celdas."""
    cells, oams = bytearray(), bytearray()
    for i in range(n):
        cells += struct.pack("<HHI", 1, 0, len(oams))
        oams += struct.pack("<HHH", 0, 0, (i * 2) & 0x3FF)
    head = struct.pack("<HHIIIII", n, 0, 0x18, 1, 0, 0, 0)
    return _nitro(b"RECN", [_block(b"KBEC", head + cells + oams), _labels(), _uext()])


def make_bin(n, frames_idx, block: int = 8) -> bytes:
    """Archivo bin de MCSS: tamaño y desplazamiento del dibujo (como los originales: +7 y casi centrado) y un rectángulo
    de 8x8 de la textura por celda."""
    xs = [i % 96 for px in frames_idx for i, v in enumerate(px) if v]
    ys = [i // 96 for px in frames_idx for i, v in enumerate(px) if v]
    w, h = max(xs) - min(xs) + 8, max(ys) - min(ys) + 8
    ox, oy = round((min(xs) + max(xs)) / 2 - 48 + 2), round(1.5 - ((min(ys) + max(ys)) / 2 - 48))
    out = struct.pack("<IHHhh", n, w, h, ox, oy)
    for i in range(n):
        s, t = (i % (256 // block)) * block, (i // (256 // block)) * block
        out += struct.pack("<6i", PIECE_MARK, 0, block * FX, block * FX, s * FX, t * FX) + bytes(24)
    return out + bytes(4)            # cola: sin nodos "idle"


def side_files(templates, frames_idx, durs, block=8):
    """Los 9 archivos de una vista (frente o espalda) a partir de sus fotogramas ya en índices de paleta.
    block: tamaño de cada pieza. Con 8 caben todos los fotogramas, pero salen 50-70 piezas por sprite; el juego dibuja cada
    una 1 píxel más al fondo (mcss.c) y, cuando la cámara se acerca (captura, algunos ataques), se ven cortes. Con 16 son
    ~20 piezas, como los originales, a cambio de usar menos fotogramas. "auto": 16 si así se conserva al menos la mitad
    de los fotogramas (como Greninja); si no, 8 con todos."""
    if block == "auto":
        f16 = fit_frames(frames_idx, durs, 16)
        block = 16 if f16[4] <= 2 else 8
        frames_idx, durs, tiles, nodes, step = f16 if block == 16 else fit_frames(frames_idx, durs, 8)
    else:
        frames_idx, durs, tiles, nodes, step = fit_frames(frames_idx, durs, block)
    feet = max(i // 96 for px in frames_idx for i, v in enumerate(px) if v)       # fila de los pies = punto de apoyo
    sequences = []
    for _, seq in nodes:
        s = []
        for idx, d in zip(seq, durs):
            if s and s[-1][1] == idx:
                s[-1] = (s[-1][0] + d, idx)
            else:
                s.append((d, idx))
        sequences.append(s)
    nodes_xy = [(gx * block - 48, gy * block - (feet + 1)) for (gx, gy), _ in nodes]
    files = [ncgr_replace(templates[0], tiled96(frames_idx[0])), b"", ncgr_replace(templates[2], texture(tiles, block)), b"",
             make_ncer(len(tiles)), make_nanr(sequences), make_nmcr(nodes_xy), make_nmar(sum(durs)),
             make_bin(len(tiles), frames_idx, block)]
    info = {"frames": len(frames_idx), "step": step, "tiles": len(tiles), "nodes": len(nodes), "ticks": sum(durs),
            "block": block}
    return files, info


# --- NARC y ROM
def build_narc(original: bytes, files: list) -> bytes:
    """El NARC con otros archivos (mismo índice de nombres que el original)."""
    pos = struct.unpack_from("<H", original, 0x0C)[0]
    btaf_size = struct.unpack_from("<I", original, pos + 4)[0]
    btnf = original[pos + btaf_size:pos + btaf_size + struct.unpack_from("<I", original, pos + btaf_size + 4)[0]]
    gmif, fat = bytearray(), bytearray()
    for f in files:
        start = len(gmif); gmif += f; fat += struct.pack("<II", start, len(gmif))
        while len(gmif) % 4:
            gmif.append(0xFF)
    body = b"BTAF" + struct.pack("<IHH", 12 + len(fat), len(files), 0) + fat + btnf \
        + b"GMIF" + struct.pack("<I", 8 + len(gmif)) + gmif
    return original[:8] + struct.pack("<I", 0x10 + len(body)) + original[12:16] + body


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def write_file(data: bytearray, r: "rom.Rom", path: str, content: bytes) -> str:
    """Cambia un archivo de la ROM: en su sitio si cabe; si no, al final, con la zona DSi llevada al final (0x90/0x92)."""
    fat = struct.unpack_from("<I", data, 0x48)[0]
    fid = r._paths[path]
    start, end = struct.unpack_from("<II", data, fat + 8 * fid)
    if len(content) <= end - start:
        data[start:end] = content + bytes([0xFF]) * (end - start - len(content))
        struct.pack_into("<II", data, fat + 8 * fid, start, start + len(content))
        return f"en su sitio ({start:#x})"
    nfiles = struct.unpack_from("<I", data, 0x4C)[0] // 8
    used = max(struct.unpack_from("<I", data, fat + 8 * i + 4)[0] for i in range(nfiles))
    used = max(used, struct.unpack_from("<I", data, 0x80)[0], struct.unpack_from("<I", data, 0x210)[0])
    new = (used + 0x1FF) & ~0x1FF
    capacity = 0x20000 << data[0x14]                         # tamaño del cartucho según la cabecera (512 MB en B2/W2)
    if new + len(content) > capacity:
        raise ValueError("no cabe en la ROM")
    if new + len(content) > len(data):                       # ROM recortada (p. ej. la que genera ndstool): se rellena
        data.extend(b"\xff" * (capacity - len(data)))
    data[new:new + len(content)] = content
    struct.pack_into("<II", data, fat + 8 * fid, new, new + len(content))
    units = len(data) // 0x80000
    struct.pack_into("<HH", data, 0x90, units, units)       # fin de la zona DS / inicio de la DSi: al final de la ROM
    struct.pack_into("<H", data, 0x15E, crc16(bytes(data[:0x15E])))
    return f"al final ({new:#x}); zona DSi movida al final de la ROM"


def _species_files(files, base, folder, name, static, log, block):
    """Los 20 archivos nuevos de una especie (sobre los suyos de la ROM) y la información de cada vista."""
    views = {}
    for side, (front, shiny) in ((0, ("frente", "frente_shiny")), (9, ("espalda", "espalda_shiny"))):
        png, png_s = (os.path.join(folder, f"{VIEWS[v][1]}_{name}.png") for v in (front, shiny))
        gif, gif_s = (os.path.join(folder, f"{VIEWS[v][0]}_{name}.gif") for v in (front, shiny))
        if not static and os.path.exists(gif) and os.path.exists(gif_s):
            gn, gs = load_frames(gif), load_frames(gif_s)
            a, b = find_offset(gn, png), find_offset(gs, png_s)
            ratio, ox, oy = max(a, b)          # los dos GIF comparten lienzo: la mejor posición vale para los dos
            views[side] = (on_canvas(gn, ox, oy), on_canvas(gs, ox, oy))
            log(f"{front}: animado, {len(gn)} fotogramas, en ({ox},{oy}) del lienzo ({ratio:.0%} igual al fijo)")
        else:
            views[side] = (on_canvas(load_frames(png), 0, 0), on_canvas(load_frames(png_s), 0, 0))
            log(f"{front}: fijo")
    normal, rare, to_idx, ncolors = palettes(views[0][0] + views[9][0], views[0][1] + views[9][1])
    log(f"colores: {ncolors} -> {len(normal) - 1}")
    new, info = list(files[base:base + FILES_PER_SPECIES]), {}
    for side, (frames, _) in views.items():
        new[side:side + 9], info[side] = side_files(files[base + side:base + side + 9], [to_idx(px) for px, _ in frames],
                                                    ds_durations([ms for _, ms in frames]), block)
        i = info[side]
        log(f"  {'frente' if side == 0 else 'espalda'}: {i['frames']} fotogramas"
            + (f" (uno de cada {i['step']})" if i["step"] > 1 else "")
            + f", {i['tiles']}/{capacity(i['block'])} bloques de {i['block']}x{i['block']}, {i['nodes']} piezas, ciclo de {i['ticks']} fotogramas del DS")
    new[18] = nclr_replace(files[base + 18], normal)
    new[19] = nclr_replace(files[base + 19], rare)
    return new, info


def missing(folder: str, name: str) -> list:
    """Los PNG fijos que faltan (sin ellos no se puede convertir la especie)."""
    pngs = [f"{VIEWS[v][1]}_{name}.png" for v in VIEWS]
    return [p for p in pngs if not os.path.exists(os.path.join(folder, p))]


def convert_many(rom_path: str, out_path: str, pairs, folder: str, static: bool = False, log=print, block="auto") -> dict:
    """Pone los sprites de varias especies [(nº de especie, nombre en Showdown)] y escribe la ROM una sola vez.
    Las que no tienen sus 4 PNG en la carpeta se saltan."""
    r = rom.Rom(rom_path)
    files = r.narc(SPRITES)
    new, done = list(files), {}
    for species, name in pairs:
        lack = missing(folder, name)
        if lack:
            log(f"#{species} {name}: se salta, faltan {', '.join(lack)}")
            continue
        log(f"#{species} {name}")
        base = species * FILES_PER_SPECIES
        new[base:base + FILES_PER_SPECIES], done[species] = _species_files(files, base, folder, name, static, log, block)
    if not done:
        raise SystemExit("ninguna especie convertida")
    data = bytearray(r.data)
    where = write_file(data, r, SPRITES, build_narc(r.file(SPRITES), new))
    with open(out_path, "wb") as f:
        f.write(data)
    log(f"{len(done)} especies; sprites {where}; guardado en {out_path}")
    return done


def convert(rom_path: str, out_path: str, species: int, folder: str, name: str, static: bool = False, log=print,
            block="auto") -> dict:
    return convert_many(rom_path, out_path, [(species, name)], folder, static, log, block)[species]


def showdown_id(name: str) -> str:
    """Nombre del juego -> nombre de archivo en Showdown (Flabébé -> flabebe, Mr. Mime -> mrmime)."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "".join(c for c in plain.lower() if c.isalnum())


def download(name: str, folder: str = CACHE, log=print) -> None:
    os.makedirs(folder, exist_ok=True)
    for view, (ani, png) in VIEWS.items():
        for sub, ext in ((ani, "gif"), (png, "png")):
            dst = os.path.join(folder, f"{sub}_{name}.{ext}")
            if os.path.exists(dst):
                continue
            req = urllib.request.Request(f"{SHOWDOWN}{sub}/{name}.{ext}", headers={"User-Agent": "PkmRealTime-sprites/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp, open(dst, "wb") as f:
                    f.write(resp.read())
                log(f"  {sub}/{name}.{ext}")
            except Exception as e:      # muchas especies no tienen animación (o no tienen espalda animada)
                log(f"  falta {sub}/{name}.{ext} ({e})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("descargar"); d.add_argument("nombre", nargs="+"); d.add_argument("--carpeta", default=CACHE)
    c = sub.add_parser("convertir")
    c.add_argument("--rom", required=True); c.add_argument("--salida", required=True)
    c.add_argument("--especie", type=int, required=True, help="nº de la especie cuyo sprite se reemplaza")
    c.add_argument("--nombre", required=True, help="nombre en Showdown (sylveon, tapukoko...)")
    c.add_argument("--carpeta", default=CACHE); c.add_argument("--fijo", action="store_true", help="sin animación")
    lt = sub.add_parser("lote", help="todas las especies de un rango, con el nombre que tienen en la ROM")
    lt.add_argument("--rom", required=True); lt.add_argument("--salida", required=True)
    lt.add_argument("--desde", type=int, required=True); lt.add_argument("--hasta", type=int, required=True)
    lt.add_argument("--carpeta", default=CACHE); lt.add_argument("--fijo", action="store_true", help="sin animación")
    lt.add_argument("--sin-descargar", action="store_true", help="usar solo lo que ya está en la carpeta")
    for p in (c, lt):
        p.add_argument("--bloque", choices=("auto", "8", "16"), default="auto",
                       help="tamaño de las piezas: 8 = todos los fotogramas; 16 = menos piezas (menos cortes con la cámara"
                            " cerca); auto (por defecto) = 16 si conserva al menos la mitad de los fotogramas")
    a = ap.parse_args()
    if a.cmd == "descargar":
        for n in a.nombre:
            download(n, a.carpeta)
        return
    if os.path.abspath(a.rom) == os.path.abspath(a.salida):
        raise SystemExit("la salida tiene que ser otro archivo (la ROM original no se toca)")
    block = a.bloque if a.bloque == "auto" else int(a.bloque)
    if a.cmd == "lote":
        names = rom.Rom(a.rom).text(rom.TEXT_SPECIES)
        pairs = [(sp, showdown_id(names[sp])) for sp in range(a.desde, a.hasta + 1)]
        if not a.sin_descargar:
            for _, n in pairs:
                download(n, a.carpeta)
        convert_many(a.rom, a.salida, pairs, a.carpeta, a.fijo, block=block)
    else:
        convert(a.rom, a.salida, a.especie, a.carpeta, a.nombre, a.fijo, block=block)


if __name__ == "__main__":
    main()
