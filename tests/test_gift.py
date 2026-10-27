"""Pruebas de gift.py (python tests/test_gift.py). Necesita gen5_data.json (se genera desde la ROM).
Usa dumps/mapa3.bin si existe para comparar con Pokémon reales."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
import datetime, random, struct
import config, gamedata, gift, pk5

if not gamedata.DATA:
    print("sin gen5_data.json (genéralo con: python rom.py <ruta.nds>): pruebas saltadas"); sys.exit(0)

TRAINER = {"name": "Diego".encode("utf-16-le") + b"\xff\xff" + bytes(4), "tid": 56319, "sid": 632,
           "language": 2, "version": 22, "gender": 0}
rng = random.Random(1)

for _ in range(300):
    sp, lvl = rng.randint(1, 649), rng.randint(1, 100)
    info = gift.species_info(sp)
    shiny = rng.random() < 0.2
    p = gift.create(sp, lvl, TRAINER, shiny=shiny, rng=rng, today=datetime.date(2026, 10, 27))
    assert len(p) == 136 and pk5.is_valid(p)
    assert pk5.decrypt(pk5.encrypt(p)) == p                       # sobrevive al cifrado
    s = gift.summary(p)
    assert s["species"] == sp and s["level"] == lvl and s["shiny"] == shiny, s
    pid = struct.unpack_from("<I", p, 0)[0]
    assert (p[0x40] >> 1) & 3 == gift.gender_of(pid, info["gender"])   # género coherente con el PID
    assert p[0x15] in info["abilities"][:2]
    assert struct.unpack_from("<HH", p, 0x0C) == (56319, 632) and p[0x68:0x78] == TRAINER["name"]
    assert p[0x17] == 2 and p[0x5F] == 22 and p[0x84] == lvl and p[0x83] == 4
    assert list(p[0x7B:0x7E]) == [26, 10, 27] and struct.unpack_from("<H", p, 0x80)[0] == gift.DISTANT_LAND
    moves = [struct.unpack_from("<H", p, 0x28 + 2 * i)[0] for i in range(4)]
    assert moves[0] and all(p[0x30 + i] == pk5.move_pp.max_pp(m) for i, m in enumerate(moves))
    assert struct.unpack_from("<I", p, 0x38)[0] >> 30 == 0           # ni huevo ni mote

# casos concretos
p = gift.create(501, 6, TRAINER, rng=rng)
assert gift.summary(p)["moves"] == ["Tackle", "Tail Whip"]
assert p[0x48:0x5E].decode("utf-16-le").split("\uffff")[0] == "Oshawott"
assert gift.create(29, 5, TRAINER, rng=rng)[0x48 + 14:0x48 + 16] == b"\x6e\x24"   # ♀ de Nidoran
assert (gift.create(29, 5, TRAINER, rng=rng)[0x40] >> 1) & 3 == 1               # Nidoran♀ siempre hembra
assert (gift.create(81, 5, TRAINER, rng=rng)[0x40] >> 1) & 3 == 2               # Magnemite sin género
assert (gift.create(1, 5, TRAINER, gender="hembra", rng=rng)[0x40] >> 1) & 3 == 1
p = gift.create(1, 5, TRAINER, hidden_ability=True, rng=rng)
assert p[0x15] == 34 and p[0x42] & 1                                          # Clorofila
p = gift.create(1, 5, TRAINER, moves=[33, 76], item=234, nature=3, rng=rng)
assert gift.summary(p)["moves"] == ["Tackle", gift.DATA["moves"][76]] and gift.summary(p)["item"] == "Leftovers" and p[0x41] == 3
for bad in [dict(species=0), dict(species=650), dict(level=0), dict(level=101), dict(moves=[33, 33]),
            dict(moves=[1, 2, 3, 4, 5]), dict(item=9999), dict(species=29, gender="macho")]:
    args = {"species": 1, "level": 5, **bad}
    try:
        gift.create(args.pop("species"), args.pop("level"), TRAINER, rng=rng, **args)
        raise SystemExit(f"debía fallar: {bad}")
    except ValueError:
        pass

# hueco vacío = Pokémon cifrado con PID 0 y especie 0
assert gift.is_empty_slot(pk5.encrypt(bytearray(136)))
assert not gift.is_empty_slot(pk5.encrypt(gift.create(1, 5, TRAINER, rng=rng)))

# comparación con datos reales de la partida
DUMP = os.path.join(ROOT, "dumps", "mapa3.bin")
if os.path.exists(DUMP):
    ram = open(DUMP, "rb").read()
    ptr = struct.unpack_from("<I", ram, 0x24)[0] & 0xFFFFFF
    t = gift.trainer_from_status(ram[ptr + config.TRAINER_PTR_OFF: ptr + config.TRAINER_PTR_OFF + config.TRAINER_SIZE])
    osha = pk5.decrypt(ram[ptr + config.PARTY_PTR_OFF: ptr + config.PARTY_PTR_OFF + 220])
    assert t == gift.trainer_from_mon(osha), (t, gift.trainer_from_mon(osha))   # mismo entrenador que Oshawott
    box = ram[ptr + config.BOX_PTR_OFF: ptr + config.BOX_PTR_OFF + 0xFF0]
    assert gift.is_empty_slot(box[136:272])                                     # caja 1 hueco 2: vacío
    print("ok comparación con la partida real")
print("ok regalos")
