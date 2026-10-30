"""Pruebas de boxes.py (cajas del PC): python tests/test_boxes.py"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import boxes

main = bytearray(boxes.MAIN_SIZE)
for n in range(24):
    name = f"BOX {n + 1}".encode("utf-16-le") + b"\xff\xff"
    main[boxes.NAMES_OFF + n * boxes.NAME_STRIDE:boxes.NAMES_OFF + n * boxes.NAME_STRIDE + len(name)] = name
main[boxes.CURRENT_OFF], main[boxes.COUNT_OFF] = 2, 8
b0, b5 = bytes(boxes.BOX_SIZE), b"\x01" * boxes.BOX_SIZE
got_main, found = boxes.parse_field(f"{main.hex()}|2:{b0.hex()}|5:{b5.hex()}")
assert got_main == bytes(main) and set(found) == {2, 5} and found[5] == b5
assert boxes.name(main, 0) == "BOX 1" and boxes.name(main, 23) == "BOX 24"
assert boxes.current(main) == 2 and boxes.count(main) == 8
assert boxes.parse_field("-") == (b"", {}) and boxes.parse_field(f"{main.hex()}|99:{b0.hex()}")[1] == {}
assert boxes.summary(b0) == []
print("ok cajas")
