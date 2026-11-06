"""Pruebas del registro del combate (battle_log.py y battle_cmd.decode) (python tests/test_battle_log.py)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # para importar los módulos de la raíz del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import battle, battle_cmd as bc, battle_log, gamedata
import dump_field

# el lector coincide con el codificador en todos los formatos que comparten
for i, (name, fmt) in enumerate(bc.READ_TABLE):
    if fmt not in ("", "MSG", "MSG_SE", "RESERVE") and i < len(bc.FORMATS):
        assert fmt == bc.FORMATS[i], (name, fmt, bc.FORMATS[i])

# bloque real (combate2): Pikachu usa Látigo y baja la Defensa del Purrloin; mensaje del juego al final
real = bytes.fromhex("00 04 01 01 00 06 01 00 59 00 00 27 00 30 00 40 27 00 00 0a 62 01 00 38 30 41"
                     " 00 5b 00 5a 00 00 00 0c 00 00 00 02 00 00 00 01 ff ff 00 00")
cmds = bc.decode(real)
assert [n for n, _ in cmds] == ["OP_SUBTRACT_PP", "OP_SET_MOVE_USED", "MOVE_MSG", "MOVE_ANIM", "OP_LOWER_STAT_STAGE",
                                "STAT_DOWN_EFFECT", "MSG_SET"], cmds
assert cmds[-1] == ("MSG_SET", [0x5A, 12, 2, 1])
# hueco reservado sin usar (rastreo del adaptador): se salta
assert [n for n, _ in bc.decode(bytes.fromhex("000400010006000059000021005f03000000003000402100"))] == \
    ["OP_SUBTRACT_PP", "OP_SET_MOVE_USED", "MOVE_MSG", "MOVE_ANIM"]
# ida y vuelta con el codificador
mine = bc.encode("OP_SUBTRACT_HP", 12, 7) + bc.encode("OP_SET_CONDITION", 12, 8, 0x123) + bc.encode("FAINT", 12)
assert bc.decode(mine) == [("OP_SUBTRACT_HP", [12, 7]), ("OP_SET_CONDITION", [12, 8, 0x123]), ("FAINT", [12])]

# bloque real (en vivo, 04-nov): Oshawott vuelve, entra Snivy, el Purrloin usa Arañazo. DAMAGE_PLURAL lleva detrás
# los pokeID golpeados (antes el lector se perdía ahí)
switch_turn = bytes.fromhex("003b0000003c00026c002c0000002c0c00002300002000002a00001200040000003d00210004600100066000590c000a005f03000000003008000a00000105000200330101000a05002d02b020000a00020018060020000a000a00190c000056000015022400300185002f00002e05002e0c")
cmds = bc.decode(switch_turn)
assert len(cmds) == 23 and cmds[-1] == ("OP_TURN_CHECK", [12]), cmds
assert ("DAMAGE_PLURAL", [1, 1, 10, 5]) in cmds and ("OP_SEND_IN", [0, 0, 4, 0]) in cmds
mons = {0: {"side": "player", "name": "Oshawott", "index": 4, "max_hp": 40},
        5: {"side": "player", "name": "Snivy", "index": 0, "max_hp": 29},
        12: {"side": "enemy", "name": "Purrloin", "index": 0, "max_hp": 17}}
battle_log.start()
assert [e["text"] for e in battle_log.events_of(cmds, mons)] == [
    "Retira a tu Oshawott", "Entra tu Snivy", "Purrloin rival usó Scratch",
    "tu Snivy perdió 2 PS (7 %) por Scratch de Purrloin rival"]
super_hit = bc.encode("OP_SUBTRACT_HP", 12, 9) + bc.encode("DAMAGE_PLURAL", 1, 2, 22) + bytes([12])     + bc.encode("MSG_STD", 0x51) + bc.encode("MSG_SET", 0xD8, 0)
texts = [e["text"] for e in battle_log.events_of(bc.decode(super_hit), mons)]
assert texts[1:] == ["¡Es muy eficaz contra Purrloin rival!", "¡Golpe crítico a Purrloin rival!", "No afecta a tu Oshawott"], texts

assert [e["text"] for e in battle_log.events_of([("OP_SET_CONDITION", [12, 5, battle.TOXIC])], mons)] ==     ["Purrloin rival: envenenamiento grave"]
# causas: movimiento, retroceso, objeto (Restos), habilidad, veneno, clima, al entrar y fin del turno
m2 = {**mons, 0: {**mons[0], "hp": 30}, 5: {**mons[5], "hp": 20}, 12: {**mons[12], "hp": 5, "ability_now": "Rough Skin"}}
blk = (bc.encode("MOVE_MSG", 5, 38) + bc.encode("OP_SUBTRACT_HP", 12, 4) + bc.encode("OP_SUBTRACT_HP", 5, 2)
       + bc.encode("ABILITY_POPUP_IN", 12) + bc.encode("OP_SUBTRACT_HP", 5, 3) + bc.encode("ABILITY_POPUP_OUT", 12)
       + bc.encode("HIDE_MSG_WINDOW", 0) + bc.encode("MSG_SET", 0x18C, 12) + bc.encode("EFFECT_BY_POS", 1, 0x290)
       + bc.encode("OP_SUBTRACT_HP", 12, 1) + bc.encode("USE_HELD_ITEM", 5) + bc.encode("OP_ADD_HP", 5, 1)
       + bc.encode("EFFECT_BY_POS", 1, 0x257) + bc.encode("OP_SUBTRACT_HP", 12, 2) + bc.encode("OP_SUBTRACT_HP", 0, 1)
       + bc.encode("OP_SEND_IN", 0, 0, 4, 0) + bc.encode("OP_SUBTRACT_HP", 5, 5))   # entra el del índice 0 (Snivy)
evs = battle_log.events_of(bc.decode(blk), {**m2, 5: {**m2[5], "item": 234}, 0: {**m2[0], "poke_id": 0}})
hp = [e for e in evs if e["type"] in ("damage", "heal")]
assert [e["text"].split(" PS")[1] for e in hp] == [
    " (24 %) por Double-Edge de tu Snivy", " (7 %) por el retroceso de Double-Edge", " (10 %) por Rough Skin de Purrloin rival",
    " (6 %) por la tormenta de arena", " (3 %) con su Leftovers", " (12 %) por el veneno", " (2 %) al final del turno",
    " (17 %) al entrar al campo"], [e["text"] for e in hp]
assert hp[0]["cause"] == {"kind": "move", "name": "Double-Edge", "by": "tu Snivy"}, hp[0]["cause"]
battle_log._fill_hp(evs, m2)                               # vida tras cada golpe, hacia atrás desde la del final
assert [(e["mon"], e["hp"]) for e in hp] == [(12, 8), (5, 27), (5, 24), (12, 7), (5, 25), (12, 5), (0, 30), (5, 20)],     [(e["mon"], e.get("hp")) for e in hp]

assert battle_log.parse_blocks("-") == []
assert battle_log.parse_blocks("2:0039 0c".replace(" ", "") + "|lost:3") == [(2, bytes.fromhex("00390c")), ("lost", 3)]

DUMP = os.path.join(ROOT, "dumps", "combate2.bin")
if os.path.exists(DUMP) and gamedata.DATA.get("move_info"):
    ram = open(DUMP, "rb").read()
    b = battle.parse(dump_field.field(ram, ",H:0:0:0,N:1"))
    battle_log.start()
    assert battle_log.feed(b, [(1, real)])
    t = battle_log.current["turns"][0]
    assert t["turn"] == 1 and t["messages"] == 1
    texts = [e["text"] for e in t["events"]]
    assert texts == ["tu Pikachu usó Tail Whip", "Defensa de Purrloin rival bajó 1"], texts
    snap = t["snapshot"]
    assert [m["name"] for m in snap["player"]] == ["Pikachu"] and [m["name"] for m in snap["enemy"]] == ["Purrloin"]
    assert snap["enemy"][0]["moves"][0] == {"move": "Scratch", "pp": snap["enemy"][0]["moves"][0]["pp"], "max_pp": 35}
    assert snap["enemy"][0]["trapped"] is None and snap["enemy"][0]["locked"] is None
    assert battle_log.current["revealed"] == {}               # el rival no ha mostrado nada todavía

    # el turno 2 del rival: Arañazo, golpe crítico, se activa su habilidad, gasta una baya y se debilita
    block2 = (bc.encode("MOVE_MSG", 12, 10) + bc.encode("OP_SUBTRACT_HP", 0, 6) + bc.encode("DAMAGE", 0, 1, 10)
              + bc.encode("ABILITY_POPUP_IN", 12) + bc.encode("OP_CONSUME_ITEM", 12, 155) + bc.encode("FAINT", 12)
              + bc.encode("OP_SEND_IN", 1, 0, 1, 2))
    assert not battle_log.feed({**b, "turn": 1}, [])          # sin bloques ni turno nuevo: nada cambia
    assert battle_log.feed({**b, "turn": 2}, [(2, block2)])
    t2 = battle_log.current["turns"][1]
    texts = [e["text"] for e in t2["events"]]
    assert texts[:2] == ["Purrloin rival usó Scratch",
                         f"tu Pikachu perdió 6 PS ({round(600 / b['player'][0]['max_hp'])} %) por Scratch de Purrloin rival"], texts
    assert "¡Golpe crítico a tu Pikachu!" in texts and "Se activó Unburden de Purrloin rival" in texts, texts
    assert any("gastó su" in x for x in texts) and "Purrloin rival se debilitó" in texts, texts
    rev = battle_log.current["revealed"]["12"]
    assert rev["moves"] == {"Scratch": 1} and rev["ability"] == "Unburden" and rev["item"].endswith("(gastado)"), rev
    # bloques que llegan después del combate (POLL ya fuera de él) siguen yendo al registro
    assert battle_log.feed(None, [(2, bc.encode("EXP_GAIN", 0, 30))])
    assert battle_log.current["turns"][1]["events"][-1]["text"] == "tu Pikachu ganó 30 puntos de experiencia"
    assert "_mons" not in battle_log.export(battle_log.current)
    print("ok registro (volcado combate2)")
print("ok registro")
