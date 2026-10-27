"""Analiza volcados de RAM hechos con dump_ram.lua.

  python tools/ram_tool.py info   dumps/mapa1.bin
      puntero, dirección del equipo y Pokémon que contiene
  python tools/ram_tool.py boxes  dumps/mapa1.bin
      busca Pokémon de caja (136 bytes) válidos fuera del equipo
  python tools/ram_tool.py diff --a dumps/mapa1.bin dumps/mapa2.bin --b dumps/menu1.bin dumps/menu2.bin
      bytes iguales dentro de cada grupo y distintos entre grupos (ej. "menú abierto")
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # módulos de la raíz
import config
import pk5

BASE = config.MAIN_RAM_BASE
MAX_SPECIES = 649   # Gen 5
MAX_MOVE = 559


def load(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def pointer(ram: bytes) -> int:
    return struct.unpack_from("<I", ram, config.MAIN_POINTER_OFF)[0] & 0xFFFFFF


def party_range(ram: bytes) -> tuple[int, int, int]:
    """(offset del equipo, cuántos hay, offset final) dentro del volcado."""
    ptr = pointer(ram)
    start = ptr + config.PARTY_PTR_OFF
    n = ram[ptr + config.PARTY_COUNT_PTR_OFF]
    return start, n, start + 6 * config.PARTY_SLOT_SIZE


def looks_like_mon(plain: bytes) -> bool:
    if not pk5.is_valid(plain) or struct.unpack_from("<I", plain, 0)[0] == 0:
        return False
    s = pk5.summary(plain)
    return 1 <= s["species"] <= MAX_SPECIES and all(m <= MAX_MOVE for m in s["moves"]) and s["moves"][0] != 0


def cmd_info(args) -> None:
    ram = load(args.dump)
    ptr = pointer(ram)
    start, n, _ = party_range(ram)
    print(f"puntero      {BASE + ptr:#010x}")
    print(f"equipo       {BASE + start:#010x}  ({n} Pokémon)")
    for i in range(min(n, 6)):
        raw = ram[start + i * 220: start + (i + 1) * 220]
        print(f"  slot {i}: {pk5.summary(pk5.decrypt(raw))}")


def cmd_boxes(args) -> None:
    ram = load(args.dump)
    ptr = pointer(ram)
    p_start, _, p_end = party_range(ram)
    found = []
    for off in range(0, len(ram) - pk5.BOX_SIZE, 4):
        if p_start <= off < p_end:
            continue
        # banderas (0x04) a 0 cuando está cifrado, y PID distinto de 0
        if struct.unpack_from("<H", ram, off + 4)[0] != 0 or struct.unpack_from("<I", ram, off)[0] == 0:
            continue
        plain = pk5.decrypt(ram[off:off + pk5.BOX_SIZE])
        if looks_like_mon(plain):
            found.append(off)
    print(f"{len(found)} Pokémon válidos fuera del equipo:")
    for off in found:
        s = pk5.summary(pk5.decrypt(ram[off:off + pk5.BOX_SIZE]))
        rel = off - ptr
        print(f"  {BASE + off:#010x}  puntero{rel:+#x}  especie {s['species']:3d}  movs {s['moves']}")
    print("La caja 1 slot 1 es la de dirección más baja en una serie separada por 136 (0x88) bytes.")


def cmd_diff(args) -> None:
    a = [load(p) for p in args.a]
    b = [load(p) for p in args.b]
    size = min(len(x) for x in a + b)

    def candidates(groups_a, groups_b, shift_a, shift_b):
        out = []
        for off in range(size):
            va = {g[off + s] for g, s in zip(groups_a, shift_a) if 0 <= off + s < size}
            vb = {g[off + s] for g, s in zip(groups_b, shift_b) if 0 <= off + s < size}
            if len(va) == 1 and len(vb) == 1 and va != vb:
                out.append((off, va.pop(), vb.pop()))
        return out

    # direcciones fijas
    fixed = candidates(a, b, [0] * len(a), [0] * len(b))
    show("Direcciones fijas", fixed, lambda off: f"{BASE + off:#010x}", args.limit)

    # relativas al puntero, por si la estructura se mueve con él
    ptrs = [pointer(x) for x in a + b]
    if len(set(ptrs)) > 1:
        base = ptrs[0]
        shifts = [p - base for p in ptrs]
        rel = candidates(a, b, shifts[:len(a)], shifts[len(a):])
        show("Relativas al puntero", rel, lambda off: f"puntero{off - base:+#x}", args.limit)
    else:
        print("\n(el puntero es igual en todos los volcados; reinicia el juego entre volcados para distinguir fijas de relativas)")


def show(title, rows, fmt, limit) -> None:
    rows.sort(key=lambda r: (r[1] != 0, r[2] == 0))   # primero: 0 en A y distinto de 0 en B
    print(f"\n{title}: {len(rows)} candidatos")
    for off, va, vb in rows[:limit]:
        print(f"  {fmt(off)}   A={va:#04x}  B={vb:#04x}")
    if len(rows) > limit:
        print(f"  ... ({len(rows) - limit} más; añade más volcados a cada grupo para reducir la lista)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("dump"); p.set_defaults(fn=cmd_info)
    p = sub.add_parser("boxes"); p.add_argument("dump"); p.set_defaults(fn=cmd_boxes)
    p = sub.add_parser("diff")
    p.add_argument("--a", nargs="+", required=True, help="volcados del estado A (ej. mapa)")
    p.add_argument("--b", nargs="+", required=True, help="volcados del estado B (ej. menú abierto)")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(fn=cmd_diff)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
