"""Calcula cuánto se desplazan las funciones de unos símbolos de Black 2 (pokebw2) en un volcado de RAM.

Uso: python tools/symbol_offset.py dumps/mapa1.bin symbols.txt [más symbols.txt...]
Los symbols.txt salen de pokebw2: config/b2_us/arm9/symbols.txt y config/b2_us/arm9/overlays/ovNNN/symbols.txt.
Para cada desplazamiento posible cuenta cuántas funciones Thumb (de 0x40 bytes o más) empiezan por push {..., lr}
(segundo byte 0xB5 o 0xB4) en el volcado. El mejor es el desplazamiento de ese código en el juego del volcado.
Resultados con White 2 (IRDO): código principal +0x2C; overlays 12, 36 y 167, +0x40.
"""
import re
import sys

BASE = 0x02000000


def functions(path: str) -> list[int]:
    out = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\S+ kind:function\(thumb,size=(0x[0-9a-f]+)\) addr:(0x[0-9a-f]+)", line)
        if m and int(m.group(1), 16) >= 0x40:
            out.append(int(m.group(2), 16))
    return out


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    ram = open(sys.argv[1], "rb").read()
    for path in sys.argv[2:]:
        addrs = functions(path)
        scores = []
        for off in range(-0x2000, 0x2000, 4):
            hits = sum(1 for a in addrs if 0 <= a + off - BASE < len(ram) - 2 and ram[a + off - BASE + 1] in (0xB4, 0xB5))
            scores.append((hits, off))
        scores.sort(reverse=True)
        print(f"{path}: {len(addrs)} funciones; mejores: " + ", ".join(f"{o:+#x} ({h})" for h, o in scores[:3]))


if __name__ == "__main__":
    main()
