"""Guiones propios del mapa (combate salvaje, contra entrenador, clima) para B2/W2.

El Lua (comando S) hace que el juego ejecute estos bytes como su "guion reservado" en cuanto el personaje queda
libre. Formato de los guiones de Gen 5: cada orden es un u16 (little-endian) y sus argumentos u16; los valores por
debajo de 0x4000 son constantes (por encima serían variables). Órdenes de la decompilación pokebw2
(src/ov036/scrcmd_encount.c, scrcmd_trainer.c; src/ov012/scrcmd_weather.c, scrcmd_vm.c).
"""
import struct

import gamedata

CMD_END = 0x0002                    # s0002_VMHalt
CMD_WILD_BATTLE = 0x0174            # s0174_CallWildBattle(especie, nivel, opciones)
CMD_WILD_BATTLE_END = 0x0175        # s0175_CallWildBattleEnd: vuelve al mapa con su transición
CMD_TRAINER_BATTLE = 0x0085         # s0085_CallTrainerBattle(entrenador 1, entrenador 2, opciones)
CMD_TRAINER_BATTLE_END = 0x008E     # s008E_CallTrainerBattleEnd
CMD_FIELD_WEATHER = 0x0136          # s0136_FieldSetWeather(clima, inmediato)

# Clima del mapa (FieldWeather). Al empezar un combate se convierte (ConvFieldWeatherToBtl en field_encount.c):
# 2, 6, 7 → lluvia; 3, 12 → granizo; 4, 5 → tormenta de arena. Los nombres son provisionales hasta verlos en el juego.
FIELD_WEATHER = {"none": 0, "rain": 2, "snow": 3, "sandstorm": 4, "sandstorm2": 5, "thunderstorm": 6,
                 "heavy_rain": 7, "diamond_dust": 12, "zone": 0xFFFF}


def _words(*values: int) -> str:
    for v in values:
        if not 0 <= v < 0x4000 and v != 0xFFFF:
            raise ValueError(f"valor fuera de rango para un guion: {v}")
    return struct.pack(f"<{len(values)}H", *values).hex()


def wild_battle(species: int, level: int) -> str:
    max_species = len(gamedata.DATA.get("species", {})) or 649
    if not 1 <= species <= max_species:
        raise ValueError(f"especie fuera de rango: {species} (1-{max_species})")
    if not 1 <= level <= 100:
        raise ValueError("el nivel debe ir de 1 a 100")
    return _words(CMD_WILD_BATTLE, species, level, 0, CMD_WILD_BATTLE_END, CMD_END)


def trainer_battle(trainer: int) -> str:
    trainers = gamedata.DATA.get("trainers")
    if not trainers:
        raise ValueError("faltan los entrenadores en gen5_data.json: reinicia el puente con ROM_PATH configurado")
    if not 1 <= trainer < len(trainers) or trainers[trainer][2] == 0:
        raise ValueError(f"entrenador no válido: {trainer} (1-{len(trainers) - 1}, con Pokémon)")
    return _words(CMD_TRAINER_BATTLE, trainer, 0, 0, CMD_TRAINER_BATTLE_END, CMD_END)


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
