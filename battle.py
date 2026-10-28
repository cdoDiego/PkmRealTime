"""Estructura de combate de B2/W2 (fase 5): lectura y escrituras de prueba.

Fuente de los offsets: NDS Ironmon Tracker (BattleHandlerGen5.lua) + volcado en combate (combate1, 27-oct).
Cada combatiente tiene DOS copias con el mismo formato:
  - copia visual  (tabla en puntero + 0x526A8, la que lee el tracker): la barra de vida se anima hacia ella
  - copia real    (tabla en puntero + 0x52790): con ella el juego calcula el daño y decide si se debilita
Cada tabla: 6 punteros del jugador + contador, y desde +0x1C los del rival + contador.
Cada uno apunta a una estructura de combatiente, sin cifrar:
  +0x00 puntero al Pokémon (PK5 cifrado, 220 bytes)   +0x04 puntero de Ilusión
  +0x0C especie (u16)   +0x16 habilidad   +0x19 identificador en combate (pokeID)
  +0x0E HP máximo (u16)   +0x10 HP actual (u16)   +0x18 nivel (u8)   +0x20 estado (u32)
  +0xEE Atq, Def, AtE, DfE, Vel (u16)   +0xFC cambios de estadísticas (7 bytes, 6 = sin cambio)
  +0x104 movimientos: 4 × 14 bytes (u16 movimiento, u8 PP, ...)
"""
import struct

import battle_cmd
import gamedata
import pk5

OFF_MAX_HP, OFF_HP, OFF_LEVEL, OFF_STATUS = 0x0E, 0x10, 0x18, 0x20
OFF_STATS, OFF_STAGES, OFF_MOVES, MOVE_STRIDE = 0xEE, 0xFC, 0x104, 14

# Cambios de estadísticas: 7 bytes desde +0xFC, 6 = sin cambio (rango 0-12 → -6..+6).
# Validados en el juego: atk (Gruñido) y def (Malicioso, Látigo). El resto sigue el orden de las estadísticas.
STAGE_NAMES = ("atk", "def", "spa", "spd", "spe", "acc", "eva")


def stages(raw: bytes) -> dict:
    """{"atk": 0, "def": -1, ...}: niveles de subida (+) o bajada (-) respecto a lo normal."""
    return {name: raw[OFF_STAGES + i] - 6 for i, name in enumerate(STAGE_NAMES)}


# Clima del combate: sField de btl_field.c (u32 clima, u32 turnos; 0xFF = sin fin). Números de ConvFieldWeatherToBtl
# (field_encount.c) y validados en el juego: el clima 3 del mapa (arena) entra al combate como 4, y el 4 (nieve fuerte)
# como 3, que hizo daño de granizo. El 1 es el sol. Sin clima = 0, 0xFF.
WEATHER_IDS = {"none": 0, "sun": 1, "rain": 2, "hail": 3, "sandstorm": 4}
WEATHER_NAMES = {v: k for k, v in WEATHER_IDS.items()}
WEATHER_RAW: dict = {}
WEATHER_ADDR = 0x021DD928          # White 2 (IRDO); el Lua lo manda como "W:"


def set_weather_command(weather: str, turns=None) -> str:
    """Cambia el clima del combate (G con guarda) y lo muestra con WEATHER_START / WEATHER_END, como el juego."""
    if weather not in WEATHER_IDS:
        raise ValueError(f"clima desconocido: {weather} (válidos: {', '.join(WEATHER_IDS)})")
    if "raw" not in WEATHER_RAW:
        raise ValueError("no se ha leído el clima de este combate todavía")
    old = WEATHER_RAW["raw"]
    old_weather = struct.unpack_from("<I", old)[0]
    w = WEATHER_IDS[weather]
    if w == 0:
        if turns is not None:
            raise ValueError("turns no se usa con none")
        new = struct.pack("<II", 0, 0xFF)
        show = battle_cmd.encode("WEATHER_END", old_weather) if old_weather else b""
    else:
        t = 0xFF if turns is None else int(turns)
        if not (1 <= t <= 254 or t == 0xFF):
            raise ValueError("turns debe ir de 1 a 254 (sin turns = sin fin)")
        new = struct.pack("<II", w, t)
        show = battle_cmd.encode("WEATHER_START", w, t)
    cmd = f"G {WEATHER_ADDR:#x} {old.hex()} {new.hex()}"
    return cmd + (f";J {show.hex()}" if show else "")


# Bytes crudos del último POLL: {("player"|"enemy", índice, "real"|"visual"): (dirección, estructura)}
RAW: dict = {}


def parse(field: str) -> dict:
    """field = "T:<tabla>,p0:<dir>:<estructura>:<pk5>,e0:..." enviado por connector.lua en combate."""
    out = {"player": [], "enemy": [], "table": ""}
    WEATHER_RAW.clear()
    RAW.clear()
    if field in ("", "-"):
        return out
    for part in field.split(","):
        bits = part.split(":")
        if bits[0] == "W":                      # clima del combate: u32 clima, u32 turnos (255 = sin fin)
            raw = bytes.fromhex(bits[1])
            WEATHER_RAW["raw"] = raw
            w, turns = struct.unpack("<II", raw)
            out["weather"] = {"weather": WEATHER_NAMES.get(w, w), "turns": None if turns == 0xFF else turns}
            continue
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
        "index": idx, "addr": f"{addr:#010x}", "poke_id": raw[0x19],
        "hp": u16(OFF_HP), "max_hp": u16(OFF_MAX_HP), "level": raw[OFF_LEVEL],
        "status_raw": struct.unpack_from("<I", raw, OFF_STATUS)[0],
        "conditions": status_names(raw),
        "stats": dict(zip(("atk", "def", "spa", "spd", "spe"), struct.unpack_from("<5H", raw, OFF_STATS))),
        "stages": stages(raw),
        "moves": [],
    }
    for i in range(4):
        move, pp, max_pp = struct.unpack_from("<HBB", raw, OFF_MOVES + MOVE_STRIDE * i)
        if move:
            info["moves"].append({"id": move, "name": names[move] if move < len(names) else "?", "pp": pp, "max_pp": max_pp})
    if mon_hex not in ("", "-"):
        plain = pk5.decrypt(bytes.fromhex(mon_hex))
        s = pk5.summary(plain)
        sp = s["species"]
        abilities = gamedata.DATA.get("abilities", [])
        info.update(species=sp, valid=s["valid"],
                    name=gamedata.DATA.get("species", {}).get(str(sp), {}).get("name", "?"),
                    shiny=s["shiny"], gender=s["gender"], form=s["form"], hidden_ability=s["hidden_ability"],
                    ability=abilities[s["ability"]] if s["ability"] < len(abilities) else s["ability"])
    return info


# Estado en combate (validado 27-oct): 36 condiciones u32 desde +0x1C (BattleMonCore.conditions en pokebw2),
# índice = número del estado de Gen 5 (1 parálisis, 2 sueño, 3 congelado, 4 quemado, 5 envenenado), y desde +0xAC
# un contador u8 por condición (conditionCounters). Cada condición (src/ov167/battle_condition.c):
#   bits 0-2 tipo (0 = no la tiene, 1 = permanente, 2 = dura unos turnos), bits 3-8 turnos.
# Sueño: tipo 2 y los turnos; el contador sube cada vez que intenta atacar y despierta (y ataca) al llegar a esos turnos
# (BattleMon_TickSleep). Validado 27-oct: con 3 durmió 2 turnos y atacó en el tercero, así que se guarda turns + 1.
# Envenenamiento grave: tipo 1 y turnos 15 (MakeConditionBadlyPoisoned); daño = 1/16 × contador, que sube cada turno.
OFF_SICK, OFF_COUNTERS = 0x1C, 0xAC
SICK_INDEX = {"paralysis": 1, "sleep": 2, "freeze": 3, "burn": 4, "poison": 5, "toxic": 5}
BLOCK = slice(OFF_SICK + 4, OFF_SICK + 4 * 6)        # entradas 1..5 (+0x20..+0x33)
COUNTERS = slice(OFF_COUNTERS + 1, OFF_COUNTERS + 6)  # sus contadores (+0xAD..+0xB1)
SLEEP_TURNS = 3                                       # turnos sin atacar por defecto; el juego elige entre 1 y 3
TOXIC = 1 | (15 << 3)


def condition_value(status: str, turns=None) -> int:
    if status == "sleep":
        turns = SLEEP_TURNS if turns is None else int(turns)
        if not 1 <= turns <= 6:
            raise ValueError("turns (sueño) debe ir de 1 a 6")
        return 2 | ((turns + 1) << 3)
    if turns is not None:
        raise ValueError("turns solo se usa con sleep")
    return TOXIC if status == "toxic" else 1


def status_names(raw: bytes) -> list[str]:
    names = {1: "paralysis", 2: "sleep", 3: "freeze", 4: "burn", 5: "poison"}
    out = []
    for i, n in names.items():
        value = struct.unpack_from("<I", raw, OFF_SICK + 4 * i)[0]
        if value & 7:
            if i == 2:
                n = f"sleep (quedan {max(0, ((value >> 3) & 0x3F) - 1 - raw[OFF_COUNTERS + 2])} turnos)"
            elif i == 5 and value & 0x1FF == TOXIC:
                n = f"toxic (turno {raw[OFF_COUNTERS + 5]})"
            out.append(n)
    return out


def _both(side: str, index: int):
    for copy in ("real", "visual"):
        if (side, index, copy) not in RAW:
            raise ValueError(f"no hay combatiente {side} {index} ({copy}) en este combate")
        yield RAW[(side, index, copy)]


def poke_id(side: str, index: int) -> int:
    """Identificador del combatiente para los comandos de pantalla (byte +0x19 de la copia real)."""
    _, raw = RAW[(side, index, "real")]
    return raw[0x19]


def show_hp_command(side: str, index: int) -> str:
    """Comando J: anima la barra de vida hacia la vida de la copia visual (al reproducirse el turno)."""
    return "J " + battle_cmd.encode("UPDATE_HP_GAUGE", poke_id(side, index)).hex()


def show_status_command(side: str, index: int, status: str) -> str:
    """Comando J: pone el ícono de estado (y el color) del combatiente.

    El valor es el número del estado; el envenenamiento grave tiene su propio ícono (PSN en morado) con el 6
    (ServerControl_SetCondition en btl_server_flow.c: CONDITION_POISON + 1).
    """
    value = 0 if status == "none" else 6 if status == "toxic" else SICK_INDEX[status]
    return "J " + battle_cmd.encode("SET_GAUGE_STATUS", poke_id(side, index), value).hex()


def set_status_command(side: str, index: int, status: str, turns=None) -> str:
    """Comandos G que dejan solo esa condición principal (o ninguna) en las dos copias, con sus contadores a 0."""
    if status != "none" and status not in SICK_INDEX:
        raise ValueError(f"estado no soportado en combate: {status} (válidos: none, {', '.join(SICK_INDEX)})")
    new = bytearray(BLOCK.stop - BLOCK.start)
    if status != "none":
        struct.pack_into("<I", new, 4 * (SICK_INDEX[status] - 1), condition_value(status, turns))
    elif turns is not None:
        raise ValueError("turns solo se usa con sleep")
    zero = bytes(COUNTERS.stop - COUNTERS.start)
    cmds = []
    for addr, raw in _both(side, index):
        cmds.append(f"G {addr + BLOCK.start:#x} {raw[BLOCK].hex()} {new.hex()}")
        cmds.append(f"G {addr + COUNTERS.start:#x} {raw[COUNTERS].hex()} {zero.hex()}")
    return ";".join(cmds)


def set_stage_command(side: str, index: int, stat: str, stage=None, delta=None) -> str:
    """Comandos G que fijan (stage, -6..+6) o suman (delta) niveles a una estadística, en las dos copias."""
    if stat not in STAGE_NAMES:
        raise ValueError(f"estadística desconocida: {stat} (válidas: {', '.join(STAGE_NAMES)})")
    if (stage is None) == (delta is None):
        raise ValueError("indica 'stage' (valor final, -6..+6) o 'delta' (cuánto subir o bajar), no los dos")
    off = OFF_STAGES + STAGE_NAMES.index(stat)
    cmds = []
    for addr, raw in _both(side, index):
        value = stage if stage is not None else raw[off] - 6 + delta
        new = max(-6, min(6, int(value))) + 6
        cmds.append(f"G {addr + off:#x} {raw[off]:02x} {new:02x}")
    return ";".join(cmds)


# Movimiento en combate (14 bytes): u16 movimiento, u8 PP, u8 PP máx, 2 bytes, y una copia de respaldo
# de esos 6 bytes en +6 (para volver tras Transformación/Mimético). Se escriben los PP en las dos.
MOVE_PP, MOVE_MAX_PP, MOVE_BACKUP = 2, 3, 6


def set_pp_command(side: str, index: int, move_slot: int, pp=None) -> str:
    """Comandos G que ponen los PP de un movimiento (None = al máximo), en las dos copias."""
    if not 0 <= move_slot <= 3:
        raise ValueError(f"hueco de movimiento fuera de rango (0-3): {move_slot}")
    cmds = []
    for addr, raw in _both(side, index):
        base = OFF_MOVES + MOVE_STRIDE * move_slot
        if struct.unpack_from("<H", raw, base)[0] == 0:
            raise ValueError(f"el hueco {move_slot} no tiene movimiento")
        value = raw[base + MOVE_MAX_PP] if pp is None else max(0, min(int(pp), raw[base + MOVE_MAX_PP]))
        for off in (base + MOVE_PP, base + MOVE_BACKUP + MOVE_PP):
            cmds.append(f"G {addr + off:#x} {raw[off]:02x} {value:02x}")
    return ";".join(cmds)


def set_hp_command(side: str, index: int, hp: int) -> str:
    """Comandos que cambian la vida en las dos copias (G: solo si no cambiaron desde la última lectura).

    Vida 0: escrita directamente, el juego no debilita al Pokémon. Solo lo hace ServerControl_CheckFainted,
    que no revisa a los que ya tienen 0 (si es el tuyo, el rival se queda atacando en bucle). Por eso la copia
    real queda a 1 y "F <dir>" pide al Lua que la ponga a 0 justo cuando el juego vaya a revisarla: así se
    debilita con su mensaje, experiencia y cambio de Pokémon. La copia visual pasa a 0 para vaciar la barra.
    """
    cmds = []
    for copy in ("real", "visual"):
        if (side, index, copy) not in RAW:
            raise ValueError(f"no hay combatiente {side} {index} ({copy}) en este combate")
        addr, raw = RAW[(side, index, copy)]
        max_hp = struct.unpack_from("<H", raw, OFF_MAX_HP)[0]
        new = max(0, min(hp, max_hp))
        if new == 0 and copy == "real":
            if struct.unpack_from("<H", raw, OFF_HP)[0] == 0:
                raise ValueError("ese Pokémon ya está debilitado")
            cmds.insert(0, f"F {addr:#x}")        # primero: si el Lua no puede, no se escribe nada
            new = 1
        cmds.append(f"G {addr + OFF_HP:#x} {raw[OFF_HP:OFF_HP + 2].hex()} {struct.pack('<H', new).hex()}")
    return ";".join(cmds)
