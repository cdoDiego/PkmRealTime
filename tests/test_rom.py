"""Pruebas de rom.py con la ROM de config.ROM_PATH (python tests/test_rom.py). Se saltan si no está la ROM."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import struct
import config, rom

path = config.rom_path()
if not path or not os.path.exists(path):
    print("sin ROM: pruebas saltadas"); sys.exit(0)
r = rom.Rom(path)
assert r.code in ("IRDO", "IREO"), r.code
d = rom.build_data(r)
sp = d["species"]
assert sp["1"]["name"] == "Bulbasaur" and sp["29"]["name"] == "Nidoran♀" and sp["501"]["name"] == "Oshawott"
assert sp["501"]["abilities"][0] == 67 and sp["501"]["learnset"][:2] == [[1, 33], [5, 39]]
assert d["move_pp"][33] == 35 and d["exp"][0][99] == 1000000 and d["exp"][5][99] == 1250000

# ROM "aleatorizada" simulada: se cambia una copia en memoria (el archivo no se toca)
fake = rom.Rom.__new__(rom.Rom)
fake.__dict__.update(r.__dict__)
data = bytearray(r.data)
fid = r._paths[rom.PERSONAL]
start = struct.unpack_from("<I", data, r._fat + 8 * fid)[0]
narc = r.file(rom.PERSONAL)
pos = struct.unpack_from("<H", narc, 0x0C)[0]
btaf_size = struct.unpack_from("<I", narc, pos + 4)[0]
s1 = struct.unpack_from("<I", narc, pos + 12 + 8 * 1)[0]           # Bulbasaur dentro del NARC
gmif = pos + btaf_size + struct.unpack_from("<I", narc, pos + btaf_size + 4)[0] + 8
off = start + gmif + s1
data[off + 0x18] = data[off + 0x19] = 37                            # Potencia
data[off + 0x15] = 5                                                # curva lenta
fake.data = bytes(data)
fd = rom.build_data(fake)
assert fd["species"]["1"]["abilities"][:2] == [37, 37] and fd["species"]["1"]["growth"] == 5

import gamedata, gift
saved = dict(gamedata.DATA)
gamedata.DATA.clear(); gamedata.DATA.update(fd)
t = {"name": "Diego".encode("utf-16-le") + b"\xff\xff" + bytes(4), "tid": 1, "sid": 2, "language": 2, "version": 22, "gender": 0}
p = gift.create(1, 10, t)
assert p[0x15] == 37                                                # el regalo sale con Potencia
assert struct.unpack_from("<I", p, 0x10)[0] == rom.EXP_TABLES[5][9] # experiencia de la curva lenta
gamedata.DATA.clear(); gamedata.DATA.update(saved)
print("ok ROM", r.code)
