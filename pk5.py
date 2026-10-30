"""Cifrado y edición de Pokémon Gen 5 (formato PK5).

Caja: 136 bytes. Equipo: 220 bytes (136 + 84 de stats de combate).
Fuente del formato: projectpokemon.org (Pokemon NDS Structure / BW save structure).
"""
import functools
import struct

import move_pp

BOX_SIZE = 136
PARTY_SIZE = 220

# Orden de bloques según shift = ((pid & 0x3E000) >> 13) % 24
_ORDERS = [
    "ABCD", "ABDC", "ACBD", "ACDB", "ADBC", "ADCB",
    "BACD", "BADC", "BCAD", "BCDA", "BDAC", "BDCA",
    "CABD", "CADB", "CBAD", "CBDA", "CDAB", "CDBA",
    "DABC", "DACB", "DBAC", "DBCA", "DCAB", "DCBA",
]

# Gen 5 guarda el estado como número, NO como bits (eso era Gen 3-4).
# Fuente: PKHeX, enum StatusType "for Generation 5+". Un valor fuera de 0-5
# hace que el juego muestre otro ícono y se cuelgue en la pantalla de datos.
# Fuera de combate no hay "toxic" ni contador de sueño.
STATUS_CODES = {
    "none": 0,
    "paralysis": 1,
    "sleep": 2,
    "freeze": 3,
    "burn": 4,
    "poison": 5,
}
STATUS_NAMES = {v: k for k, v in STATUS_CODES.items()}

MAX_ITEM = 638       # último objeto de Gen 5

# Offsets en datos YA descifrados y ordenados
OFF_SPECIES = 0x08
OFF_HELD_ITEM = 0x0A
OFF_MOVES = 0x28
OFF_PP = 0x30        # 4 bytes, PP actuales
OFF_PP_UPS = 0x34    # 4 bytes, Más PP usados (0-3)
OFF_STATUS = 0x88
OFF_LEVEL = 0x8C
OFF_CUR_HP = 0x8E
OFF_MAX_HP = 0x90


def _prng(seed: int):
    x = seed & 0xFFFFFFFF
    while True:
        x = (0x41C64E6D * x + 0x6073) & 0xFFFFFFFF
        yield x >> 16


def _xor_words(data: bytearray, start: int, end: int, seed: int) -> None:
    rng = _prng(seed)
    for i in range(start, end, 2):
        w = struct.unpack_from("<H", data, i)[0] ^ next(rng)
        struct.pack_into("<H", data, i, w)


def _shift(pid: int) -> int:
    return ((pid & 0x3E000) >> 13) % 24


def checksum(data: bytes) -> int:
    return sum(struct.unpack_from("<64H", data, 0x08)) & 0xFFFF


def _shuffle(data: bytearray, order: str, inverse: bool) -> None:
    blocks = [bytes(data[0x08 + 32 * i: 0x08 + 32 * (i + 1)]) for i in range(4)]
    out = [b""] * 4
    for dst, letter in enumerate(order):
        src = "ABCD".index(letter)
        if inverse:
            out[src] = blocks[dst]
        else:
            out[dst] = blocks[src]
    data[0x08:0x88] = b"".join(out)


@functools.lru_cache(maxsize=2048)
def decrypt_ro(raw: bytes) -> bytes:
    """decrypt() con memoria, para leer sin modificar: los mismos bytes cifrados no se vuelven a descifrar (las cajas casi
    nunca cambian y se leen en cada consulta). Devuelve bytes (inmutables) para que nadie cambie la copia guardada."""
    return bytes(decrypt(raw))


def decrypt(raw: bytes) -> bytearray:
    """Recibe 136 o 220 bytes cifrados, devuelve descifrados y ordenados (ABCD)."""
    data = bytearray(raw)
    pid = struct.unpack_from("<I", data, 0)[0]
    chk = struct.unpack_from("<H", data, 6)[0]
    _xor_words(data, 0x08, 0x88, chk)
    _shuffle(data, _ORDERS[_shift(pid)], inverse=True)
    if len(data) > BOX_SIZE:
        _xor_words(data, 0x88, len(data), pid)
    return data


def encrypt(plain: bytes) -> bytearray:
    """Recalcula el checksum, reordena y cifra. Acepta 136 o 220 bytes."""
    data = bytearray(plain)
    pid = struct.unpack_from("<I", data, 0)[0]
    chk = checksum(data)
    struct.pack_into("<H", data, 6, chk)
    _shuffle(data, _ORDERS[_shift(pid)], inverse=False)
    _xor_words(data, 0x08, 0x88, chk)
    if len(data) > BOX_SIZE:
        _xor_words(data, 0x88, len(data), pid)
    return data


def is_valid(plain: bytes) -> bool:
    return checksum(plain) == struct.unpack_from("<H", plain, 6)[0]


def nickname(plain: bytes) -> str:
    """Mote (0x48, 11 caracteres UTF-16 terminados en 0xFFFF)."""
    out = []
    for i in range(0x48, 0x5E, 2):
        c = plain[i] | plain[i + 1] << 8
        if c == 0xFFFF:
            break
        out.append(chr(c))
    return "".join(out)


def summary(plain: bytes) -> dict:
    """Resumen legible de un Pokémon descifrado."""
    u16 = lambda o: struct.unpack_from("<H", plain, o)[0]
    info = {
        "species": u16(OFF_SPECIES),
        "held_item": u16(OFF_HELD_ITEM),
        "moves": [u16(OFF_MOVES + 2 * i) for i in range(4)],
        "pp": list(plain[OFF_PP:OFF_PP + 4]),
        "valid": is_valid(plain),
    }
    # bloques sin cifrar del PK5 (PKHeX PK5): PID 0x00, TID/SID 0x0C/0x0E, habilidad 0x15, 0x40 bits (1 hembra,
    # 2 sin sexo, 3-7 forma), 0x41 naturaleza, 0x42 bit 0 = habilidad oculta
    pid, tid, sid = struct.unpack_from("<I", plain, 0)[0], u16(0x0C), u16(0x0E)
    info.update(
        shiny=((pid >> 16) ^ (pid & 0xFFFF) ^ tid ^ sid) < 8,
        gender="genderless" if plain[0x40] & 4 else "female" if plain[0x40] & 2 else "male",
        form=plain[0x40] >> 3,
        ability=plain[0x15],
        hidden_ability=bool(plain[0x42] & 1),
        nature=plain[0x41],
        egg=bool(struct.unpack_from("<I", plain, 0x38)[0] >> 30 & 1),   # bit 30 de las IV
        nickname=nickname(plain),
    )
    if info["egg"]:
        info["egg_cycles"] = plain[0x14]   # en un huevo, la amistad cuenta los ciclos que faltan (256 pasos cada uno)
    if len(plain) >= PARTY_SIZE:
        st = struct.unpack_from("<I", plain, OFF_STATUS)[0]
        info.update(
            level=plain[OFF_LEVEL],
            hp=u16(OFF_CUR_HP),
            max_hp=u16(OFF_MAX_HP),
            status=STATUS_NAMES.get(st, f"invalido({st:#x})"),
        )
    return info


def set_hp(raw: bytes, hp: int) -> bytearray:
    p = decrypt(raw)
    max_hp = struct.unpack_from("<H", p, OFF_MAX_HP)[0]
    struct.pack_into("<H", p, OFF_CUR_HP, max(0, min(hp, max_hp)))
    return encrypt(p)


def set_status(raw: bytes, status: str) -> bytearray:
    p = decrypt(raw)
    struct.pack_into("<I", p, OFF_STATUS, STATUS_CODES[status])  # campo de 32 bits
    return encrypt(p)


def heal(raw: bytes) -> bytearray:
    """HP al máximo, sin estado y PP al máximo (como un Centro Pokémon)."""
    p = decrypt(raw)
    struct.pack_into("<H", p, OFF_CUR_HP, struct.unpack_from("<H", p, OFF_MAX_HP)[0])
    struct.pack_into("<I", p, OFF_STATUS, STATUS_CODES["none"])
    for i in range(4):
        move = struct.unpack_from("<H", p, OFF_MOVES + 2 * i)[0]
        p[OFF_PP + i] = move_pp.max_pp(move, p[OFF_PP_UPS + i] & 3)
    return encrypt(p)


def set_item(raw: bytes, item: int) -> bytearray:
    """Objeto equipado (0 = ninguno)."""
    if not 0 <= item <= MAX_ITEM:
        raise ValueError(f"objeto fuera de rango (0-{MAX_ITEM}): {item}")
    p = decrypt(raw)
    struct.pack_into("<H", p, OFF_HELD_ITEM, item)
    return encrypt(p)


def set_egg_cycles(raw: bytes, cycles: int) -> bytearray:
    """Ciclos que le faltan a un huevo para eclosionar (la amistad, 0x14). Cada ciclo son 256 pasos; con 0 eclosiona
    al terminar el ciclo de pasos en curso."""
    if not 0 <= cycles <= 255:
        raise ValueError("hatch_cycles debe ir de 0 a 255")
    p = decrypt(raw)
    if not summary(p)["egg"]:
        raise ValueError("ese Pokémon no es un huevo")
    p[0x14] = cycles
    return encrypt(p)


def set_move(raw: bytes, move_slot: int, move: int) -> bytearray:
    """Pone un movimiento en el hueco 0-3 con sus PP al máximo y sin Más PP.

    move = 0 borra el hueco; el juego no admite huecos vacíos antes de uno lleno,
    así que solo se permite borrar si los de después ya están vacíos.
    """
    if not 0 <= move_slot <= 3:
        raise ValueError(f"hueco de movimiento fuera de rango (0-3): {move_slot}")
    if not 0 <= move <= move_pp.MAX_MOVE:
        raise ValueError(f"movimiento fuera de rango (0-{move_pp.MAX_MOVE}): {move}")
    p = decrypt(raw)
    moves = [struct.unpack_from("<H", p, OFF_MOVES + 2 * i)[0] for i in range(4)]
    if move and move in moves and moves.index(move) != move_slot:
        raise ValueError(f"el Pokémon ya conoce el movimiento {move}")
    if move == 0 and any(moves[move_slot + 1:]):
        raise ValueError("no se puede borrar un movimiento con otros detrás")
    if move and move_slot > 0 and moves[move_slot - 1] == 0:
        raise ValueError(f"hueco {move_slot} no permitido: el hueco {move_slot - 1} está vacío")
    if moves[0] and move == 0 and move_slot == 0:
        raise ValueError("el Pokémon debe conocer al menos un movimiento")
    struct.pack_into("<H", p, OFF_MOVES + 2 * move_slot, move)
    p[OFF_PP + move_slot] = move_pp.max_pp(move)
    p[OFF_PP_UPS + move_slot] = 0
    return encrypt(p)
