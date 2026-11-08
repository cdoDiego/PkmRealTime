"""Guiones propios del mapa (combate salvaje, contra entrenador, clima) para B2/W2.

El Lua (comando S) hace que el juego ejecute estos bytes como su "guion reservado" en cuanto el personaje queda
libre. Formato de los guiones de Gen 5: cada orden es un u16 (little-endian) y sus argumentos u16; los valores por
debajo de 0x4000 son constantes (por encima serían variables). Órdenes de la decompilación pokebw2
(src/ov036/scrcmd_encount.c, scrcmd_trainer.c; src/ov012/scrcmd_weather.c, scrcmd_vm.c).
"""
import struct

import gamedata

CMD_END = 0x0002                    # s0002_VMHalt
CMD_CMP_CONST = 0x0019              # s0019_WorkCmpConst(variable, valor)
CMD_JUMP_IF = 0x001F                # s001F_VMJumpIf(condición u8, salto u32 desde el final de la orden)
COND_EQUAL = 1                      # VM_CMP_LUT: 0 menor, 1 igual, 2 mayor
TEMP_VAR = 0x8000                   # variable temporal de los guiones
CMD_WILD_BATTLE = 0x0174            # s0174_CallWildBattle(especie, nivel, opciones)
CMD_WILD_BATTLE_EX = 0x0297         # s0297_CallWildBattleEx(especie, nivel, forma, opciones)
# Opciones de EventWildBattleCall_CreateStatic (src/ov036/field_encount.c). Los significados marcados con "?" faltan
# por confirmar en el juego.
WILD_SHINY = 0x02                   # shinyLock = 1: variocolor (?; con 0x10 no salió variocolor, 27-oct)
WILD_NOT_SHINY = 0x10               # shinyLock = 2: nunca variocolor (?)
WILD_HIDDEN_ABILITY = 0x08          # (?)
WILD_SEX = {"male": 0x20, "macho": 0x20, "female": 0x40, "hembra": 0x40}   # 0x40 = hembra validado 27-oct
WILD_NO_FLEE = 0x01                 # BtlSetup flag 4: no se puede huir (validado 27-oct)
CMD_WILD_BATTLE_END = 0x0175        # s0175_CallWildBattleEnd: vuelve al mapa con su transición
CMD_WILD_LOSE = 0x0176              # s0176_CallWildLose: derrota (al Centro Pokémon) y fin del guion
CMD_WILD_IS_VICTORY = 0x0177        # s0177_WildBattleIsVictory(variable): 1 si no perdió
CMD_TRAINER_BATTLE = 0x0085         # s0085_CallTrainerBattle(entrenador 1, entrenador 2, opciones)
CMD_TRAINER_LOSE = 0x008C           # s008C_CallTrainerLose
CMD_TRAINER_IS_VICTORY = 0x008D     # s008D_TrainerBattleIsVictory(variable)
CMD_TRAINER_BATTLE_END = 0x008E     # s008E_CallTrainerBattleEnd
CMD_FIELD_WEATHER = 0x0136          # s0136_FieldSetWeather(clima, inmediato)
CMD_FLY_WARP = 0x028A               # s028A_MapChangeFlyWarp(zona, dirección): al punto de aterrizaje de la zona (src/ov036/scrcmd_mapchange.c)
CMD_WARP = 0x00C2                   # s00C2_MapChangeWarp(zona, x, z, dirección): a una casilla concreta
DIR_DOWN = 1
CMD_PARTY_ADD_EX = 0x010E           # s010E_PokePartyAddEx(resultado, especie, forma, nivel, habilidad, sexo, param1C, objeto, ball)
CMD_PARTY_ADD_EGG = 0x010F          # s010F_PokePartyAddEgg(resultado, especie, forma): huevo al equipo (nada si está lleno)
CMD_BOX_ADD_EX = 0x0123             # s0123_BoxAddEx: lo mismo, a la primera caja con sitio (src/ov012/scrcmd_pokemon.c)
# habilidad: 2 = la normal al azar, 3 = la oculta · sexo: 0 macho, 1 hembra, 2 al azar · param1C: 2 = lo normal
# (sin nombre en la decompilación: es el variocolor, 1 = sí, validado 27-oct) · ball: 4 = Poké Ball

# Zonas de las ciudades (mainZoneId de RESPAWN_ZONE_INFO en src/ov012/respawn_zone.c: los destinos de Vuelo)
CITIES = {
    "aspertia": 427, "virbank": 448, "castelia": 28, "nimbasa": 62, "driftveil": 96, "mistralton": 107,
    "icirrus": 113, "opelucid": 120, "lacunosa": 406, "undella": 412, "humilau": 465, "nacrene": 16,
    "striaton": 6, "accumula": 397, "nuvema": 389, "pokemon_league": 136, "victory_road": 573,
    "black_city": 0, "white_forest": 424,
}

# Clima del mapa (FieldWeather). Al empezar un combate se convierte (ConvFieldWeatherToBtl en field_encount.c):
# 2, 6, 7 → lluvia; 3, 12 → arena; 4, 5 → granizo; el resto, sin clima en combate. Todos vistos en el juego (27-oct).
FIELD_WEATHER = {
    "none": 0, "snow": 1, "rain": 2, "sandstorm": 3, "hail": 4, "blizzard": 5, "heavy_rain": 6, "rain_streaks": 7,
    "diamond_dust": 8, "fog": 9, "overcast": 10, "light_fog": 11, "heavy_sandstorm": 12, "overcast2": 13,
    "zone": 0xFFFF,   # el clima normal de la ruta
}


def _words(*values: int) -> str:
    for v in values:
        if not 0 <= v < 0x4000 and v != 0xFFFF and not TEMP_VAR <= v < TEMP_VAR + 4:
            raise ValueError(f"valor fuera de rango para un guion: {v}")
    return struct.pack(f"<{len(values)}H", *values).hex()


def _after_battle(is_victory: int, lose: int, end: int) -> str:
    """Como los guiones del juego: si perdió, la derrota (el juego ya no la hace solo en combates de guion: si se
    intenta volver al mapa tras perder, se cuelga, visto el 27-oct); si no, vuelta al mapa."""
    return (_words(is_victory, TEMP_VAR, CMD_CMP_CONST, TEMP_VAR, 1)
            + struct.pack("<HBI", CMD_JUMP_IF, COND_EQUAL, 2).hex()   # si ganó, se salta la orden de derrota (2 bytes)
            + _words(lose, end, CMD_END))


def wild_battle(species: int, level: int, form: int = 0, shiny=None, hidden_ability: bool = False, gender=None,
                no_flee: bool = False) -> str:
    """shiny: True = variocolor, False = nunca, None = como siempre (al azar)."""
    max_species = gamedata.max_species()
    if not 1 <= species <= max_species:
        raise ValueError(f"especie fuera de rango: {species} (1-{max_species})")
    if not 1 <= level <= 100:
        raise ValueError("el nivel debe ir de 1 a 100")
    if not 0 <= form < 32:
        raise ValueError("forma fuera de rango (0-31)")
    flags = {True: WILD_SHINY, False: WILD_NOT_SHINY, None: 0}[shiny]
    if hidden_ability:
        flags |= WILD_HIDDEN_ABILITY
    if gender is not None:
        if gender not in WILD_SEX:
            raise ValueError("gender: male/macho o female/hembra")
        flags |= WILD_SEX[gender]
    if no_flee:
        flags |= WILD_NO_FLEE
    return (_words(CMD_WILD_BATTLE_EX, species, level, form, flags)
            + _after_battle(CMD_WILD_IS_VICTORY, CMD_WILD_LOSE, CMD_WILD_BATTLE_END))


STYLE_SINGLE, STYLE_DOUBLE = 0, 1   # estilo de combate del entrenador (TRAINER_PARAM_BATTLE_STYLE)


def trainer_battle(trainer: int, trainer2: int = 0) -> str:
    """El tipo de combate lo decide el juego por el estilo del primer entrenador (BtlSetup_SetTrainerLocal en
    src/ov036/field_encount.c): uno doble (o triple, rotatorio) lucha así solo; con un segundo entrenador y el primero
    individual es un combate doble contra los dos a la vez (BtlSetup_SetTrainer1v2), como cuando te ven dos juntos."""
    trainers = gamedata.DATA.get("trainers")
    if not trainers:
        raise ValueError("faltan los entrenadores en gen5_data.json: reinicia el puente con ROM_PATH configurado")
    for t in (trainer, trainer2) if trainer2 else (trainer,):
        if not 1 <= t < len(trainers) or trainers[t][2] == 0:
            raise ValueError(f"entrenador no válido: {t} (1-{len(trainers) - 1}, con Pokémon)")
    if trainer2 and trainers[trainer][1] != STYLE_SINGLE:
        raise ValueError(f"el entrenador {trainer} ya es de combate {trainer_info(trainer)['battle_type']}: "
                         "con un segundo entrenador, el primero debe ser individual")
    return _words(CMD_TRAINER_BATTLE, trainer, trainer2, 0) + _after_battle(CMD_TRAINER_IS_VICTORY, CMD_TRAINER_LOSE,
                                                                           CMD_TRAINER_BATTLE_END)


def party_needed(trainer: int, trainer2: int = 0) -> int:
    """Pokémon que hay que tener en condiciones de luchar: 2 en un combate doble, 3 en uno triple o rotatorio."""
    style = gamedata.DATA["trainers"][trainer][1]
    if trainer2 or style == STYLE_DOUBLE:
        return 2
    return 3 if style in (2, 3) else 1


def field_weather(weather) -> str:
    if isinstance(weather, str):
        if weather not in FIELD_WEATHER:
            raise ValueError(f"clima desconocido: {weather} (válidos: {', '.join(FIELD_WEATHER)} o un número)")
        weather = FIELD_WEATHER[weather]
    return _words(CMD_FIELD_WEATHER, int(weather), 1, CMD_END)


def give_pokemon(species: int, level: int, form: int = 0, hidden_ability: bool = False, gender=None, item: int = 0,
                 ball: int = 4, shiny: bool = False) -> str:
    """Al equipo con la orden del juego (lo crea el juego: entrenador, lugar, Pokédex); si está lleno, a una caja."""
    max_species = gamedata.max_species()
    if not 1 <= species <= max_species:
        raise ValueError(f"especie fuera de rango: {species} (1-{max_species})")
    if not 1 <= level <= 100:
        raise ValueError("el nivel debe ir de 1 a 100")
    sex = {None: 2, "male": 0, "macho": 0, "female": 1, "hembra": 1}.get(gender)
    if sex is None:
        raise ValueError("gender: male/macho o female/hembra")
    if not 0 <= item <= 638 or not 1 <= ball <= 25:
        raise ValueError("objeto (0-638) o ball (1-25) fuera de rango")
    args = (TEMP_VAR, species, form, level, 3 if hidden_ability else 2, sex, 1 if shiny else 2, item, ball)
    # si el equipo estaba lleno (resultado 0), a la caja; si no, se salta esa orden (2 + 9 × 2 = 20 bytes)
    return (_words(CMD_PARTY_ADD_EX, *args, CMD_CMP_CONST, TEMP_VAR, 1)
            + struct.pack("<HBI", CMD_JUMP_IF, COND_EQUAL, 20).hex()
            + _words(CMD_BOX_ADD_EX, *args, CMD_END))


def teleport(zone, x=None, z=None) -> str:
    """Sin x/z: al punto de aterrizaje de la zona (como Vuelo). Con x y z: a esa casilla de la zona."""
    if isinstance(zone, str) and not zone.isdigit():
        if zone not in CITIES:
            raise ValueError(f"ciudad desconocida: {zone} (válidas: {', '.join(CITIES)} o un número de zona)")
        zone = CITIES[zone]
    zone = int(zone)
    if not 0 <= zone < 700:
        raise ValueError("zona fuera de rango (0-699)")
    if x is None and z is None:
        return _words(CMD_FLY_WARP, zone, DIR_DOWN, CMD_END)
    if x is None or z is None:
        raise ValueError("para una casilla hacen falta x y z")
    return _words(CMD_WARP, zone, int(x), int(z), DIR_DOWN, CMD_END)


def trainer_info(trainer: int) -> dict:
    t = gamedata.DATA["trainers"][trainer]
    classes = gamedata.DATA.get("trainer_classes", [])
    return {"id": trainer, "class": classes[t[0]] if t[0] < len(classes) else t[0],
            "battle_type": ("individual", "doble", "triple", "rotatorio")[t[1]] if t[1] < 4 else t[1], "pokemon": t[2]}


def give_egg(species: int, form: int = 0) -> str:
    """Huevo al equipo con la orden del juego: tu nombre de entrenador, los ciclos normales para eclosionar y el origen
    de un huevo. Si el equipo está lleno, el juego no lo crea (no hay versión para la caja)."""
    max_species = gamedata.max_species()
    if not 1 <= species <= max_species:
        raise ValueError(f"especie fuera de rango: {species} (1-{max_species})")
    if not 0 <= form < 32:
        raise ValueError("forma fuera de rango (0-31)")
    return _words(CMD_PARTY_ADD_EGG, TEMP_VAR, species, form, CMD_END)


# Acompañante (prueba, 08-nov): el sistema de la historia para los aliados que te siguen (src/ov012/pair_sys.c)
CMD_PLAYER_GET_GPOS = 0x0068        # s0068_PlayerGetGPos(variable x, variable z)
CMD_ACTOR_NEW = 0x0069              # s0069_ActorNew(x, z, dirección, id, modelo, código de movimiento)
CMD_ACTOR_DELETE = 0x006C           # s006C_ActorDelete(id)
CMD_WORK_ADD = 0x0026               # s0026_WorkAdd(variable, valor)
CMD_PAIR_SET = 0x0250               # s0250_ActorPairSet(id, índice 0-7, persistente, entrenador aliado, guion)
CMD_PAIR_END = 0x0251               # s0251_ActorPairEnd(guion, código de movimiento)
CMD_PAIR_MOVE_ENABLE = 0x0253       # s0253_ActorPairSetMoveEnable(u8)
FOLLOWER_NEW_ID = 0xF0              # id con el que se crea (luego el juego le pone FOLLOWER_ACTOR_ID = 0xFE)
FOLLOWER_ACTOR_ID = 0xFE
FOLLOWER_INDEX = 7                  # índice del acompañante (0-7); la historia usa los bajos
OBJ_CODE_POKEMON_MIN = 0x1000       # modelos de Pokémon para caminar (OBJ_CODE_POKEMON_*: 0x1000-0x126B)
# Con acompañante, los salvajes salen dobles con él de aliado (CreateEncountManager, overlay 36: pairActive =
# GameData_CheckPairFlag). Nuestro Pokémon no es entrenador: el juego sacaba un aliado vacío y se trababa (08-nov).
# Parche: ese bl -> movs r0, #0; nop (pairActive = 0). Lo mantiene el Lua (orden P) mientras haya acompañante.
NO_PAIR_BATTLE_PATCH = {"IRDO": (0x021A0B5E, "c9f7a9fb", "0020c046")}


def follower(obj_code: int) -> str:
    """Crea un personaje con ese modelo debajo del jugador y lo vuelve su acompañante persistente (sigue al cambiar
    de mapa). Si ya hay uno (de la historia o anterior), el juego no lo cambia."""
    if not OBJ_CODE_POKEMON_MIN <= obj_code < 0x2000:
        raise ValueError("obj_code debe ser un modelo de Pokémon (0x1000-0x1FFF)")
    x, z = TEMP_VAR, TEMP_VAR + 1
    return (_words(CMD_PLAYER_GET_GPOS, x, z, CMD_WORK_ADD, z, 1,
                   CMD_ACTOR_NEW, x, z, DIR_DOWN, FOLLOWER_NEW_ID, obj_code, 0,
                   CMD_PAIR_SET, FOLLOWER_NEW_ID, FOLLOWER_INDEX, 1, 0, 0)
            + struct.pack("<HB", CMD_PAIR_MOVE_ENABLE, 1).hex() + _words(CMD_END))


def follower_end() -> str:
    """Quita el acompañante."""
    return _words(CMD_PAIR_END, 0, 0, CMD_ACTOR_DELETE, FOLLOWER_ACTOR_ID, CMD_ACTOR_DELETE, FOLLOWER_NEW_ID, CMD_END)


# Acompañante dentro de la ROM (tools/w2u_build/patches/follower.cpp): el primero del equipo te sigue solo. Estas
# banderas del guardado lo apagan y dicen si el que te sigue es el nuestro (no un aliado de la historia).
CMD_FLAG_SET = 0x0023               # s0023_FlagSet(bandera)
CMD_FLAG_RESET = 0x0024             # s0024_FlagReset(bandera)
CMD_FLAG_GET = 0x0025               # s0025_FlagGet(bandera, variable)
FLAG_PAIR = 0x966                   # pair_sys: alguien te sigue
FLAG_FOLLOWER_OFF = 0xA90
FLAG_FOLLOWER_OURS = 0xA91


def follower_native(on: bool) -> str:
    """Enciende o apaga el acompañante de la ROM. Al encenderlo aparece al entrar en el siguiente mapa (puerta,
    cambio de ruta); al apagarlo se va enseguida, pero solo si es el nuestro (un aliado de la historia se queda)."""
    if on:
        return _words(CMD_FLAG_RESET, FLAG_FOLLOWER_OFF, CMD_END)
    remove = _words(CMD_ACTOR_DELETE, FOLLOWER_ACTOR_ID, CMD_FLAG_RESET, FLAG_PAIR, CMD_FLAG_RESET, FLAG_FOLLOWER_OURS)
    return (_words(CMD_FLAG_SET, FLAG_FOLLOWER_OFF, CMD_FLAG_GET, FLAG_FOLLOWER_OURS, TEMP_VAR,
                   CMD_CMP_CONST, TEMP_VAR, 0)
            + struct.pack("<HBI", CMD_JUMP_IF, COND_EQUAL, len(remove) // 2).hex()   # no es el nuestro: nada que quitar
            + remove + _words(CMD_END))
