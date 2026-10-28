"""Pruebas del dinero (python tests/test_money.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bridge

bridge.game["party_addr"] = 0x0221E42C                     # puntero 0x02204D04 en la partida de prueba
bridge.update_misc("141c000001000000")                     # 7188 y 1 medalla (leído en el juego)
assert (bridge.game["money"], bridge.game["badges"]) == (7188, 1)
addr = "0x2226724"                                         # puntero + 0x21A20
assert bridge.money_commands({"type": "give_money", "qty": 1000}) == f"SAVE;G {addr} 141c0000 fc1f0000"   # 8188
assert bridge.money_commands({"type": "take_money", "qty": 99999}).endswith(" 00000000")                 # no baja de 0
assert bridge.money_commands({"type": "set_money", "qty": 50_000_000}).endswith(" 7f969800")             # tope 9.999.999
for bad in [{"type": "give_money", "qty": -5}, {"type": "give_money"}]:
    try:
        bridge.money_commands(bad); raise SystemExit("debía fallar")
    except ValueError:
        pass
print("ok dinero")
