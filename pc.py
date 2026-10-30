"""Mover y quitar Pokémon entre el equipo y las cajas, escribiendo directamente en la copia del save en RAM.

- Un hueco vacío (de la caja o del equipo) es un Pokémon "cero" cifrado, no ceros.
- Los 136 primeros bytes cifrados de un Pokémon del equipo son ya un Pokémon de caja válido (el checksum solo cubre
  0x08-0x87; los datos de combate 0x88-0xDB van cifrados aparte con el PID).
- De la caja al equipo hay que calcular los datos de combate (nivel, estadísticas, vida), como hace el juego al sacarlo.
"""
import struct

import gamedata
import gift
import pk5

BOX_SLOT, PARTY_SLOT, PARTY_MAX = 136, 220, 6
EMPTY_BOX = bytes(pk5.encrypt(bytes(BOX_SLOT)))
EMPTY_PARTY = bytes(pk5.encrypt(bytes(PARTY_SLOT)))
OFF_STATS = 0x90     # vida máx, Ataque, Defensa, Velocidad, At. Esp., Def. Esp. (u16)


def party_block(party: list) -> bytes:
    """Contador u32 + 6 huecos, tal como está en RAM (equipo = puntero + 0x19724)."""
    return struct.pack("<I", len(party)) + b"".join(party) + EMPTY_PARTY * (PARTY_MAX - len(party))


def is_empty(raw: bytes) -> bool:
    return gift.is_empty_slot(raw[:BOX_SLOT])


def stats(plain: bytes, level: int) -> list:
    """Estadísticas de Gen 5 (orden del PK5: vida, Ataque, Defensa, Velocidad, At. Esp., Def. Esp.)."""
    sp = struct.unpack_from("<H", plain, 0x08)[0]
    base = gamedata.DATA["species"][str(sp)]["stats"]           # mismo orden en los datos personales de la ROM
    iv32 = struct.unpack_from("<I", plain, 0x38)[0]
    ivs = [(iv32 >> (5 * i)) & 31 for i in range(6)]
    evs = list(plain[0x18:0x1E])
    nature = plain[0x41]
    up, down = nature // 5 + 1, nature % 5 + 1                  # 1-5 = Ataque, Defensa, Velocidad, At. Esp., Def. Esp.
    out = []
    for i in range(6):
        core = (2 * base[i] + ivs[i] + evs[i] // 4) * level // 100
        if i == 0:
            out.append(1 if sp == 292 else core + level + 10)     # Shedinja siempre tiene 1
        else:
            v = core + 5
            if up != down:
                v = v * 11 // 10 if i == up else v * 9 // 10 if i == down else v
            out.append(v)
    return out


def to_party(box_raw: bytes, hp=None) -> bytes:
    """Pokémon de caja (cifrado) -> del equipo (cifrado), con vida llena salvo que se indique (0 = debilitado)."""
    plain = bytearray(pk5.decrypt(box_raw[:BOX_SLOT])) + bytearray(PARTY_SLOT - BOX_SLOT)
    level = gift.summary(plain)["level"]
    st = stats(plain, level)
    plain[pk5.OFF_LEVEL] = level
    struct.pack_into("<6H", plain, OFF_STATS, *st)
    struct.pack_into("<H", plain, pk5.OFF_CUR_HP, st[0] if hp is None else max(0, min(int(hp), st[0])))
    return bytes(pk5.encrypt(plain))


def first_free(box: bytes):
    return next((i for i in range(len(box) // BOX_SLOT) if is_empty(box[i * BOX_SLOT:(i + 1) * BOX_SLOT])), None)


def able(raw: bytes) -> bool:
    s = pk5.summary(pk5.decrypt(raw))
    return not s["egg"] and s.get("hp", 0) > 0
