"""Regalo Misterioso de Gen 5 (EXPERIMENTAL, sin validar en el juego): álbum de Tarjetas Misteriosas.

Bloque del save 0x1C800 (0xA94 bytes) = RAM puntero + MYSTERY_PTR_OFF. También va cifrado en RAM:
  +0x000  banderas "ya recibido" (2048 bits, uno por ID de tarjeta)
  +0x100  12 tarjetas PGF de 0xCC bytes (vacía = todo ceros)
  +0xA90  semilla u32 (sin cifrar) del cifrado de PK5 (LCRNG, XOR por u16)

Formato PGF según PKHeX (PGF.cs) y tarjetas oficiales de la galería de Project Pokémon.
"""
import datetime
import struct

MYSTERY_PTR_OFF = 0x920 + 0x1C800   # = 0x1D120
DATA_SIZE = 0xA90                   # parte cifrada
BLOCK_SIZE = 0xA94                  # + semilla
FLAGS_SIZE = 0x100
CARD_START = 0x100
CARD_SIZE = 0xCC
CARDS = 12
MAX_CARD_ID = 2047

TYPE_NAMES = {0: "vacía", 1: "pokemon", 2: "objeto", 3: "poder"}
CHERISH_BALL = 16
LOVELY_PLACE = 40001   # "Un lugar encantador": lugar de encuentro de casi todos los eventos
CARD_LOCATION = 68     # valor de las tarjetas oficiales de Wi-Fi (sin interpretar)


def _keystream(seed: int, start: int, length: int) -> bytes:
    """Bytes de la clave para el rango [start, start+length) del bloque (start par)."""
    if start % 2 or length % 2:
        raise ValueError("el cifrado trabaja por u16: inicio y longitud deben ser pares")
    for _ in range(start // 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
    out = bytearray()
    for _ in range(length // 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        out += struct.pack("<H", seed >> 16)
    return bytes(out)


def crypt(data: bytes, seed: int, start: int = 0) -> bytes:
    """Cifra o descifra (es la misma operación) `data`, que empieza en `start` dentro del bloque."""
    key = _keystream(seed, start, len(data))
    return bytes(a ^ b for a, b in zip(data, key))


def seed_of(block: bytes) -> int:
    return struct.unpack_from("<I", block, DATA_SIZE)[0]


def decrypt_block(block: bytes) -> bytes:
    """Bloque entero (0xA94) → parte descifrada (0xA90)."""
    if len(block) != BLOCK_SIZE:
        raise ValueError(f"el bloque debe medir {BLOCK_SIZE:#x} bytes")
    return crypt(block[:DATA_SIZE], seed_of(block))


def card_offset(slot: int) -> int:
    if not 0 <= slot < CARDS:
        raise ValueError(f"hueco del álbum fuera de rango (0-{CARDS - 1})")
    return CARD_START + slot * CARD_SIZE


def received_ids(plain: bytes) -> list[int]:
    return [i for i in range(MAX_CARD_ID + 1) if plain[i >> 3] >> (i & 7) & 1]


def _text(raw: bytes) -> str:
    out = []
    for (c,) in struct.iter_unpack("<H", raw):
        if c in (0, 0xFFFF):
            break
        out.append(chr(c))
    return "".join(out)


def _encode(text: str, chars: int) -> bytes:
    """UTF-16 relleno con 0xFFFF, como las tarjetas oficiales."""
    units = [ord(c) for c in text][:chars - 1]
    return struct.pack(f"<{chars}H", *(units + [0xFFFF] * (chars - len(units))))


def summary(card: bytes) -> dict:
    u16 = lambda o: struct.unpack_from("<H", card, o)[0]
    kind = card[0xB3]
    s = {"type": TYPE_NAMES.get(kind, kind), "id": u16(0xB0), "title": _text(card[0x60:0xAA]),
         "date": f"{card[0xAC]:02}/{card[0xAD]:02}/{u16(0xAE)}", "used": bool(card[0xB4] & 2), "b4": card[0xB4]}
    if kind == 1:
        s.update(species=u16(0x1A), level=card[0x5B], egg=bool(card[0x5C]), shiny=card[0x37] == 2,
                 ot=_text(card[0x4A:0x5A]), moves=[u16(0x12 + 2 * i) for i in range(4)], item=u16(0x10))
    elif kind == 2:
        s["item"] = u16(0x00)
    return s


def pokemon_card(species: int, level: int, moves: list[int], *, card_id: int, title: str, ot: str = "Regalo",
                 tid: int = 0, shiny: bool = False, item: int = 0, ball: int = CHERISH_BALL,
                 today: datetime.date | None = None) -> bytes:
    """Tarjeta de Pokémon con los valores de las oficiales: naturaleza, género e IV al azar; idioma y juego del jugador."""
    if not 1 <= level <= 100:
        raise ValueError("nivel 1-100")
    if not 0 <= card_id <= MAX_CARD_ID:
        raise ValueError(f"ID de tarjeta 0-{MAX_CARD_ID}")
    if not 1 <= len(moves) <= 4:
        raise ValueError("de 1 a 4 movimientos")
    today = today or datetime.date.today()
    c = bytearray(CARD_SIZE)
    struct.pack_into("<HH", c, 0x00, tid, 0)       # TID / SID del entrenador del evento
    c[0x0E] = ball
    struct.pack_into("<H", c, 0x10, item)
    struct.pack_into("<4H", c, 0x12, *(list(moves) + [0] * (4 - len(moves))))
    struct.pack_into("<H", c, 0x1A, species)
    c[0x1E:0x34] = b"\xff" * 22                    # sin mote
    c[0x34] = 0xFF                                 # naturaleza al azar
    c[0x35] = 2                                    # género al azar
    c[0x36] = 0                                    # habilidad 1
    c[0x37] = 2 if shiny else 0                    # 2 = siempre variocolor, 0 = nunca
    struct.pack_into("<H", c, 0x3A, LOVELY_PLACE)
    c[0x3C] = level                                # nivel de encuentro
    c[0x43:0x49] = b"\xff" * 6                     # IV al azar
    c[0x4A:0x5A] = _encode(ot, 8)
    c[0x5B] = level
    c[0x60:0xAA] = _encode(title, 37)
    c[0xAC], c[0xAD] = today.day, today.month
    struct.pack_into("<HH", c, 0xAE, today.year, card_id)
    c[0xB2] = CARD_LOCATION
    c[0xB3] = 1                                    # Pokémon
    c[0xB4] = 1                                    # como en los .pgf oficiales
    return bytes(c)


def item_card(item: int, *, card_id: int, title: str, today: datetime.date | None = None) -> bytes:
    today = today or datetime.date.today()
    c = bytearray(CARD_SIZE)
    struct.pack_into("<H", c, 0x00, item)
    c[0x60:0xAA] = _encode(title, 37)
    c[0xAC], c[0xAD] = today.day, today.month
    struct.pack_into("<HH", c, 0xAE, today.year, card_id)
    c[0xB2], c[0xB3], c[0xB4] = CARD_LOCATION, 2, 1
    return bytes(c)


def load_pgf(path: str) -> bytes:
    """Lee un .pgf (0xCC bytes) o un .wc5full (cabecera + PGF al final)."""
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) < CARD_SIZE:
        raise ValueError(f"{path}: demasiado corto para ser una tarjeta ({len(raw)} bytes)")
    card = raw[-CARD_SIZE:] if len(raw) != CARD_SIZE else raw
    if card[0xB3] not in (1, 2, 3):
        raise ValueError(f"{path}: tipo de tarjeta desconocido ({card[0xB3]})")
    return card


def patch(block: bytes, start: int, new_plain: bytes) -> tuple[bytes, bytes]:
    """Para escribir `new_plain` (descifrado) en `start`: devuelve (cifrado actual, cifrado nuevo) de ese rango.
    El rango se alinea a u16."""
    end = start + len(new_plain)
    a, b = start & ~1, (end + 1) & ~1
    seed = seed_of(block)
    plain = bytearray(crypt(block[a:b], seed, a))
    plain[start - a:end - a] = new_plain
    return block[a:b], crypt(bytes(plain), seed, a)


def flag_patch(block: bytes, card_id: int) -> tuple[int, bytes, bytes]:
    """(offset, cifrado actual, cifrado nuevo) para marcar `card_id` como recibido."""
    a = (card_id >> 3) & ~1
    plain = bytearray(crypt(block[a:a + 2], seed_of(block), a))
    plain[(card_id >> 3) - a] |= 1 << (card_id & 7)
    return a, block[a:a + 2], crypt(bytes(plain), seed_of(block), a)


def cards(plain: bytes) -> list[bytes]:
    return [plain[card_offset(i):card_offset(i) + CARD_SIZE] for i in range(CARDS)]


def is_delivered(card: bytes) -> bool:
    return bool(card[0xB4] & 2)


def free_slot(plain: bytes) -> int | None:
    """Primer hueco vacío; si no hay, el de la primera tarjeta ya entregada (el juego deja tirar solo esas).
    None si las 12 están esperando al repartidor."""
    album = cards(plain)
    empty = [i for i, c in enumerate(album) if c[0xB3] == 0]
    if empty:
        return empty[0]
    return next((i for i, c in enumerate(album) if is_delivered(c)), None)


CUSTOM_IDS = range(1500, 2046)   # las oficiales usan IDs bajos (y 2046 el Pase Libertad)


def free_card_id(plain: bytes) -> int:
    """Un ID para una tarjeta propia que no esté recibido ni en el álbum (si se agotan, uno que no esté en el álbum)."""
    received = set(received_ids(plain))
    in_album = {struct.unpack_from("<H", c, 0xB0)[0] for c in cards(plain) if c[0xB3]}
    for pool in (received | in_album, in_album):
        cid = next((i for i in CUSTOM_IDS if i not in pool), None)
        if cid is not None:
            return cid
    raise ValueError("no quedan IDs libres para tarjetas propias")


def set_card_id(card: bytes, card_id: int) -> bytes:
    c = bytearray(card)
    struct.pack_into("<H", c, 0xB0, card_id)
    if c[0xB3] == 1:   # las tarjetas propias usan el ID también como TID del entrenador del evento
        struct.pack_into("<H", c, 0x00, card_id)
    return bytes(c)


def add_card_writes(block: bytes, card: bytes, set_flag: bool = True) -> tuple[int, list[tuple[int, bytes, bytes]]]:
    """Escrituras (offset en el bloque, cifrado actual, cifrado nuevo) para meter `card` en el álbum: la tarjeta en
    el hueco libre y, si set_flag, la bandera de su ID (como hace el juego al recibirla). Devuelve (hueco, escrituras)."""
    plain = decrypt_block(block)
    if card in cards(plain):
        raise ValueError("esa tarjeta ya está en el álbum")
    slot = free_slot(plain)
    if slot is None:
        raise ValueError("el álbum tiene 12 tarjetas sin recoger: recoge alguna con el repartidor")
    o = card_offset(slot)
    old, new = patch(block, o, card)
    writes = [(o, old, new)]
    if set_flag:
        writes.append(flag_patch(block, struct.unpack_from("<H", card, 0xB0)[0]))
    return slot, writes
