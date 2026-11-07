"""Marca el ARM9 de la ROM como no comprimido (compressed_end = 0 en los parámetros del módulo).

White2Upgrade sustituye el ARM9 por el de PMC, que ya viene descomprimido, pero conserva compressed_end = 0x020776CC:
al arrancar, el juego "descomprime" código que no lo está y se queda en blanco.
Uso: python3 fix_arm9.py White2Upgrade.nds
"""
import struct
import sys

path = sys.argv[1]
with open(path, "r+b") as f:
    head = f.read(0x40)
    off, _, ram, size = struct.unpack_from("<IIII", head, 0x20)
    f.seek(off)
    arm9 = f.read(size)
    mark = arm9.find(struct.pack("<II", 0xDEC00621, 0x2106C0DE))      # marca de los parámetros del módulo (nitrocode)
    if mark < 0:
        sys.exit("no se encontraron los parámetros del módulo en el ARM9")
    field = mark - 0x1C + 0x14
    comp_end = struct.unpack_from("<I", arm9, field)[0]
    if comp_end == 0:
        print("ARM9 ya marcado como no comprimido")
    elif comp_end - ram > size or size >= 0x90000:
        f.seek(off + field)
        f.write(bytes(4))
        print(f"compressed_end {comp_end:#x} -> 0 (ARM9 de {size:#x} bytes, ya descomprimido)")
    else:
        print(f"compressed_end {comp_end:#x}: el ARM9 parece comprimido de verdad; no se toca")
