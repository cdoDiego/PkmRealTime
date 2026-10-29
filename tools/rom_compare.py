"""Compara el código de dos ROMs de NDS (p. ej. la original y un romhack) para saber si el puente funcionará.

Uso:  python tools/rom_compare.py <original.nds> <hack.nds>

Muestra el código del cartucho y el CRC de la cabecera, qué overlays cambian, y las zonas del arm9 (descomprimido)
(y de los overlays, descomprimidos) que son distintas, avisando si alguna toca código que usa connector.lua. Al final revisa
en el hack las firmas de connector.lua (los bytes que el Lua comprueba antes de usar cada función).
El arm9 viene comprimido con BLZ (compresión hacia atrás); el final de la parte comprimida está en los parámetros
del módulo (tras la marca 0xDEC00621 0x2106C0DE, campo compressed_static_end).
"""
import os
import re
import struct
import sys

SIG_OVERLAY = {"battle": 167, "map": 12}   # overlay cargado en cada modo de las firmas
LUA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lua", "connector.lua")


def blz_decompress(data: bytes) -> bytes:
    footer, extra = struct.unpack_from("<II", data, len(data) - 8)
    header_len, comp_len = footer >> 24, footer & 0xFFFFFF
    start = len(data) - comp_len
    src = data[start:len(data) - header_len]
    out = bytearray(comp_len + extra)
    si, di = len(src), len(out)
    while si > 0 and di > 0:
        si -= 1
        flags = src[si]
        for _ in range(8):
            if si <= 0 or di <= 0:
                break
            if flags & 0x80:
                si -= 2
                b = src[si] | (src[si + 1] << 8)
                n, disp = (b >> 12) + 3, (b & 0xFFF) + 3
                for _ in range(n):
                    di -= 1
                    out[di] = out[di + disp]
            else:
                si -= 1
                di -= 1
                out[di] = src[si]
            flags = (flags << 1) & 0xFF
    return bytes(data[:start]) + bytes(out)


def load(path: str):
    with open(path, "rb") as f:
        h = f.read(0x200)
        code, crc = h[0xC:0x10].decode(errors="replace"), struct.unpack_from("<H", h, 0x15E)[0]
        a9_off, _, a9_ram, a9_size = struct.unpack_from("<IIII", h, 0x20)
        fat_off, fat_size, ovt_off, ovt_size = struct.unpack_from("<IIII", h, 0x48)
        f.seek(a9_off); arm9 = f.read(a9_size)
        f.seek(fat_off); fat = f.read(fat_size)
        f.seek(ovt_off); ovt = f.read(ovt_size)
        overlays = {}
        for i in range(0, len(ovt), 32):
            oid, ram, size, _, _, _, fid, flags = struct.unpack_from("<8I", ovt, i)
            s, e = struct.unpack_from("<II", fat, fid * 8)
            f.seek(s)
            data = f.read(e - s)
            if flags >> 24 & 1:                    # overlay comprimido (BLZ, como el arm9)
                data = blz_decompress(data)
            overlays[oid] = (ram, size, data)
    mark = arm9.find(struct.pack("<II", 0xDEC00621, 0x2106C0DE))
    if mark >= 0:
        comp_end = struct.unpack_from("<I", arm9, mark - 0x1C + 0x14)[0]
        if comp_end:
            arm9 = blz_decompress(arm9[:comp_end - a9_ram]) + arm9[comp_end - a9_ram:]
    return code, crc, a9_ram, arm9, overlays


def lua_sigs(game_code: str = "IRDO") -> dict:
    """Firmas de connector.lua: {función: (modo, [(dirección, hex), ...])}"""
    text = open(LUA, encoding="utf-8").read()
    block = text[text.index(f"{game_code} = {{"):]
    block = block[block.index("sigs = {"):]
    block = block[:re.search(r"\n\s*\} \},", block).start()]      # hasta la línea que cierra sigs y el juego
    sigs, current = {}, None
    for line in block.splitlines():
        m = re.search(r'(\w+)\s*=\s*\{\s*mode\s*=\s*"(\w+)"', line)
        if m:
            current = m.group(1)
            sigs[current] = (m.group(2), [])
        if current:
            sigs[current][1].extend((int(a, 16), h) for a, h in re.findall(r'\{\s*0x([0-9A-Fa-f]+),\s*"([0-9a-f]+)"\s*\}', line))
    return sigs


def check_sigs(arm9_ram: int, arm9: bytes, overlays: dict, game_code: str = "IRDO") -> dict:
    """{función: True/False} según si los bytes de la ROM coinciden con las firmas de connector.lua"""
    out = {}
    for name, (mode, pairs) in lua_sigs(game_code).items():
        ok = True
        for addr, hexs in pairs:
            n = len(hexs) // 2
            if arm9_ram <= addr < arm9_ram + len(arm9):
                got = arm9[addr - arm9_ram:addr - arm9_ram + n]
            else:
                ram, _, data = overlays.get(SIG_OVERLAY[mode], (0, 0, b""))
                got = data[addr - ram:addr - ram + n] if ram <= addr else b""
            ok = ok and got.hex() == hexs
        out[name] = ok
    return out


def diff_regions(a: bytes, b: bytes, base: int):
    out, i, n = [], 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j:j + 16] != b[j:j + 16]:
                j += 1
            out.append((base + i, j - i))
            i = j
        i += 1
    return out


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    ca, ra, a9r, arm_a, ov_a = load(sys.argv[1])
    cb, rb, _, arm_b, ov_b = load(sys.argv[2])
    print(f"cartucho {ca} / {cb}   crc cabecera {ra:04x} / {rb:04x}")
    changed = [o for o in ov_a if ov_a[o][2] != ov_b.get(o, (0, 0, b""))[2]]
    print(f"overlays: {len(ov_a)} / {len(ov_b)}; distintos: {changed or 'ninguno'}")
    # código que usa connector.lua: las direcciones de sus firmas, en el arm9 o en el overlay de su modo
    used = {}   # None (arm9) u overlay -> [(dirección, función)]
    for name, (mode, pairs) in lua_sigs().items():
        for addr, hexs in pairs:
            where = None if a9r <= addr < a9r + len(arm_a) else SIG_OVERLAY[mode]
            used.setdefault(where, []).append((addr, name))
    hit = False

    def show(regions, where):
        nonlocal hit
        for addr, n in regions:
            hits = sorted({name for u, name in used.get(where, []) if addr - 16 <= u < addr + n + 16})
            hit = hit or bool(hits)
            print(f"  {addr:#010x} +{n}" + (f"   <-- toca {', '.join(hits)}" if hits else ""))

    for o in changed:
        ra, sa, da = ov_a[o]
        rb, sb, db = ov_b.get(o, (0, 0, b""))
        if (ra, sa) != (rb, sb):
            print(f"  overlay {o}: se carga en otra dirección o con otro tamaño" + ("  <-- lo usa connector.lua" if o in used else ""))
            hit = hit or o in used
            continue
        regions = diff_regions(da, db, ra)
        print(f"  overlay {o}: {len(regions)} zonas distintas ({sum(n for _, n in regions)} bytes)")
        show(regions, o)
    regions = diff_regions(arm_a, arm_b, a9r)
    print(f"arm9: {len(arm_a)} / {len(arm_b)} bytes; {len(regions)} zonas distintas ({sum(n for _, n in regions)} bytes)")
    show(regions, None)
    sigs = check_sigs(a9r, arm_b, ov_b)
    off = [n for n, ok in sigs.items() if not ok]
    print("firmas de connector.lua en el hack:", "todas coinciden" if not off else
          f"NO coinciden {', '.join(off)} (esas funciones se desactivarán)")
    print("\nResultado:", "revisar: cambia código que usamos" if hit or off else
          "el código que usa el puente es el mismo (los datos se leen de la ROM con rom.py)")


if __name__ == "__main__":
    main()
