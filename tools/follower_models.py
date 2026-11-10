"""Baja los modelos de Pokémon que caminan para que pisen su sombra (acompañante y Grutas Ocultas).

Uso:  python tools/follower_models.py --rom Mezcla.nds [--offset -4]

Los modelos de Pokémon (códigos de objeto 0x1000 en adelante, los de HeartGold) se dibujan unos píxeles por encima de
su sombra y parecen flotar. La tabla de modelos (a/0/4/7, ARCID_MMODEL_TBL: 4 bytes y luego 28 por modelo) tiene un
desplazamiento vertical (wPosOffsetY, s8 en +14) que mueve el dibujo; la sombra también se movería, pero el gancho de
FldeffShadow_Draw en patches/follower.cpp la deja en el suelo en los modelos de Pokémon. Validado en el juego
(08-nov): con -4, Eevee y Pidove quedan bien; sin él, Pikachu flota.
Solo cambia los de tamaño normal (billboardSize 0); los grandes (Wailord...) se quedan. Escribe la ROM en su sitio:
la cabecera no cambia, así que el puente no necesita regenerar sus datos.
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

MMODEL_TBL = "a/0/4/7"
RECORD = 28
OBJ_CODE_POKEMON_MIN = 0x1000
OFF_BILLBOARD_SIZE = 7
OFF_POS_Y = 14
DEFAULT_OFFSET = -4


def lower_pokemon(table: bytes, offset: int) -> tuple[bytes, int]:
    """La tabla con wPosOffsetY = offset en los modelos de Pokémon de tamaño normal, y cuántos cambió."""
    d = bytearray(table)
    n = 0
    for pos in range(4, len(d) - RECORD + 1, RECORD):
        uid = struct.unpack_from("<H", d, pos)[0]
        if uid >= OBJ_CODE_POKEMON_MIN and d[pos + OFF_BILLBOARD_SIZE] == 0:
            struct.pack_into("<b", d, pos + OFF_POS_Y, offset)
            n += 1
    return bytes(d), n


def apply(path: str, offset: int = DEFAULT_OFFSET, log=print) -> None:
    r = rom.Rom(path)
    files = r.narc(MMODEL_TBL)
    files[0], n = lower_pokemon(files[0], offset)
    data = bytearray(r.data)
    where = write_file(data, r, MMODEL_TBL, build_narc(r.file(MMODEL_TBL), files))
    with open(path, "wb") as f:
        f.write(data)
    log(f"{n} modelos de Pokémon con desplazamiento {offset}; tabla {where}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", required=True)
    ap.add_argument("--offset", type=int, default=DEFAULT_OFFSET)
    a = ap.parse_args()
    apply(a.rom, a.offset)


if __name__ == "__main__":
    main()
