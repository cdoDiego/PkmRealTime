"""Pruebas de rival.py (control del rival) con dumps/combate2.bin y datos sintéticos (python tests/test_rival.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct
import battle, gamedata, rival
import dump_field


def must_fail(fn, text):
    try:
        fn()
    except ValueError as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"debía fallar: {text}")


# acciones: ida y vuelta
assert rival.encode_fight(10, 0) == 0x501                      # el Arañazo del volcado
assert rival.decode_action(rival.encode_change(0, 3))["slot"] == 3
assert rival.decode_action(0x501)["move_id"] == 10

DUMP = os.path.join(ROOT, "dumps", "combate2.bin")
if os.path.exists(DUMP) and gamedata.DATA.get("move_info"):
    ram = open(DUMP, "rb").read()
    b = battle.parse(dump_field.field(ram, ",H:0:0:0,N:3"))
    a1 = b["adapters"][1]
    assert (a1["cmd"], a1["state"], a1["returned"], a1["reply"]) == (3, 4, True, "01050000"), a1
    st = rival.status(b)
    assert st["request"] == "accion" and st["player_ready"] is False and st["turn"] == 3, st
    act = st["rivals"][0]["actions"][0]
    assert (act["action"], act["move"], act["target"]) == ("atacar", "Scratch", 0), act
    e = b["enemy"][0]
    assert e["types"] == [16, 16] and e["ability_now"] == "Unburden" and e["prev_move"] == "Growl", e
    assert e["locked"] is None and e["volatile"] == [], e

    d = {"type": "rival_action", "action": "move", "move_slot": 1, "target": {}}
    assert rival.ready(b, d)
    cmds = rival.action_commands(b, d)                         # Gruñido (45) contra la posición 0
    assert cmds == "G 0x2261cea 04 04;G 0x2261b88 01050000 81160000", cmds
    assert rival.action_commands(b, {**d, "move_slot": 0}) == "G 0x2261cea 04 04"   # ya era Arañazo
    must_fail(lambda: rival.action_commands(b, {**d, "move_slot": 2}), "no tiene movimiento")
    must_fail(lambda: rival.action_commands(b, {"action": "switch", "to_slot": 1, "target": {}}), "no hay rival")
    must_fail(lambda: rival.action_commands(b, {"action": "jump", "target": {}}), "action debe ser")

    # PP a 0 y condiciones: se modifican los bytes de la copia real del rival
    addr, raw = battle.RAW[("enemy", 0, "real")]
    def with_raw(new):
        battle.RAW[("enemy", 0, "real")] = (addr, bytes(new))
    r = bytearray(raw); r[battle.OFF_MOVES + battle.MOVE_STRIDE + 2] = 0
    with_raw(r); must_fail(lambda: rival.action_commands(b, d), "no tiene PP")
    r = bytearray(raw); struct.pack_into("<I", r, battle.OFF_SICK + 4 * 23, 2 | 3 << 3 | 10 << 9)   # Otra vez: Arañazo
    with_raw(r); must_fail(lambda: rival.action_commands(b, d), "Otra vez")
    r = bytearray(raw); struct.pack_into("<I", r, battle.OFF_SICK + 4 * 11, 2 | 3 << 3)              # Mofa: Gruñido no
    with_raw(r); must_fail(lambda: rival.action_commands(b, d), "Mofa")
    r = bytearray(raw); struct.pack_into("<I", r, battle.OFF_SICK + 4 * 25, 2 | 2 << 3 | 37 << 9)    # Golpe (Thrash)
    with_raw(r)
    assert battle.locked(bytes(r))["reason"] == "move_lock"
    must_fail(lambda: rival.action_commands(b, d), "no elige")
    r = bytearray(raw); r[battle.OFF_COND_FLAGS + 1] |= 0x10                                         # recarga
    with_raw(r); must_fail(lambda: rival.action_commands(b, d), "recargando")
    with_raw(raw)

    # el ataque no se puede elegir en un cambio tras debilitarse
    b2 = {**b, "adapters": {**b["adapters"], 1: {**a1, "cmd": 5, "reply": "01050000"}}}
    assert not rival.ready(b2, d)
    assert not rival.ready(b2, {"action": "switch", "to_slot": 1, "target": {}})   # su respuesta no es un cambio

    # pausa: se suelta sola si el rival no tiene nada que decidir
    held = {**b, "hold": {"active": True, "frames": 10, "enabled": True},
            "adapters": {**b["adapters"], 1: {**a1, "state": 2, "cmd": 5, "reply": "00000000"}}}
    assert rival.auto_release(held) == "HR"
    held["adapters"][1] = {**a1, "state": 2}
    assert rival.auto_release(held) == ""                      # tiene un ataque: se espera la decisión
    print("ok rival (volcado combate2)")

# cambio de Pokémon con un equipo sintético de 3: el 0 en el campo, el 1 vivo y el 2 debilitado
def mon(hp=20, types=(0, 0), ability=0, item=0, conds=()):
    raw = bytearray(dump_field.BATTLER_SIZE)
    struct.pack_into("<HH", raw, battle.OFF_MAX_HP, 20, hp)
    struct.pack_into("<H", raw, battle.OFF_ITEM, item)
    raw[battle.OFF_TYPES:battle.OFF_TYPES + 2] = bytes(types)
    struct.pack_into("<H", raw, battle.OFF_ABILITY_NOW, ability)
    struct.pack_into("<HB", raw, battle.OFF_MOVES, 33, 10)
    for c in conds:
        struct.pack_into("<I", raw, battle.OFF_SICK + 4 * c, 1)
    return raw.hex()

def build(enemy0="", reply="01050000", cmd=3, player=""):
    parts = ["T:00", f"P0:0225c120:{player or mon()}:-", f"p0:0225b224:{player or mon()}:-",
             f"E0:0225cdf8:{enemy0 or mon()}:-", f"E1:0225d000:{mon()}:-", f"E2:0225d200:{mon(hp=0)}:-",
             f"Q0:02260274:0000030303000000:00000000:-:0000000000000000",
             f"Q1:02261cdc:010104{cmd:02x}{cmd:02x}000000:02261b88:{reply}:0000000000000000"]
    return battle.parse(",".join(parts))

sw = {"action": "switch", "to_slot": 1, "target": {}}
b = build()
assert rival.action_commands(b, sw) == "G 0x2261cea 04 04;G 0x2261b88 01050000 83000000"
must_fail(lambda: rival.action_commands(b, {**sw, "to_slot": 2}), "debilitado")
must_fail(lambda: rival.action_commands(b, {**sw, "to_slot": 0}), "banquillo")
must_fail(lambda: rival.action_commands(build(enemy0=mon(conds=[22])), sw), "no puede huir")
must_fail(lambda: rival.action_commands(build(enemy0=mon(conds=[8])), sw), "atrapado")
must_fail(lambda: rival.action_commands(build(player=mon(ability=23)), sw), "Sombra Trampa")
assert rival.action_commands(build(enemy0=mon(conds=[22], item=295)), sw).endswith("83000000")   # Muda Concha
must_fail(lambda: rival.action_commands(build(player=mon(ability=71)), sw), "Trampa Arena")
assert rival.action_commands(build(enemy0=mon(types=(2, 2)), player=mon(ability=71)), sw)       # volador: no
must_fail(lambda: rival.action_commands(build(enemy0=mon(types=(8, 8)), player=mon(ability=42)), sw), "Imán")
# tras debilitarse: el rival iba a sacar al 2 (u otro); se cambia por el 1 manteniendo su posición
b = build(reply=struct.pack("<I", rival.encode_change(0, 2)).hex(), cmd=5)
assert rival.ready(b, sw)
assert rival.action_commands(b, sw).endswith(f"{struct.pack('<I', rival.encode_change(0, 1)).hex()}")
must_fail(lambda: rival.action_commands(b, {**sw, "action": "move", "move_slot": 0}), "elige acción")
print("ok rival (cambios)")
