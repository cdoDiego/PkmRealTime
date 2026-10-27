"""Pruebas del cifrado PK5 y de los cambios de HP, estado, curar, objeto y movimiento (python tests/test_pk5.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import struct
import pk5
ok = 0
for _ in range(500):
    p = bytearray(os.urandom(pk5.PARTY_SIZE))
    struct.pack_into("<I", p, pk5.OFF_STATUS, 0)
    struct.pack_into("<H", p, 6, pk5.checksum(p))
    struct.pack_into("<H", p, pk5.OFF_MAX_HP, 120); struct.pack_into("<H", p, pk5.OFF_CUR_HP, 120)
    enc = pk5.encrypt(p)
    assert pk5.decrypt(enc) == p
    box = pk5.encrypt(p[:136]); assert pk5.decrypt(box) == p[:136]
    e2 = pk5.set_status(pk5.set_hp(enc, 37), "burn")
    s = pk5.summary(pk5.decrypt(e2))
    assert s["hp"] == 37 and s["status"] == "burn" and s["valid"], s
    d = pk5.decrypt(e2)
    assert struct.unpack_from("<I", d, pk5.OFF_STATUS)[0] == 4          # Gen 5: quemado = 4
    assert d[:pk5.OFF_STATUS] == pk5.decrypt(pk5.set_hp(enc, 37))[:pk5.OFF_STATUS]  # nada más cambia
    ok += 1
print("ok", ok)

# ---- eventos de la fase B: curar, objeto, movimiento
def make_mon(moves=(33, 39, 0, 0)):
    p = bytearray(os.urandom(pk5.PARTY_SIZE))
    struct.pack_into("<I", p, pk5.OFF_STATUS, 4)                 # quemado
    struct.pack_into("<HH", p, pk5.OFF_CUR_HP, 5, 23)            # 5/23 HP
    for i, m in enumerate(moves):
        struct.pack_into("<H", p, pk5.OFF_MOVES + 2 * i, m)
    p[pk5.OFF_PP:pk5.OFF_PP + 4] = bytes([1, 2, 0, 0])
    p[pk5.OFF_PP_UPS:pk5.OFF_PP_UPS + 4] = bytes([0, 3, 0, 0])    # Látigo con 3 Más PP
    struct.pack_into("<H", p, 6, pk5.checksum(p))
    return pk5.encrypt(p)

for _ in range(100):
    enc = make_mon()
    s = pk5.summary(pk5.decrypt(pk5.heal(enc)))
    assert s["hp"] == 23 and s["status"] == "none" and s["valid"], s
    assert s["pp"] == [35, 48, 0, 0], s["pp"]                     # Placaje 35; Látigo 30 * 8 // 5 = 48

    s = pk5.summary(pk5.decrypt(pk5.set_item(enc, 234)))          # Restos
    assert s["held_item"] == 234 and s["valid"] and s["hp"] == 5

    s = pk5.summary(pk5.decrypt(pk5.set_move(enc, 2, 55)))        # Pistola Agua en el hueco 2
    assert s["moves"] == [33, 39, 55, 0] and s["pp"][2] == 25 and s["valid"], s
    s = pk5.summary(pk5.decrypt(pk5.set_move(enc, 1, 45)))        # Gruñido sustituye a Látigo
    assert s["moves"] == [33, 45, 0, 0] and s["pp"][1] == 40, s
    assert pk5.decrypt(pk5.set_move(enc, 1, 45))[pk5.OFF_PP_UPS + 1] == 0

for bad in [(3, 55), (0, 39), (0, 0), (4, 1), (2, 999)]:
    try:
        pk5.set_move(make_mon(), *bad); raise SystemExit(f"debía fallar: {bad}")
    except ValueError:
        pass
try:
    pk5.set_item(make_mon(), 9999); raise SystemExit("debía fallar: objeto 9999")
except ValueError:
    pass
print("ok fase B")
