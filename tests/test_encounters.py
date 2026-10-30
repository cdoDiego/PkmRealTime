"""Pruebas de encounters.py (zona y tabla de encuentros): python tests/test_encounters.py"""
import os, sys, struct
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import encounters, gamedata

# Tabla sintética: Bulbasaur 2-4 en el primer hueco de la hierba, tasa 10, cargada
raw = bytearray(encounters.SIZE); raw[0] = 10; raw[7] = 0x80
struct.pack_into("<HBB", raw, 8, 1, 2, 4)
struct.pack_into("<HBB", raw, 8 + 4 * 36, 129 | (1 << 11), 5, 15)   # Magikarp forma 1 en el primer hueco de surf
t = encounters.parse(bytes(raw))
assert t["loaded"] and t["grass"]["rate"] == 10 and t["grass"]["slots"][0] == {"species": 1, "name": "Bulbasaur", "form": 0, "min": 2, "max": 4}
assert len(t["surf"]["slots"]) == 5 and t["surf"]["slots"][0]["form"] == 1 and t["surf"]["slots"][0]["species"] == 129
loc, addr, got = encounters.parse_location(f"446:1:0x0223b800:{raw.hex()}")
assert loc["zone"] == 446 and loc["season"] == "summer" and addr == 0x0223B800 and got == bytes(raw), loc
assert encounters.parse_location("12:0:-:-")[1:] == (0, b"") and encounters.parse_location("-")[0] is None
print("ok tabla de encuentros")

# Con los datos de la ROM (si están): zona -> nombre y tabla; el volcado de combate (Ruta 19, verano) coincide con la ROM
if "zones" in gamedata.DATA and gamedata.rom_info().get("header_crc") == 0xD75C:
    assert encounters.place_name(446) == "Route 20"
    r20 = encounters.parse(encounters.rom_table(446, 1))
    assert [s["name"] for s in r20["grass"]["slots"][:2]] == ["Sunkern", "Sewaddle"]
    DUMP = os.path.join(ROOT, "dumps", "combate1.bin")
    if os.path.exists(DUMP):
        ram = open(DUMP, "rb").read()
        gd = (struct.unpack_from("<I", ram, 0x24)[0] & 0xFFFFFF) + 0x3666C
        zone, season = struct.unpack_from("<H", ram, gd + 0x114)[0], ram[gd + 0x1C8]
        ev = struct.unpack_from("<I", ram, gd + 0x158)[0] & 0xFFFFFF
        live = ram[ev + 0x38:ev + 0x38 + encounters.SIZE]
        assert encounters.rom_table(zone, season) == live, (zone, season)
        print("ok volcado = ROM en la zona", zone, encounters.place_name(zone))
    print("ok zonas de la ROM")
