"""Pruebas de bag.py (python tests/test_bag.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import struct
import bag

def make(objetos=((4, 9),), medicinas=((17, 1),), clave=((621, 1),)):
    b = bytearray(bag.SIZE)
    for name, entries in (("objetos", objetos), ("medicinas", medicinas), ("clave", clave)):
        off, _ = bag.pocket_range(name)
        for i, (it, q) in enumerate(entries):
            struct.pack_into("<HH", b, off + 4 * i, it, q)
    return bytes(b)

b = make()
s = bag.summary(bag.give(b, 17, 5))
assert s["medicinas"] == [{"item": 17, "qty": 6}], s                     # suma a la Poción existente
s = bag.summary(bag.give(b, 18, 2))
assert s["medicinas"] == [{"item": 17, "qty": 1}, {"item": 18, "qty": 2}]  # nuevo, al final
s = bag.summary(bag.give(b, 155, 3))
assert s["bayas"] == [{"item": 155, "qty": 3}]                           # va al bolsillo correcto
s = bag.summary(bag.give(b, 4, 5000))
assert s["objetos"] == [{"item": 4, "qty": 999}]                         # tope 999
s = bag.summary(bag.give(b, 328, 5))
assert s["mt"] == [{"item": 328, "qty": 1}]                              # MT: tope 1

s = bag.summary(bag.take(b, 4, 3))
assert s["objetos"] == [{"item": 4, "qty": 6}]
s = bag.summary(bag.take(make(objetos=((4, 9), (2, 1), (3, 5))), 2))     # quitar todas y compactar
assert s["objetos"] == [{"item": 4, "qty": 9}, {"item": 3, "qty": 5}], s
assert bag.summary(bag.take(b, 4))["objetos"] == []

nb = bag.give(b, 18, 1)                                                  # solo cambia medicinas
off, n = bag.pocket_range("medicinas")
assert nb[:off] == b[:off] and nb[off + n:] == b[off + n:]

for fn, args in [(bag.give, (b, 621, 1)), (bag.give, (b, 16, 1)), (bag.give, (b, 9999, 1)),
                 (bag.give, (b, 17, 0)), (bag.take, (b, 18)), (bag.take, (b, 621)),
                 (bag.give, (make(objetos=((4, 999),)), 4, 1))]:
    try:
        fn(*args); raise SystemExit(f"debía fallar: {fn.__name__}{args[1:]}")
    except ValueError:
        pass
print("ok mochila")
