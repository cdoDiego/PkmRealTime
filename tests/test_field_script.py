"""Pruebas de field_script.py (python tests/test_field_script.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import field_script, gamedata

# combate salvaje: 0x0174 especie nivel opciones, 0x0175, 0x0002 (u16 little-endian)
assert field_script.wild_battle(25, 10) == "7401" "1900" "0a00" "0000" "7501" "0200"
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
assert field_script.trainer_battle(1) == "8500" "0100" "0000" "0000" "8e00" "0200"
assert field_script.trainer_info(1) == {"id": 1, "class": "Lass", "battle_type": "individual", "pokemon": 2}
for bad in (0, 2, 3):        # 0 no existe, 2 no tiene Pokémon, 3 fuera de rango
    try:
        field_script.trainer_battle(bad); raise SystemExit("debía fallar")
    except ValueError:
        pass
gamedata.DATA["trainers"], gamedata.DATA["trainer_classes"] = saved
print("ok guiones del mapa")
