"""Pruebas de wondercard.py (python tests/test_wondercard.py). Usa dumps/mapa1.bin si existe."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import datetime, random, struct
import config, wondercard as wc

rng = random.Random(5)

# el cifrado por rangos coincide con el del bloque entero
seed = 0xBFBF0000
plain = bytes(rng.randrange(256) for _ in range(wc.DATA_SIZE))
enc = wc.crypt(plain, seed)
assert wc.crypt(enc, seed) == plain
for start in (0, 2, 0x100, 0x1CC, 0xA8E):
    assert wc.crypt(enc[start:start + 2], seed, start) == plain[start:start + 2]

# tarjeta a medida
card = wc.pokemon_card(25, 10, [84, 45, 39], card_id=2000, title="Pikachu de prueba", tid=2000, shiny=True,
                       today=datetime.date(2026, 11, 3))
assert len(card) == wc.CARD_SIZE
s = wc.summary(card)
assert s == {"type": "pokemon", "id": 2000, "title": "Pikachu de prueba", "date": "03/11/2026", "used": False, "b4": 1,
             "species": 25, "level": 10, "egg": False, "shiny": True, "ot": "Regalo", "moves": [84, 45, 39, 0],
             "item": 0}, s
assert card[0x1E:0x34] == b"\xff" * 22 and card[0x43:0x49] == b"\xff" * 6
assert wc.summary(wc.item_card(50, card_id=7, title="Caramelo"))["item"] == 50

# escribir en un bloque vacío (cifrado) y comprobar al descifrar
block = wc.crypt(bytes(wc.DATA_SIZE), seed) + struct.pack("<I", seed)
o = wc.card_offset(3)
old, new = wc.patch(block, o, card)
assert old == block[o:o + wc.CARD_SIZE] and len(new) == wc.CARD_SIZE
block2 = block[:o] + new + block[o + wc.CARD_SIZE:]
p2 = wc.decrypt_block(block2)
assert p2[o:o + wc.CARD_SIZE] == card and not any(p2[:o]) and not any(p2[o + wc.CARD_SIZE:])
for cid in (0, 7, 8, 129, 2000, 2047):
    fo, fold, fnew = wc.flag_patch(block2, cid)
    b3 = block2[:fo] + fnew + block2[fo + 2:]
    assert wc.received_ids(wc.decrypt_block(b3)) == [cid]

# en los volcados reales el bloque descifra a ceros (álbum vacío)
dump = os.path.join(ROOT, "dumps", "mapa1.bin")
if os.path.exists(dump):
    ram = open(dump, "rb").read()
    ptr = struct.unpack_from("<I", ram, config.MAIN_POINTER_OFF)[0] & 0xFFFFFF
    blk = ram[ptr + wc.MYSTERY_PTR_OFF:ptr + wc.MYSTERY_PTR_OFF + wc.BLOCK_SIZE]
    assert not any(wc.decrypt_block(blk)), "el álbum del volcado no descifra a ceros"
    print("volcado: álbum vacío, semilla", hex(wc.seed_of(blk)))
print("wondercard OK")

# hueco libre e IDs para tarjetas propias
empty = bytes(wc.DATA_SIZE)
assert wc.free_slot(empty) == 0 and wc.free_card_id(empty) == 1500
full = bytearray(empty)
for i in range(wc.CARDS):
    o = wc.card_offset(i)
    full[o:o + wc.CARD_SIZE] = wc.set_card_id(card, 1500 + i)
assert wc.free_slot(bytes(full)) is None                          # 12 sin recoger
assert wc.free_card_id(bytes(full)) == 1512
full[wc.card_offset(5) + 0xB4] |= 2                               # la 5 ya se recogió: se puede reemplazar
assert wc.free_slot(bytes(full)) == 5
full[1500 >> 3] |= 1 << (1500 & 7)
assert wc.free_card_id(bytes(full)) == 1512
c7 = wc.set_card_id(card, 1777)
assert struct.unpack_from("<HH", c7, 0) == (1777, 0) and struct.unpack_from("<H", c7, 0xB0)[0] == 1777

# add_card_writes: tarjeta + bandera, y no repite la misma tarjeta
slot, writes = wc.add_card_writes(block, c7)
assert slot == 0 and len(writes) == 2
b = bytearray(block)
for o, old, new in writes:
    assert bytes(b[o:o + len(old)]) == old
    b[o:o + len(new)] = new
p = wc.decrypt_block(bytes(b))
assert wc.cards(p)[0] == c7 and wc.received_ids(p) == [1777]
try:
    wc.add_card_writes(bytes(b), c7)
    raise AssertionError("debió rechazar la tarjeta repetida")
except ValueError:
    pass
print("wondercard (álbum) OK")
