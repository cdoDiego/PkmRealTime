"""Pruebas de tools/follower_models.py (python tests/test_follower_models.py). Datos sintéticos."""
import os, struct, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import follower_models as fm


def rec(uid, size=0, y=0):
    r = bytearray(28); struct.pack_into("<H", r, 0, uid); r[7] = size; struct.pack_into("<b", r, 14, y); r[16] = 0xE9
    return bytes(r)


table = struct.pack("<I", 4) + rec(0x0001) + rec(0x1086) + rec(0x1019, y=2) + rec(0x1100, size=2)
out, n = fm.lower_pokemon(table, -4)
ys = [struct.unpack_from("<b", out, 4 + 28 * i + 14)[0] for i in range(4)]
assert n == 2 and ys == [0, -4, -4, 0], ys                  # personas y modelos grandes, igual
assert all(out[4 + 28 * i + 16] == 0xE9 for i in range(4))  # el resto del registro no se toca
print("ok follower_models")
