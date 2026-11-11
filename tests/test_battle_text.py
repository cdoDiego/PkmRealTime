"""Pruebas de tools/battle_text.py (python tests/test_battle_text.py). Archivo de texto sintético."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import rom
import battle_text as bt

lines = [bt.encode(f"{{mon}} line {i}") for i in range(bt.FIRST_LINE)]
d = bt.build(lines)
assert bt.read_lines(d) == lines and len(d) % 4 == 0
out = rom.decode_text(bt.add_messages(d))
assert len(out) == bt.FIRST_LINE + 3 * len(bt.MESSAGES)
assert out[5] == "Ă\u0001\u0000 line 5"
assert out[bt.FIRST_LINE] == "Ă\u0001\u0000 is radiating\na dark aura!"
assert out[bt.FIRST_LINE + 2].startswith("The foe's ")       # tu Pokémon, el salvaje, el del rival
assert out[bt.FIRST_LINE + 3].endswith("a fairy aura!")
try:
    bt.add_messages(bt.build(lines[:-1]))                          # otro número de líneas: no se toca
    raise AssertionError("debía fallar")
except ValueError:
    pass
print("ok battle_text")
