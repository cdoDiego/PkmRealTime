"""Pruebas de battle_cmd.py contra bloques reales de White 2 (python tests/test_battle_cmd.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import battle_cmd as bc

# Bloque real del turno de Látigo de Pikachu contra el Purrloin (volcado combate2, cola del cliente)
real = bytes.fromhex("00 04 01 01 00 06 01 00 59 00 00 27 00 30 00 40 27 00 00 0a 62 01 00 38 30 41"
                     " 00 5b 00 5a 00 00 00 0c 00 00 00 02 00 00 00 01 ff ff 00 00")
DUMP = os.path.join(ROOT, "dumps", "combate2.bin")
if os.path.exists(DUMP):   # los mismos bytes, leídos de la cola del cliente en el volcado
    ram = open(DUMP, "rb").read()
    assert ram[0x02260E78 - 0x02000000:][:len(real)] == real
mine = (bc.encode("OP_SUBTRACT_PP", 0, 1, 1) + bc.encode("OP_SET_MOVE_USED", 0, 1)
        + bc.encode("MOVE_MSG", 0, 39) + bc.encode("MOVE_ANIM", 0, 1, 39, 0)
        + bc.encode("OP_LOWER_STAT_STAGE", 12, 2, 1) + bc.encode("STAT_DOWN_EFFECT", 12, 2, 1)
        + bc.encode("MSG_SET", 0x5A, 12, 2, 1))
assert mine == real, (mine.hex(), real.hex())

# Del turno de Placaje contra el Patrat (combate1): MOVE_MSG y MOVE_ANIM
assert bc.encode("MOVE_MSG", 0, 33) == bytes.fromhex("005900002100")[:5]
assert bc.encode("UPDATE_HP_GAUGE", 12) == bytes.fromhex("00410c")
assert bc.encode("SET_GAUGE_STATUS", 12, 1) == bytes.fromhex("00350c01")
assert bc.block([["UPDATE_HP_GAUGE", 12], ["SET_GAUGE_STATUS", 12, 1]]) == bytes.fromhex("00410c00350c01")
try:
    bc.encode("UPDATE_HP_GAUGE", 1, 2); raise SystemExit("debía fallar")
except ValueError:
    pass
print("ok comandos de combate")
