"""Pruebas de happenings.py (avisos de lo que pasa en el juego): python tests/test_happenings.py"""
import os, sys, struct, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import gift, happenings, pk5, gamedata

T = {"name": "Diego".encode("utf-16-le") + b"\xff\xff" + bytes(4), "tid": 1, "sid": 2, "language": 2, "version": 22, "gender": 0}
rng = random.Random(5)

def mon(species, level, hp=20, met=124, party=True, egg=False):
    p = gift.create(species, level, T, met_location=met, rng=rng)
    if egg:
        ivs = struct.unpack_from("<I", p, 0x38)[0] | (1 << 30); struct.pack_into("<I", p, 0x38, ivs)
    if not party:
        return p
    p = p + bytearray(84); p[pk5.OFF_LEVEL] = level; struct.pack_into("<H", p, pk5.OFF_CUR_HP, hp)
    return p

def enc(plain): return bytes(pk5.encrypt(plain))
def snap(mode, zone, badges, party, box=b""):
    return happenings.snapshot(mode, {"zone": zone}, badges, [enc(p) for p in party], {0: box} if box else {})

starter = mon(501, 5)
s0 = snap("map", 437, 0b1, [starter])
assert happenings.diff(None, s0) == []                     # al conectar no se avisa de lo que ya había
assert happenings.diff(s0, snap("map", 437, 0b1, [starter])) == []

# zona, medalla, combate
s1 = snap("map", 446, 0b11, [starter])
kinds = [k for k, _ in happenings.diff(s0, s1)]
assert kinds == ["zone", "badge"], kinds
assert dict(happenings.diff(s0, s1))["badge"] == {"badge": 2, "count": 2}
s2 = snap("battle", 446, 0b11, [])
assert [k for k, _ in happenings.diff(s1, s2)] == ["battle_start"] and s2["mons"] is None

# captura (lugar de encuentro = lugar de la zona) frente a regalo; sube de nivel, se debilita
route20 = happenings.place_of_zone(446)
caught = mon(519, 4, met=route20 if route20 >= 0 else 125)
gifted = mon(25, 10, met=gift.DISTANT_LAND)
up = bytearray(starter); up[pk5.OFF_LEVEL] = 6; struct.pack_into("<H", up, pk5.OFF_CUR_HP, 0)
s3 = snap("map", 446, 0b11, [up, caught, gifted])
s2["mons"] = s1["mons"]                                    # el puente conserva los Pokémon de antes del combate
got = happenings.diff(s2, s3)
kinds = [k for k, _ in got]
if route20 >= 0:
    assert kinds == ["battle_end", "level_up", "fainted", "caught", "obtained"], kinds
d = dict(got)
assert d["level_up"]["from_level"] == 5 and d["level_up"]["level"] == 6 and d["obtained"]["species"] == 25

# evoluciona, se cura (revive), pasa a la caja, se va; un huevo eclosiona
evo = bytearray(up); struct.pack_into("<H", evo, 8, 502); struct.pack_into("<H", evo, pk5.OFF_CUR_HP, 15)
egg = mon(1, 1, egg=True)
s4 = snap("map", 446, 0b11, [evo, egg], box=enc(caught[:136]) + bytes(136 * 29))
kinds = [k for k, _ in happenings.diff(s3, s4)]
assert kinds == ["evolved", "revived", "obtained", "moved", "left"], kinds
hatched = bytearray(egg); ivs = struct.unpack_from("<I", hatched, 0x38)[0] & ~(1 << 30); struct.pack_into("<I", hatched, 0x38, ivs)
s5 = snap("map", 446, 0b11, [evo, hatched], box=enc(caught[:136]) + bytes(136 * 29))
assert [k for k, _ in happenings.diff(s4, s5)] == ["hatched"]

# datos a medio escribir: no se compara (sin avisos falsos)
bad = bytearray(enc(evo)); bad[0x20] ^= 0xFF
s6 = happenings.snapshot("map", {"zone": 446}, 0b11, [bytes(bad)], {})
assert s6["mons"] is None and happenings.diff(s5, s6) == []
# de la caja 1 a la caja 3: "moved" con la caja
s7 = happenings.snapshot("map", {"zone": 446}, 0b11, [enc(evo), enc(hatched)], {0: bytes(136 * 30), 2: enc(caught[:136]) + bytes(136 * 29)})
got = happenings.diff(s5, s7)
assert [k for k, _ in got] == ["moved"] and got[0][1]["where"] == "box3" and got[0][1]["from"] == "box1", got
print("ok avisos")
