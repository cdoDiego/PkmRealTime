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
CMD_WILD_BATTLE_END = 0x0175        # s0175_CallWildBattleEnd: vuelve al mapa con su transición
CMD_WILD_LOSE = 0x0176              # s0176_CallWildLose: derrota (al Centro Pokémon) y fin del guion
CMD_WILD_IS_VICTORY = 0x0177        # s0177_WildBattleIsVictory(variable): 1 si no perdió
CMD_TRAINER_BATTLE = 0x0085         # s0085_CallTrainerBattle(entrenador 1, entrenador 2, opciones)
CMD_TRAINER_LOSE = 0x008C           # s008C_CallTrainerLose
CMD_TRAINER_IS_VICTORY = 0x008D     # s008D_TrainerBattleIsVictory(variable)
CMD_TRAINER_BATTLE_END = 0x008E     # s008E_CallTrainerBattleEnd
CMD_FIELD_WEATHER = 0x0136          # s0136_FieldSetWeather(clima, inmediato)

# Clima del mapa (FieldWeather). Al empezar un combate se convierte (ConvFieldWeatherToBtl en field_encount.c):
# 2, 6, 7 → lluvia; 3, 12 → arena; 4, 5 → granizo; el resto, sin clima en combate. Todos vistos en el juego (27-oct).
FIELD_WEATHER = {
    "none": 0, "snow": 1, "rain": 2, "sandstorm": 3, "hail": 4, "blizzard": 5, "heavy_rain": 6, "rain_streaks": 7,
    "diamond_dust": 8, "fog": 9, "overcast": 10, "light_fog": 11, "heavy_sandstorm": 12, "overcast2": 13,
    "zone": 0xFFFF,   # el clima normal de la ruta
}


def _words(*values: int) -> str:
    for v in values:
        if not 0 <= v < 0x4000 and v not in (0xFFFF, TEMP_VAR):
            raise ValueError(f"valor fuera de rango para un guion: {v}")
    return struct.pack(f"<{len(values)}H", *values).hex()


def _after_battle(is_victory: int, lose: int, end: int) -> str:
    """Como los guiones del juego: si perdió, la derrota (el juego ya no la hace solo en combates de guion: si se
    intenta volver al mapa tras perder, se cuelga, visto el 27-oct); si no, vuelta al mapa."""
    return (_words(is_victory, TEMP_VAR, CMD_CMP_CONST, TEMP_VAR, 1)
            + struct.pack("<HBI", CMD_JUMP_IF, COND_EQUAL, 2).hex()   # si ganó, se salta la orden de derrota (2 bytes)
            + _words(lose, end, CMD_END))


def wild_battle(species: int, level: int) -> str:
    max_species = len(gamedata.DATA.get("species", {})) or 649
    if not 1 <= species <= max_species:
        raise ValueError(f"especie fuera de rango: {species} (1-{max_species})")
    if not 1 <= level <= 100:
        raise ValueError("el nivel debe ir de 1 a 100")
    return _words(CMD_WILD_BATTLE, species, level, 0) + _after_battle(CMD_WILD_IS_VICTORY, CMD_WILD_LOSE, CMD_WILD_BATTLE_END)


def trainer_battle(trainer: int) -> str:
    trainers = gamedata.DATA.get("trainers")
    if not trainers:
        raise ValueError("faltan los entrenadores en gen5_data.json: reinicia el puente con ROM_PATH configurado")
    if not 1 <= trainer < len(trainers) or trainers[trainer][2] == 0:
        raise ValueError(f"entrenador no válido: {trainer} (1-{len(trainers) - 1}, con Pokémon)")
    return _words(CMD_TRAINER_BATTLE, trainer, 0, 0) + _after_battle(CMD_TRAINER_IS_VICTORY, CMD_TRAINER_LOSE,
                                                                    CMD_TRAINER_BATTLE_END)


def field_weather(weather) -> str:
    if isinstance(weather, str):
        if weather not in FIELD_WEATHER:
            raise ValueError(f"clima desconocido: {weather} (válidos: {', '.join(FIELD_WEATHER)} o un número)")
        weather = FIELD_WEATHER[weather]
    return _words(CMD_FIELD_WEATHER, int(weather), 1, CMD_END)


def trainer_info(trainer: int) -> dict:
    t = gamedata.DATA["trainers"][trainer]
    classes = gamedata.DATA.get("trainer_classes", [])
    return {"id": trainer, "class": classes[t[0]] if t[0] < len(classes) else t[0],
            "battle_type": ("individual", "doble", "triple", "rotatorio")[t[1]] if t[1] < 4 else t[1], "pokemon": t[2]}
