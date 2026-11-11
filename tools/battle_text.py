"""Mensajes de combate nuevos (los de las habilidades de Gen 6), al final de su archivo de texto.

Uso:  python tools/battle_text.py --rom Mezcla.nds

Los mensajes que salen al activarse una habilidad ("¡X ejerce su Presión!") están en el archivo de texto 18 (a/0/0/2),
de tres en tres: tu Pokémon, el salvaje ("The wild X...") y el del rival ("The foe's X..."); el juego elige según el
bando. Se añaden detrás de los 1159 del juego, desde FIRST_LINE; patches/abilities.cpp los pide por ese número.
Va después de merge_redux.py.
"""
import argparse
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rom                                          # noqa: E402
from sprites_gen5 import build_narc, write_file     # noqa: E402

BATTLE_TEXT = 18
FIRST_LINE = 1159                   # tras los del juego (patches/abilities.cpp: MSG_DARK_AURA...)
MON = (0xF000, 0x0102, 0x0001, 0x0000)   # código del nombre del Pokémon (argumento 0)
END = 0xFFFF
NEWLINE = 0xFFFE
# Uno por habilidad, en el orden de abilities.cpp: Aura Oscura, Aura Feérica, Rompeaura
MESSAGES = [
    "{mon} is radiating\na dark aura!",
    "{mon} is radiating\na fairy aura!",
    "{mon} reversed all\nother Pokémon's auras!",
]
PREFIXES = ("", "The wild ", "The foe's ")


def line_key(i: int) -> int:
    return (0x7C89 + i * 0x2983) & 0xFFFF


def read_lines(d: bytes) -> list[list[int]]:
    """Las líneas descifradas (códigos de 16 bits, con el final), de la primera sección."""
    sections, lines = struct.unpack_from("<HH", d, 0)
    if sections != 1:
        raise ValueError(f"se espera un archivo de texto de una sección ({sections})")
    sec = struct.unpack_from("<I", d, 0x0C)[0]
    out = []
    for i in range(lines):
        off, length, _ = struct.unpack_from("<IHH", d, sec + 4 + 8 * i)
        enc = struct.unpack_from(f"<{length}H", d, sec + off)
        key, dec = line_key(i), []
        for c in enc:
            dec.append(c ^ key)
            key = ((key << 3) | (key >> 13)) & 0xFFFF
        out.append(dec)
    return out


def build(lines: list[list[int]]) -> bytes:
    table, data = bytearray(), bytearray()
    start = 4 + 8 * len(lines)
    for i, dec in enumerate(lines):
        key, enc = line_key(i), []
        for c in dec:
            enc.append(c ^ key)
            key = ((key << 3) | (key >> 13)) & 0xFFFF
        table += struct.pack("<IHH", start + len(data), len(enc), 0)
        data += struct.pack(f"<{len(enc)}H", *enc)
    data += bytes(-(4 + len(table) + len(data)) % 4)     # la sección acaba alineada a 4
    section = struct.pack("<I", 4 + len(table) + len(data)) + table + data
    return struct.pack("<HHIII", 1, len(lines), len(section), 0, 0x10) + section


def encode(text: str) -> list[int]:
    out = []
    head, _, tail = text.partition("{mon}")
    for part, mon in ((head, True), (tail, False)):
        out += [NEWLINE if ch == "\n" else ord(ch) for ch in part]
        if mon:
            out += MON
    return out + [END]


def new_lines() -> list[list[int]]:
    return [encode(p + m) for m in MESSAGES for p in PREFIXES]


def add_messages(d: bytes) -> bytes:
    lines = read_lines(d)
    again = build(lines)
    if len(again) != len(d) or again[:len(d) - 4] != d[:len(d) - 4]:   # el relleno del final puede ser otro
        raise ValueError("el archivo de texto no se puede rehacer igual (formato inesperado)")
    if len(lines) != FIRST_LINE:
        raise ValueError(f"el archivo de mensajes tiene {len(lines)} líneas; se esperan {FIRST_LINE}")
    return build(lines + new_lines())


def apply(path: str, log=print) -> None:
    r = rom.Rom(path)
    files = list(r.narc(rom.TEXT))
    files[BATTLE_TEXT] = add_messages(files[BATTLE_TEXT])
    data = bytearray(r.data)
    log(f"{len(new_lines())} mensajes de combate ({FIRST_LINE}-{FIRST_LINE + len(new_lines()) - 1}): "
        + write_file(data, r, rom.TEXT, build_narc(r.file(rom.TEXT), files)))
    with open(path, "wb") as f:
        f.write(data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", required=True)
    apply(ap.parse_args().rom)


if __name__ == "__main__":
    main()
