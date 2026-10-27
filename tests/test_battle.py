"""Pruebas de battle.py con datos sintéticos y, si existe, con el volcado dumps/combate1.bin (python tests/test_battle.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import struct
import battle

def battler(hp=10, max_hp=16, stages=(6, 6, 6, 6, 6, 6, 6), sick=None, sleep=None):
    raw = bytearray(battle.OFF_MOVES + 4 * battle.MOVE_STRIDE)
    struct.pack_into("<HH", raw, battle.OFF_MAX_HP, max_hp, hp)
    raw[battle.OFF_STAGES:battle.OFF_STAGES + 7] = bytes(stages)
    if sick:
        struct.pack_into("<I", raw, battle.OFF_SICK + 4 * sick, 1)
    if sleep:
        struct.pack_into("<I", raw, battle.OFF_SICK + 8, 2 | (sleep[1] << 3)); raw[battle.OFF_COUNTERS + 2] = sleep[0]
    return raw.hex()

# cambios de estadísticas legibles: 6 = 0, 5 = -1, 8 = +2
b = battle.parse(f"T:00,p0:0225b224:{battler(stages=(4, 5, 6, 6, 8, 6, 6))}:-,P0:0225c120:{battler(stages=(4, 5, 6, 6, 8, 6, 6))}:-")
assert b["player"][0]["stages"] == {"atk": -2, "def": -1, "spa": 0, "spd": 0, "spe": 2, "acc": 0, "eva": 0}, b

# se muestra la copia real y la vida de la visual
b = battle.parse(f"T:00,e0:0225befc:{battler(hp=0)}:-,E0:0225cdf8:{battler(hp=3, sick=1)}:-")
e = b["enemy"][0]
assert (e["hp"], e["hp_visual"], e["conditions"]) == (3, 0, ["paralysis"]), e

# escrituras en las dos copias, con su guarda
assert battle.set_hp_command("enemy", 0, 1) == "G 0x225ce08 0300 0100;G 0x225bf0c 0000 0100"
# vida 0: la copia real queda a 1 y el Lua la debilita cuando el juego la revisa; la visual pasa a 0
s = battle.parse(f"T:00,P1:0225c344:{battler(sleep=(1, 3))}:-")
assert s["player"][0]["conditions"] == ["sleep (quedan 1 turnos)"], s
b = battle.parse(f"T:00,e0:0225befc:{battler(hp=0)}:-,E0:0225cdf8:{battler(hp=3, sick=1)}:-")
assert battle.set_hp_command("enemy", 0, 0) == "F 0x225cdf8;G 0x225ce08 0300 0100;G 0x225bf0c 0000 0000"
cmd = battle.set_status_command("enemy", 0, "burn")
assert cmd.count("G ") == 4 and cmd.split(";")[0].endswith("0000000000000000000000000100000000000000")
assert cmd.split(";")[1] == "G 0x225cea5 0000000000 0000000000"          # contadores 1-5 a 0 (+0xAD)
# sueño: tipo 2 y turnos en los bits 3-8; envenenamiento grave: tipo 1 y turnos 15
sleep = battle.set_status_command("enemy", 0, "sleep", 2).split(";")[0].split()[-1]
assert sleep == "00000000" + "1a000000" + "00" * 12, sleep   # 2 turnos sin atacar = 3 en el contador
toxic = battle.set_status_command("enemy", 0, "toxic").split(";")[0].split()[-1]
assert toxic == "00" * 16 + "79000000", toxic
for bad in [lambda: battle.set_status_command("enemy", 0, "sleep", 7), lambda: battle.set_status_command("enemy", 0, "burn", 2),
            lambda: battle.set_status_command("enemy", 0, "confusion"), lambda: battle.set_hp_command("player", 3, 1)]:
    try:
        bad(); raise SystemExit("debía fallar")
    except ValueError:
        pass

# con el volcado real del combate contra el Patrat (Malicioso bajó la Defensa de Oshawott)
DUMP = os.path.join(ROOT, "dumps", "combate1.bin")
if os.path.exists(DUMP):
    ram = open(DUMP, "rb").read(); B = 0x02000000
    ptr = struct.unpack_from("<I", ram, 0x24)[0] & 0xFFFFFF
    parts = ["T:00"]
    for side, base in (("p", ptr + 0x526A8), ("P", ptr + 0x52790)):
        a = struct.unpack_from("<I", ram, base)[0] & 0xFFFFFF
        parts.append(f"{side}0:{B + a:08x}:{ram[a:a + 0x140].hex()}:-")
    osha = battle.parse(",".join(parts))["player"][0]
    assert osha["stages"]["def"] == -1 and osha["stages"]["atk"] == 0, osha["stages"]
    print("ok comparación con el combate real")
print("ok combate")

# cambios de estadísticas y PP (opción B)
def battler_moves(stages=(6, 6, 6, 6, 6, 6, 6)):
    raw = bytearray.fromhex(battler(stages=stages))
    entry = bytes.fromhex("2100202300112100202300110100")      # Placaje 32/35, tal como está en el volcado
    raw[battle.OFF_MOVES:battle.OFF_MOVES + 14] = entry
    return raw.hex()
battle.parse(f"T:00,p0:0225b224:{battler_moves((6, 5, 6, 6, 6, 6, 6))}:-,P0:0225c120:{battler_moves((6, 5, 6, 6, 6, 6, 6))}:-")
assert battle.set_stage_command("player", 0, "atk", stage=2) == "G 0x225c21c 06 08;G 0x225b320 06 08"
assert battle.set_stage_command("player", 0, "def", delta=-1).startswith("G 0x225c21d 05 04")
assert battle.set_stage_command("player", 0, "def", delta=-20).endswith(" 05 00")    # tope -6
assert battle.set_stage_command("player", 0, "spe", stage=9).endswith(" 06 0c")      # tope +6
cmd = battle.set_pp_command("player", 0, 0)                                            # al máximo: 35
assert cmd.count("G ") == 4 and cmd.split(";")[0] == "G 0x225c226 20 23" and cmd.split(";")[1] == "G 0x225c22c 20 23"
assert battle.set_pp_command("player", 0, 0, pp=0).split(";")[0].endswith(" 20 00")
assert battle.set_pp_command("player", 0, 0, pp=99).split(";")[0].endswith(" 20 23")    # tope = PP máx
for bad in [lambda: battle.set_stage_command("player", 0, "hp", stage=1),
            lambda: battle.set_stage_command("player", 0, "atk"),
            lambda: battle.set_pp_command("player", 0, 1),                            # hueco vacío
            lambda: battle.set_pp_command("player", 0, 4)]:
    try:
        bad(); raise SystemExit("debía fallar")
    except ValueError:
        pass
print("ok estadísticas y PP en combate")

# comandos de pantalla (opción 3): animar barra e ícono de estado, con el pokeID de la copia real
raw = bytearray.fromhex(battler(hp=3)); raw[0x19] = 12
battle.parse(f"T:00,e0:0225befc:{raw.hex()}:-,E0:0225cdf8:{raw.hex()}:-")
assert battle.poke_id("enemy", 0) == 12
assert battle.show_hp_command("enemy", 0) == "J 00410c"
assert battle.show_status_command("enemy", 0, "paralysis") == "J 00350c01"
assert battle.show_status_command("enemy", 0, "burn") == "J 00350c04"
assert battle.show_status_command("enemy", 0, "none") == "J 00350c00"
print("ok comandos de pantalla")
