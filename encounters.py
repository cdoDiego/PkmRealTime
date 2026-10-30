"""Zona actual y tabla de encuentros salvajes de la zona (EncData de pokebw2, 0xE8 bytes).

Al entrar en una zona el juego copia su tabla de la ROM (a/1/2/7) a la RAM y cada encuentro se sortea leyendo esa copia,
así que cambiarla cambia el siguiente encuentro. Al cambiar de zona el juego carga la suya.
"""
import struct

import gamedata

SIZE = 0xE8
LOADED = 0x80        # bit 7 del byte 7: el juego lo enciende al cargar la tabla; sin él no hay encuentros
SEASONS = ["spring", "summer", "autumn", "winter"]
# (nombre, primer hueco, nº de huecos); la tasa de cada tipo está en el byte de su orden (0 = no hay)
KINDS = [("grass", 0, 12), ("dark_grass", 12, 12), ("shaking_grass", 24, 12), ("surf", 36, 5),
         ("surf_rippling", 41, 5), ("fishing", 46, 5), ("fishing_rippling", 51, 5)]


def place_name(zone: int) -> str:
    zones, places = gamedata.DATA.get("zones", []), gamedata.DATA.get("places", [])
    if not 0 <= zone < len(zones) or not 0 <= zones[zone][0] < len(places):
        return ""
    return places[zones[zone][0]]


def parse(raw: bytes) -> dict:
    """{"loaded": bool, "grass": {"rate", "slots": [{"species", "name", "form", "min", "max"}]}, ...}"""
    species = gamedata.DATA.get("species", {})
    out = {"loaded": bool(raw[7] & LOADED)}
    for i, (kind, first, count) in enumerate(KINDS):
        slots = []
        for s in range(first, first + count):
            v, lo, hi = struct.unpack_from("<HBB", raw, 8 + 4 * s)
            sp = v & 0x7FF
            slots.append({"species": sp, "name": species.get(str(sp), {}).get("name", ""), "form": v >> 11,
                          "min": lo, "max": hi})
        out[kind] = {"rate": raw[i], "slots": slots}
    return out


def rom_table(zone: int, season: int) -> bytes:
    """La tabla de la ROM para la zona y la estación, tal como la deja el juego en RAM (con el bit de cargada), o b"" si
    la zona no tiene encuentros."""
    zones, tables = gamedata.DATA.get("zones", []), gamedata.DATA.get("encounters", [])
    if not 0 <= zone < len(zones) or zones[zone][1] is None or zones[zone][1] >= len(tables):
        return b""
    t = tables[zones[zone][1]]
    raw = bytearray.fromhex(t[season if len(t) > 1 else 0])
    raw[7] |= LOADED
    return bytes(raw)


def parse_location(field: str):
    """Campo del POLL "<zona>:<estación>:<dir. tabla|->:<hex tabla|->" -> (location, dirección, tabla) o (None, 0, b"")."""
    parts = field.split(":")
    if len(parts) != 4 or not parts[0].isdigit():
        return None, 0, b""
    zone, season = int(parts[0]), int(parts[1])
    raw = bytes.fromhex(parts[3]) if parts[3] != "-" else b""
    loc = {"zone": zone, "name": place_name(zone), "season": SEASONS[season] if 0 <= season < 4 else season}
    if len(raw) != SIZE:
        return loc, 0, b""
    return loc, int(parts[2], 16), raw
