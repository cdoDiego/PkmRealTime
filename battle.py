"""Estructura de combate de B2/W2 (fase 5): lectura y escrituras de prueba.

Fuente de los offsets: NDS Ironmon Tracker (BattleHandlerGen5.lua) + volcado en combate (combate1, 27-oct).
Cada combatiente tiene DOS copias con el mismo formato:
  - copia visual  (tabla en puntero + 0x526A8, la que lee el tracker): la barra de vida se anima hacia ella
  - copia real    (tabla en puntero + 0x52790): con ella el juego calcula el daño y decide si se debilita
Cada tabla: 6 punteros del jugador + contador, y desde +0x1C los del rival + contador.
Cada uno apunta a una estructura de combatiente, sin cifrar:
  +0x00 puntero al Pokémon (PK5 cifrado, 220 bytes)   +0x04 puntero de Ilusión
  +0x0E HP máximo (u16)   +0x10 HP actual (u16)   +0x18 nivel (u8)   +0x20 estado (u32)
  +0xEE Atq, Def, AtE, DfE, Vel (u16)   +0xFC cambios de estadísticas
  +0x104 movimientos: 4 × 14 bytes (u16 movimiento, u8 PP, ...)
"""
import struct

import gamedata
import pk5

OFF_MAX_HP, OFF_HP, OFF_LEVEL, OFF_STATUS = 0x0E, 0x10, 0x18, 0x20
OFF_STATS, OFF_STAGES, OFF_MOVES, MOVE_STRIDE = 0xEE, 0xFC, 0x104, 14


# Bytes crudos del último POLL: {("player"|"enemy", índice, "real"|"visual"): (dirección, estructura)}
RAW: dict = {}


def parse(field: str) -> dict:
    """field = "T:<tabla>,p0:<dir>:<estructura>:<pk5>,e0:..." enviado por connector.lua en combate."""
    out = {"player": [], "enemy": [], "table": ""}
    RAW.clear()
    if field in ("", "-"):
        return out
    for part in field.split(","):
        bits = part.split(":")
        if bits[0] == "T":
            out["table"] = bits[1]
            continue
        side, idx, addr, raw, mon = bits[0][0], int(bits[0][1:]), int(bits[1], 16), bytes.fromhex(bits[2]), bits[3]
        name = "player" if side in "pP" else "enemy"
        copy = "real" if side.isupper() else "visual"
        RAW[(name, idx, copy)] = (addr, raw)
        if copy == "real":                       # se muestra la copia real; de la visual, solo su vida
            out[name].append(describe(idx, addr, raw, mon))
    for name in ("player", "enemy"):
        for info in out[name]:
            vis = RAW.get((name, info["index"], "visual"))
            info["hp_visual"] = struct.unpack_from("<H", vis[1], OFF_HP)[0] if vis else None
        out[name].sort(key=lambda i: i["index"])
    return out


def describe(idx: int, addr: int, raw: bytes, mon_hex: str) -> dict:
    u16 = lambda o: struct.unpack_from("<H", raw, o)[0]
    names = gamedata.DATA.get("moves", [])
    info = {
        "index": idx, "addr": f"{addr:#010x}",
        "hp": u16(OFF_HP), "max_hp": u16(OFF_MAX_HP), "level": raw[OFF_LEVEL],
        "status_raw": struct.unpack_from("<I", raw, OFF_STATUS)[0],
        "conditions": status_names(raw),
        "stats": dict(zip(("atk", "def", "spa", "spd", "spe"), struct.unpack_from("<5H", raw, OFF_STATS))),
        "stages": list(raw[OFF_STAGES:OFF_STAGES + 8]),
        "moves": [],
    }
    for i in range(4):
        move, pp = struct.unpack_from("<HB", raw, OFF_MOVES + MOVE_STRIDE * i)
        if move:
            info["moves"].append({"id": move, "name": names[move] if move < len(names) else "?", "pp": pp})
    if mon_hex not in ("", "-"):
        plain = pk5.decrypt(bytes.fromhex(mon_hex))
        s = pk5.summary(plain)
        sp = s["species"]
        info.update(species=sp, valid=s["valid"],
                    name=gamedata.DATA.get("species", {}).get(str(sp), {}).get("name", "?"))
    return info


# Estado en combate (validado 27-oct con una quemadura): lista de entradas u32 desde +0x1C, una por condición,
# índice = número del estado de Gen 5 (1 parálisis, 2 sueño, 3 congelado, 4 quemado, 5 envenenado).
# Valor 0 = no la tiene; 1 = permanente. Onda Trueno dejó 1 en +0x20 (entrada de parálisis), y escribir 4 ahí
# no quemó (solo cambió la "duración" de la parálisis). El sueño queda fuera hasta saber cómo guarda los turnos.
OFF_SICK = 0x1C
SICK_INDEX = {"paralysis": 1, "freeze": 3, "burn": 4, "poison": 5}
BLOCK = slice(OFF_SICK + 4, OFF_SICK + 4 * 6)        # entradas 1..5 (+0x20..+0x33)


def status_names(raw: bytes) -> list[str]:
    names = {1: "paralysis", 2: "sleep", 3: "freeze", 4: "burn", 5: "poison"}
    return [n for i, n in names.items() if struct.unpack_from("<I", raw, OFF_SICK + 4 * i)[0]]


def _both(side: str, index: int):
    for copy in ("real", "visual"):
        if (side, index, copy) not in RAW:
            raise ValueError(f"no hay combatiente {side} {index} ({copy}) en este combate")
        yield RAW[(side, index, copy)]


def set_status_command(side: str, index: int, status: str) -> str:
    """Comandos G que dejan solo esa condición principal (o ninguna) en las dos copias."""
    if status != "none" and status not in SICK_INDEX:
        raise ValueError(f"estado no soportado en combate: {status} (válidos: none, {', '.join(SICK_INDEX)})")
    new = bytearray(BLOCK.stop - BLOCK.start)
    if status != "none":
        struct.pack_into("<I", new, 4 * (SICK_INDEX[status] - 1), 1)
    return ";".join(f"G {addr + BLOCK.start:#x} {raw[BLOCK].hex()} {new.hex()}" for addr, raw in _both(side, index))


def set_hp_command(side: str, index: int, hp: int) -> str:
    """Comandos G que cambian la vida en las dos copias (solo si no cambiaron desde la última lectura)."""
    cmds = []
    for copy in ("real", "visual"):
        if (side, index, copy) not in RAW:
            raise ValueError(f"no hay combatiente {side} {index} ({copy}) en este combate")
        addr, raw = RAW[(side, index, copy)]
        max_hp = struct.unpack_from("<H", raw, OFF_MAX_HP)[0]
        new = max(0, min(hp, max_hp))
        cmds.append(f"G {addr + OFF_HP:#x} {raw[OFF_HP:OFF_HP + 2].hex()} {struct.pack('<H', new).hex()}")
    return ";".join(cmds)
