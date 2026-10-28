"""Pruebas de field_script.py (python tests/test_field_script.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import field_script, gamedata

# combate salvaje: 0x0174 especie nivel opciones, 0x0175, 0x0002 (u16 little-endian)
# después: ¿ganó? (en 0x8000), comparar con 1, si es igual saltar 2 bytes (la orden de derrota), fin del combate, fin
AFTER_WILD = "7701" "0080" "1900" "0080" "0100" "1f00" "01" "02000000" "7601" "7501" "0200"
assert field_script.wild_battle(25, 10) == "9702" "1900" "0a00" "0000" "0000" + AFTER_WILD
# opciones: variocolor 0x02 + oculta 0x08 + hembra 0x40 + sin huida 0x01 = 0x4b; forma 1
assert field_script.wild_battle(25, 10, 1, True, True, "female", True).startswith("9702" "1900" "0a00" "0100" "4b00")
assert field_script.wild_battle(25, 10, shiny=False).startswith("9702" "1900" "0a00" "0000" "1000")
assert field_script.field_weather("rain") == "3601" "0200" "0100" "0200"
assert field_script.field_weather("zone") == "3601" "ffff" "0100" "0200"
for bad in [lambda: field_script.wild_battle(0, 5), lambda: field_script.wild_battle(25, 101),
            lambda: field_script.field_weather("sol")]:
    try:
        bad(); raise SystemExit("debía fallar")
    except ValueError:
        pass

# entrenadores: con datos sintéticos (clase, tipo de combate, nº de Pokémon)
saved = gamedata.DATA.get("trainers"), gamedata.DATA.get("trainer_classes")
gamedata.DATA["trainers"] = [[0, 0, 0], [1, 0, 2], [2, 1, 0]]
gamedata.DATA["trainer_classes"] = ["?", "Lass", "Twins"]
assert field_script.trainer_battle(1) == ("8500" "0100" "0000" "0000"
                                         "8d00" "0080" "1900" "0080" "0100" "1f00" "01" "02000000" "8c00" "8e00" "0200")
assert field_script.trainer_info(1) == {"id": 1, "class": "Lass", "battle_type": "individual", "pokemon": 2}
for bad in (0, 2, 3):        # 0 no existe, 2 no tiene Pokémon, 3 fuera de rango
    try:
        field_script.trainer_battle(bad); raise SystemExit("debía fallar")
    except ValueError:
        pass
gamedata.DATA["trainers"], gamedata.DATA["trainer_classes"] = saved
# teletransporte: volar a la zona (0x028A zona dirección) o a una casilla (0x00C2 zona x z dirección)
assert field_script.teleport("aspertia") == "8a02" "ab01" "0100" "0200"
assert field_script.teleport("28", 10, 20) == "c200" "1c00" "0a00" "1400" "0100" "0200"
for bad in [lambda: field_script.teleport("atlantis"), lambda: field_script.teleport("28", 10)]:
    try:
        bad(); raise SystemExit("debía fallar")
    except ValueError:
        pass
# regalo al equipo: 0x010E y, si devolvió 0 (equipo lleno), 0x0123 a una caja
g = field_script.give_pokemon(25, 10, shiny=True, gender="female")
args = "0080" "1900" "0000" "0a00" "0200" "0100" "0100" "0000" "0400"
assert g == "0e01" + args + "1900" "0080" "0100" "1f00" "01" "14000000" + "2301" + args + "0200", g
assert len(bytes.fromhex("2301" + args)) == 20
print("ok guiones del mapa")
