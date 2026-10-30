"""Pruebas de pc.py y de move_pokemon / remove_pokemon (sin juego): python tests/test_pc.py"""
import os, sys, struct, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bridge, boxes, config, gift, pc, pk5

T = {"name": "Diego".encode("utf-16-le") + b"\xff\xff" + bytes(4), "tid": 1, "sid": 2, "language": 2, "version": 22, "gender": 0}
rng = random.Random(3)
boxmon = lambda sp, lvl: bytes(pk5.encrypt(gift.create(sp, lvl, T, rng=rng)))

# de caja a equipo: datos de combate calculados (Bulbasaur nivel 10, vida llena o la indicada)
b = boxmon(1, 10)
p = pk5.decrypt(pc.to_party(b))
assert len(p) == 220 and p[pk5.OFF_LEVEL] == 10 and pk5.is_valid(p)
st = struct.unpack_from("<6H", p, pc.OFF_STATS)
assert struct.unpack_from("<H", p, pk5.OFF_CUR_HP)[0] == st[0] and 25 <= st[0] <= 35, st
assert struct.unpack_from("<H", pk5.decrypt(pc.to_party(b, hp=0)), pk5.OFF_CUR_HP)[0] == 0
assert pc.to_party(b)[:136] == b                                   # la parte de caja no cambia
assert pc.is_empty(pc.EMPTY_BOX) and pc.is_empty(pc.EMPTY_PARTY) and not pc.is_empty(b)

# eventos con un estado falso: equipo de 2, caja 1 con uno en el hueco 0, caja 2 vacía
PTR = 0x02204D04
bridge.game.update(mode="map", party_addr=PTR + config.PARTY_PTR_OFF)
party = [pc.to_party(boxmon(501, 5)), pc.to_party(boxmon(25, 7))]
bridge.party_raw[:] = party
main = bytearray(boxes.MAIN_SIZE); main[boxes.COUNT_OFF] = 8
bridge.box_main = bytes(main)
bridge.box_cache.clear()
bridge.box_cache[0] = b + pc.EMPTY_BOX * 29
bridge.box_cache[1] = pc.EMPTY_BOX * 30

def cmds(**kw):
    return bridge.build_commands(bridge.Event(id=1, data=bridge.EventIn(**kw).model_dump(), source="prueba")).split(";")

c = cmds(type="move_pokemon", target={"slot": 1}, destination="box2")       # equipo -> caja 2 (hueco 0)
assert c[0] == "SAVE" and c[1].startswith(f"G {PTR + config.PARTY_COUNT_PTR_OFF:#x} 02000000")
assert c[1].split()[3].startswith("01000000") and c[1].split()[3].endswith(pc.EMPTY_PARTY.hex())
assert c[2] == f"G {PTR + config.BOX_PTR_OFF + 0x1000:#x} {pc.EMPTY_BOX.hex()} {party[1][:136].hex()}"
c = cmds(type="move_pokemon", target={"box": 1, "slot": 0}, destination="party")   # caja 1 -> equipo
assert c[1] == f"G {PTR + config.BOX_PTR_OFF:#x} {b.hex()} {pc.EMPTY_BOX.hex()}"
assert c[2].split()[3].startswith("03000000") and c[3].startswith(f"W {PTR + config.PARTY_PTR_OFF + 440:#x} ")
c = cmds(type="move_pokemon", target={"box": 1, "slot": 0}, destination="box1", to_slot=5)   # dentro de la caja
assert c[2] == f"G {PTR + config.BOX_PTR_OFF + 5 * 136:#x} {pc.EMPTY_BOX.hex()} {b.hex()}"
c = cmds(type="remove_pokemon", target={"box": 1, "slot": 0})
assert c == ["SAVE", f"G {PTR + config.BOX_PTR_OFF:#x} {b.hex()} {pc.EMPTY_BOX.hex()}"]
for bad in [dict(type="remove_pokemon", target={"box": 2, "slot": 0}),           # hueco vacío
            dict(type="move_pokemon", target={"slot": 0}, destination="party"),   # ya en el equipo
            dict(type="move_pokemon", target={"slot": 0}, destination="box9"),    # solo 8 cajas
            dict(type="move_pokemon", target={"slot": 0}, destination="box3"),    # caja aún sin leer
            dict(type="move_pokemon", target={"box": 1, "slot": 0}, destination="box1", to_slot=0),
            dict(type="set_hp", target={"box": 1, "slot": 0}, hp=1)]:
    try:
        cmds(**bad); raise SystemExit(f"debía fallar: {bad}")
    except ValueError:
        pass
bridge.party_raw[:] = party[:1]                                               # no dejar el equipo vacío
try:
    cmds(type="remove_pokemon", target={"slot": 0}); raise SystemExit("debía fallar")
except ValueError as e:
    assert "al menos un" in str(e)
bridge.party_raw[:] = []; bridge.box_cache.clear(); bridge.box_main = b""
print("ok mover y quitar Pokémon")
