"""Pruebas de tools/sprites_gen5.py sin Pillow ni juego (python tests/test_sprites_gen5.py).

Con fotogramas sintéticos: se generan los archivos de una vista y se "reproducen" como MCSS (nodo + celda de su
animación + rectángulo de la textura) para comprobar que en cada momento sale el fotograma de partida."""
import os, random, struct, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import sprites_gen5 as sg

# LZ11: ida y vuelta (cortas, medianas, largas y sin repeticiones)
rng = random.Random(1)
for data in (bytes(100), bytes(70000), bytes(range(256)) * 3, bytes(rng.randrange(4) for _ in range(5000)),
             bytes(300) + b"ab" * 200 + bytes(70000)):
    assert sg.lz_decompress(sg.lz11(data)) == data

# 96x96 en piezas OAM: es una reordenación de los píxeles
img = [i % 16 for i in range(9216)]
t = sg.tiled96(img)
assert sorted(t) == sorted(img) and t[:8] == img[:8] and t[8:16] == img[96:104] and t[64:72] == img[8:16]   # cuadros de 8x8 por filas

# duraciones: el total no se desfasa
assert sum(sg.ds_durations([100] * 64)) == 384 and sum(sg.ds_durations([30] * 10)) == 18


def ncgr_template(pixels: int, compressed: bool) -> bytes:
    """NCGR mínimo: RGCN + bloque RAHC con tamaño de datos (0x28) y desplazamiento (0x2C, relativo a 0x18)."""
    d = bytearray(b"RGCN" + struct.pack("<HHIHH", 0xFEFF, 0x0101, 0, 16, 1))
    d += b"RAHC" + struct.pack("<I", 0x20 + pixels // 2) + struct.pack("<HHIIIII", 0, 0, 3, 0, 1, pixels // 2, 0x18)
    d += bytes(pixels // 2)
    return sg.lz11(bytes(d)) if compressed else bytes(d)


def frame(dx, dy, color):
    """Un "Pokémon" de 20x30 con los pies en la fila 75 que se mueve un poco."""
    px = [0] * 9216
    for y in range(45 + dy, 75 + dy + 1):
        for x in range(38 + dx, 58 + dx):
            px[y * 96 + x] = color if (x + y) % 5 else 2
    return px


frames = [frame(dx, dy, c) for dx, dy, c in ((0, 0, 1), (1, 0, 1), (1, -1, 3), (0, -1, 3))]
durs = [6, 6, 7, 6]
templates = [ncgr_template(96 * 96, True), b"", ncgr_template(256 * 128, True)] + [b""] * 6
files, info = sg.side_files(templates, frames, durs)
assert info["frames"] == 4 and info["step"] == 1 and info["ticks"] == 25 and info["tiles"] <= sg.TILES_MAX


def read_anim(d):
    if d[0] in (0x10, 0x11):
        d = sg.lz_decompress(d)
    b = d.find(b"KNBA") + 8
    nseq, _, off_seq, off_fr, off_el = struct.unpack_from("<HHIII", d, b)
    seqs = []
    for s in range(nseq):
        nf, _, elem, kind, mode, first = struct.unpack_from("<HHHHII", d, b + off_seq + 16 * s)
        assert elem == 0 and mode == 2
        fr = []
        for f in range(nf):
            p_el, dur = struct.unpack_from("<IH", d, b + off_fr + first + 8 * f)
            fr.append((dur, struct.unpack_from("<H", d, b + off_el + p_el)[0]))
        seqs.append(fr)
    return seqs


for block in (8, 16):
    files, info = sg.side_files(templates, frames, durs, block)
    assert info["tiles"] <= sg.capacity(block)
    nanr, nmar = read_anim(files[5]), read_anim(files[7])
    assert nmar == [[(25, 0)]]                                   # la multi-celda dura el ciclo entero
    d = files[6]; b = d.find(b"KBCM") + 8
    n, _, off_mc, off_hier = struct.unpack_from("<HHII", d, b)
    nn, nca, off_h = struct.unpack_from("<HHI", d, b + off_mc)
    nodes = [struct.unpack_from("<HhhH", d, b + off_hier + off_h + 8 * k) for k in range(nn)]
    assert n == 1 and nn == nca == len(nanr) and all(attr >> 8 == k for k, (_, _, _, attr) in enumerate(nodes))
    count, w, h, ox, oy = struct.unpack_from("<IHHhh", files[8], 0)
    assert count == info["tiles"] and len(files[8]) == 12 + 48 * count + 4 and (w, h) == (21 + 7, 32 + 7)
    tex = sg.ncgr_pixels(files[2]); tex = [(tex[i // 2] >> (4 * (i & 1))) & 15 for i in range(len(tex) * 2)]
    assert files[4][:4] == b"RECN" and struct.unpack_from("<H", files[4], 0x18)[0] == count
    # 96x96 (pantallas 2D) = primer fotograma
    p0 = sg.ncgr_pixels(files[0]); assert [(p0[i // 2] >> (4 * (i & 1))) & 15 for i in range(9216)] == sg.tiled96(frames[0])

    feet = 75
    for f, start in enumerate((0, 6, 12, 19)):
        for tick in (start, start + 5):
            out = [0] * 9216
            for (seq, x, y, attr) in nodes:
                acc = 0
                for dur, idx in nanr[attr >> 8]:
                    if acc + dur > tick:
                        break
                    acc += dur
                q = struct.unpack_from("<6i", files[8], 12 + 48 * idx)
                s0, t0 = q[4] // sg.FX, q[5] // sg.FX
                for yy in range(block):
                    for xx in range(block):
                        out[(y + feet + 1 + yy) * 96 + x + 48 + xx] = tex[(t0 + yy) * 256 + s0 + xx]
            assert out == frames[f], (f, tick)


# auto: con pocos cuadritos distintos elige 16 (menos piezas)
assert sg.side_files(templates, frames, durs, "auto")[1]["block"] == 16

# demasiados cuadritos: se usan menos fotogramas
noisy = [[rng.randrange(1, 16) if 20 <= i % 96 < 76 and 20 <= i // 96 < 76 else 0 for i in range(9216)] for _ in range(20)]
f2, d2, tiles, _, step = sg.fit_frames(noisy, [5] * 20)
assert step > 1 and len(tiles) <= sg.TILES_MAX and sum(d2) == 100

# NARC: rehacerlo sin cambios da el mismo archivo (con la ROM, si está configurada)
import config, rom
path = config.rom_path()
if path and os.path.exists(path):
    r = rom.Rom(path)
    assert sg.build_narc(r.file(sg.SPRITES), r.narc(sg.SPRITES)) == r.file(sg.SPRITES)
    print("ok NARC de sprites de la ROM")
print("ok sprites Gen 5")
