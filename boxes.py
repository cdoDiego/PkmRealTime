"""Cajas del PC (bloques 0-24 del save): el bloque 0 tiene los nombres, la caja abierta y cuántas hay; cada caja son 30
Pokémon de 136 bytes. El Lua manda en cada lectura el bloque 0, la caja abierta y otra caja por turnos."""
import functools

import gift
import pk5

MAIN_SIZE = 0x3E0
NAMES_OFF, NAME_STRIDE = 0x04, 0x28
CURRENT_OFF, COUNT_OFF = 0x3DC, 0x3DD
SLOTS, SLOT_SIZE = 30, 136
BOX_SIZE = SLOTS * SLOT_SIZE
STRIDE = 0x1000              # distancia entre cajas en la RAM (caja n = caja 1 + n * 0x1000)
MAX_BOXES = 24


def parse_field(field: str):
    """"<hex bloque 0>|<n>:<hex>|..." -> (bloque 0, {nº de caja desde 0: datos}) o (b"", {}) si no viene."""
    parts = field.split("|")
    main = bytes.fromhex(parts[0]) if parts[0] not in ("", "-") else b""
    if len(main) != MAIN_SIZE:
        return b"", {}
    found = {}
    for p in parts[1:]:
        n, _, hexdata = p.partition(":")
        raw = bytes.fromhex(hexdata)
        if n.isdigit() and int(n) < MAX_BOXES and len(raw) == BOX_SIZE:
            found[int(n)] = raw
    return main, found


def name(main: bytes, box: int) -> str:
    raw = main[NAMES_OFF + box * NAME_STRIDE:NAMES_OFF + (box + 1) * NAME_STRIDE]
    chars = []
    for i in range(0, len(raw), 2):
        c = raw[i] | raw[i + 1] << 8
        if c == 0xFFFF:
            break
        chars.append(chr(c))
    return "".join(chars)


def current(main: bytes) -> int:
    return main[CURRENT_OFF]


def count(main: bytes) -> int:
    n = main[COUNT_OFF]
    return n if 1 <= n <= MAX_BOXES else MAX_BOXES


@functools.lru_cache(maxsize=2048)
def _slot_info(chunk: bytes):
    """Resumen de un Pokémon de caja (None = hueco vacío). Con memoria: solo se recalcula si cambian sus bytes."""
    if gift.is_empty_slot(chunk):
        return None
    try:
        info = gift.summary(pk5.decrypt_ro(chunk))
        return {k: info[k] for k in ("species", "name", "level", "valid")}
    except (ValueError, IndexError, KeyError, StopIteration):   # datos raros: se marcan, no se tumba el puente
        return {"valid": False}


def summary(raw: bytes) -> list:
    """Los Pokémon de una caja: [{"slot", "species", "name", "level", "valid"}] (huecos vacíos fuera)."""
    out = []
    for i in range(SLOTS):
        info = _slot_info(bytes(raw[i * SLOT_SIZE:(i + 1) * SLOT_SIZE]))
        if info is not None:
            out.append({"slot": i, **info})
    return out
