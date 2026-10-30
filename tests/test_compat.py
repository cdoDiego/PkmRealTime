"""Pruebas de las firmas de código (compatibilidad con romhacks): python tests/test_compat.py"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bridge, config, rom_compare

# Lo que manda el Lua al final del POLL
assert bridge.parse_compat("faint=1,item=0,script=?") == {"faint": True, "item": False, "script": None}
assert bridge.parse_compat("-") == {}

# Sin comprobar o compatible: se deja pasar; distinto: el evento falla con un mensaje claro
bridge.game["compat"] = {"faint": True, "item": None, "script": False}
bridge.require_compat("faint")
bridge.require_compat("item")
try:
    bridge.require_compat("script"); raise SystemExit("debía fallar")
except ValueError as e:
    assert "romhack" in str(e)
bridge.game["mode"] = "map"
ev = bridge.Event(id=1, data=bridge.EventIn(type="teleport", zone="1").model_dump(), source="prueba")
try:
    bridge.build_commands(ev); raise SystemExit("debía fallar")
except ValueError as e:
    assert "guiones propios" in str(e)
bridge.game["compat"] = {}
print("ok puente")

# Las firmas del Lua se leen bien y coinciden con la ROM configurada (se salta si no está)
sigs = rom_compare.lua_sigs()
assert set(sigs) == {"faint", "inject", "item", "weather", "script", "encounters", "shiny"} and all(pairs for _, pairs in sigs.values())
path = config.rom_path()
if not path or not os.path.exists(path):
    print("sin ROM: pruebas de la ROM saltadas"); sys.exit(0)
_, _, a9r, arm9, ovs = rom_compare.load(path)
assert all(rom_compare.check_sigs(a9r, arm9, ovs).values()), rom_compare.check_sigs(a9r, arm9, ovs)
# Romhack simulado: se cambia un byte de check_fainted en una copia (el archivo no se toca)
ram, size, data = ovs[167]
addr = sigs["faint"][1][0][0]
data = bytearray(data); data[addr - ram] ^= 0xFF
ovs[167] = (ram, size, bytes(data))
res = rom_compare.check_sigs(a9r, arm9, ovs)
assert res["faint"] is False and res["script"] and res["item"], res
print("ok firmas en la ROM")
