"""Pruebas de set_shiny_odds (sin juego): python tests/test_shiny.py"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import bridge, config, rom_compare

addr, orig = bridge.SHINY_PATCH["IRDO"]
eff = lambda b: (b[0] if b[-2:] == bytes.fromhex("0026") else b[0] * ((1 << (int.from_bytes(b[-2:], "little") >> 6)) - 1))
for odds in (4000, 1000, 100, 32, 10, 2):
    b = bytes.fromhex(bridge.shiny_patch_bytes(orig, bridge.shiny_rolls(odds)))
    assert len(b) == len(bytes.fromhex(orig)) and b[1:-2] == bytes.fromhex(orig)[1:-2]   # solo cambian los extremos
    p = 1 - (1 - 1 / bridge.shiny_base()) ** eff(b)
    assert abs(1 / p - odds) / odds < 0.12, (odds, 1 / p)
    sh = int.from_bytes(b[-2:], "little")
    assert b[-2:] == bytes.fromhex("0026") or (sh & 0xF83F) == 0                            # lsls r0, r0, #s

bridge.game.update(game={"code": "IRDO"}, compat={"shiny": True})
assert bridge.shiny_command(100).startswith(f"P {addr:#x} {orig} 52")
assert bridge.shiny_command(None) == f"P {addr:#x} {orig} {orig}" and bridge.shiny_odds is None
for bad in (1, 0):
    try:
        bridge.shiny_command(bad); raise SystemExit("debía fallar")
    except ValueError:
        pass
bridge.game["compat"] = {"shiny": False}
try:
    bridge.shiny_command(100); raise SystemExit("debía fallar (firma)")
except ValueError as e:
    assert "variocolor" in str(e)
bridge.game.update(compat={}, game=None)
print("ok puente")

path = config.rom_path()
if not path or not os.path.exists(path):
    print("sin ROM: prueba de la ROM saltada"); sys.exit(0)
code, _, _, _, ovs = rom_compare.load(path)
if code == "IRDO":
    ram, _, data = ovs[36]
    assert data[addr - ram:addr - ram + len(orig) // 2].hex() == orig, "el código original no coincide con la ROM"
    print("ok código original en la ROM")

# ROM con otro umbral de variocolor (Redux: < 128, 1/512): la probabilidad base y el PID de los regalos lo siguen
import gamedata, gift, random
saved = gamedata.DATA.get("shiny_threshold")
gamedata.DATA["shiny_threshold"] = 128
assert bridge.shiny_base() == 512 and bridge.shiny_rolls(512) == 1 and bridge.shiny_rolls(2) > 300
assert gift.is_shiny(100 << 16, 0, 0) and not gift.is_shiny(200 << 16, 0, 0)
rng = random.Random(1)
assert all(gift.is_shiny(gift.make_pid(rng, 7, 9, 127, True, None), 7, 9) for _ in range(50))
try:
    bridge.game.update(game={"code": "IRDO"}, compat={"shiny": True})
    assert bridge.shiny_command(512).endswith(f"{orig} {orig}")         # 1/512 ya es lo normal: sin parche
finally:
    bridge.game.update(compat={}, game=None); bridge.shiny_odds = None
    gamedata.DATA.pop("shiny_threshold", None)
    if saved is not None:
        gamedata.DATA["shiny_threshold"] = saved
assert bridge.shiny_base() == 65536 // gamedata.shiny_threshold()
print("ok umbral de variocolor")
