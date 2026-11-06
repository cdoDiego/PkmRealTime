"""Control del rival en combate (EXPERIMENTAL): ver y cambiar lo que eligió la IA, y la pausa del turno.

Cómo decide el juego (src/ov167/btl_client.c y btl_server.c de pokebw2):
  - El servidor pide a cada cliente "elegir acción" (comando 3 del adaptador), "cambio tras debilitarse" (5) o
    "cambio a mitad de turno" (6, Ida y Vuelta...). La IA del rival responde enseguida (AISelectAction /
    AISelectChangePoke) y su respuesta queda en RAM, apuntada por el adaptador (+0x04), hasta que el servidor la copia
    tal cual, sin revisarla (BattleServer_StoreClientActions), cuando todos han respondido.
  - Cada acción es un u32 (BattleAction): bits 0-3 tipo (1 atacar, 2 objeto, 3 cambiar, 4 huir, 7 nada);
    atacar: bits 4-6 posición del objetivo, bits 7-22 movimiento; cambiar: bits 4-6 posición, 7-9 hueco del equipo,
    bit 10 "no queda nadie". Validado el 04-nov en combate2.bin: 0x501 = Arañazo contra la posición 0.
  - Estado del adaptador (+0x0E): 4 = respondido, pero el servidor espera a los demás; cuando todos respondieron lo lee
    en ese mismo frame y lo deja en 0. Así que con 1-4 la respuesta aún se puede cambiar (validado en combate2.bin:
    rival en 4 con su Arañazo, jugador en 3 eligiendo).
  - Pausa: el Lua pone ese estado en 2; el servidor espera hasta que lo vuelve a 3 (connector.lua).

El puente cambia la respuesta con G (guarda: la respuesta y el estado del adaptador deben seguir igual).
Las comprobaciones copian las del juego para el jugador (atrapado, ataque encadenado, Otra vez, Anulación...), porque
el servidor no las repite: lo que se escribe, se ejecuta.
"""
import struct

import battle
import gamedata

ACTIONS = {0: "nada", 1: "atacar", 2: "objeto", 3: "cambiar", 4: "huir", 5: "desplazar", 6: "rotar", 7: "sin acción",
           8: "fin de tiempo", 9: "error"}
FIGHT, ITEM, CHANGE, SKIP = 1, 2, 3, 7
REQUESTS = {3: "accion", 5: "cambio_debilitado", 6: "cambio_medio_turno"}
AI_ADAPTERS = (1, 3)            # rival y segundo rival (combate contra dos entrenadores)


def encode_fight(move: int, target: int) -> int:
    return FIGHT | (target & 7) << 4 | (move & 0xFFFF) << 7


def encode_change(pos: int, slot: int) -> int:
    return CHANGE | (pos & 7) << 4 | (slot & 7) << 7


def decode_action(raw: int, side_base: int = 0) -> dict:
    """u32 → {"action", ...}; side_base = 6 para el segundo rival (índices 6-11 de su lado en battle.RAW)."""
    kind = raw & 0xF
    out = {"raw": f"{raw:08x}", "action": ACTIONS.get(kind, kind)}
    names = gamedata.DATA.get("moves", [])
    if kind == FIGHT:
        move = (raw >> 7) & 0xFFFF
        out.update(move_id=move, move=names[move] if move < len(names) else move, target=(raw >> 4) & 7)
    elif kind == ITEM:
        item = (raw >> 7) & 0xFFFF
        items = gamedata.DATA.get("items", [])
        out.update(item_id=item, item=items[item] if item < len(items) else item)
    elif kind == CHANGE:
        slot = (raw >> 7) & 7
        out.update(pos=(raw >> 4) & 7, slot=side_base + slot, deplete=bool(raw >> 10 & 1))
        mon = battle.RAW.get(("enemy", side_base + slot, "real"))
        if mon and not out["deplete"]:
            out["name"] = _name(side_base + slot)
    return out


def _name(index: int) -> str:
    for m in (_battle or {}).get("enemy", []):
        if m["index"] == index:
            return m.get("name", "?")
    return "?"


_battle: dict | None = None    # último estado de combate (battle.parse), para los nombres


def _actions(a: dict) -> list[int]:
    reply = bytes.fromhex(a["reply"])
    return [struct.unpack_from("<I", reply, i)[0] for i in range(0, len(reply) - 3, 4)]


def status(b: dict | None) -> dict | None:
    """Lo que hay que mostrar del rival: qué pide el servidor, si respondió, qué eligió y si está en pausa."""
    global _battle
    _battle = b
    if not b or "adapters" not in b:
        return None
    ad = b["adapters"]
    p = ad.get(0)
    out = {"turn": b.get("turn", 0), "hold": b.get("hold"), "request": None, "player_ready": None, "rivals": []}
    if p:
        out["request"] = REQUESTS.get(p["cmd"]) if p["state"] in (1, 3, 4) else None
        out["player_ready"] = p["returned"]
    for i in AI_ADAPTERS:
        a = ad.get(i)
        if not a:
            continue
        r = {"adapter": i, "request": REQUESTS.get(a["cmd"]) if a["state"] in (1, 2, 3, 4) else None,
             "ready": a["returned"], "held": a["state"] == 2, "actions": []}
        if a["returned"] and r["request"]:
            r["actions"] = [decode_action(x, 6 if i == 3 else 0) for x in _actions(a)]
        out["rivals"].append(r)
    return out


def _enemy(index: int) -> tuple[int, bytes]:
    if ("enemy", index, "real") not in battle.RAW:
        raise ValueError(f"no hay rival con índice {index} en este combate")
    return battle.RAW[("enemy", index, "real")]


def _player_actives() -> list[bytes]:
    out = []
    for i in list(range(battle.ACTIVE_COUNT["player"])) + [battle.SECOND_CLIENT]:
        r = battle.RAW.get(("player", i, "real"))
        if r and struct.unpack_from("<H", r[1], battle.OFF_HP)[0] > 0:
            out.append(r[1])
    return out


def ready(b: dict | None, d: dict) -> bool:
    """El evento rival_action se puede aplicar ya: la IA respondió y el servidor aún no lo leyó."""
    if not b or "adapters" not in b:
        return False
    k = int(d["target"].get("slot", 0))
    a = b["adapters"].get(3 if k >= battle.SECOND_CLIENT else 1)
    if not a or not a["returned"] or a["state"] not in (1, 2, 3, 4) or a["cmd"] not in REQUESTS:
        return False
    if d.get("action") == "move" and a["cmd"] != 3:
        return False      # el ataque espera a la próxima vez que elija acción (p. ej. después de un cambio forzado)
    if a["cmd"] != 3:     # cambio tras debilitarse o a mitad de turno: solo si a este rival le toca sacar a alguien
        acts = _actions(a)
        e = k - (battle.SECOND_CLIENT if k >= battle.SECOND_CLIENT else 0)
        if not 0 <= e < len(acts) or acts[e] & 0xF != CHANGE or acts[e] >> 10 & 1:
            return False
    return True


def action_commands(b: dict, d: dict) -> str:
    """Comandos G que cambian la elección del rival (d = evento rival_action). ValueError si no se puede."""
    kind = d.get("action")
    if kind not in ("move", "switch"):
        raise ValueError("action debe ser 'move' (con move_slot 0-3) o 'switch' (con to_slot)")
    k = int(d["target"].get("slot", 0))
    second = k >= battle.SECOND_CLIENT
    adapter = 3 if second else 1
    base = battle.SECOND_CLIENT if second else 0
    a = b["adapters"].get(adapter)
    entry = k - base
    actions = _actions(a)
    if not 0 <= entry < len(actions):
        raise ValueError(f"el rival {k} no tiene que elegir nada ahora (hay {len(actions)} acciones en su respuesta)")
    old = actions[entry]
    n_active = battle.ACTIVE_COUNT["enemy"]
    if a["cmd"] == 3:
        _, raw = _enemy(k)
        lock = battle.locked(raw)
        if lock:
            raise ValueError(f"este turno el rival no elige: {lock['label']}")
        if old & 0xF in (0, SKIP):
            raise ValueError("este turno el rival no tiene acción (debilitado o sin poder actuar)")
    if kind == "switch":
        if d.get("to_slot") is None:
            raise ValueError("falta to_slot: el hueco del equipo del rival que entra (el que está en el campo es el 0)")
        to = int(d["to_slot"])
        slot = to - base
        if not n_active <= slot < 6:
            raise ValueError(f"to_slot debe ser un Pokémon del banquillo ({base + n_active}-{base + 5})")
        _, target = _enemy(to)
        if struct.unpack_from("<H", target, battle.OFF_HP)[0] == 0:
            raise ValueError(f"el Pokémon {to} del rival está debilitado")
        for j, other in enumerate(actions):
            if j != entry and other & 0xF == CHANGE and (other >> 7) & 7 == slot and not other >> 10 & 1:
                raise ValueError(f"el Pokémon {to} del rival ya va a entrar en otra posición")
        if a["cmd"] == 3:
            _, raw = _enemy(k)
            why = battle.trapped(raw, _player_actives())
            if why:
                raise ValueError(f"el rival no puede cambiar: {why}")
            pos = entry
        else:
            if old & 0xF != CHANGE or old >> 10 & 1:
                raise ValueError("el rival no tiene que sacar a nadie ahora")
            pos = (old >> 4) & 7
        new = encode_change(pos, slot)
    else:
        if a["cmd"] != 3:
            raise ValueError("el ataque solo se puede elegir cuando el rival elige acción")
        if d.get("move_slot") is None:
            raise ValueError("falta move_slot (0-3)")
        ms = int(d["move_slot"])
        if not 0 <= ms <= 3:
            raise ValueError("move_slot va de 0 a 3")
        _, raw = _enemy(k)
        move, pp = struct.unpack_from("<HB", raw, battle.OFF_MOVES + battle.MOVE_STRIDE * ms)
        if move == 0:
            raise ValueError(f"el rival no tiene movimiento en el hueco {ms}")
        if pp == 0:
            raise ValueError("ese movimiento no tiene PP")
        problem = unselectable(raw, move)
        if problem:
            raise ValueError(f"el rival no puede elegir ese movimiento: {problem}")
        target = (old >> 4) & 7 if old & 0xF == FIGHT else 0
        new = encode_fight(move, target)
    st = f"{a['state']:02x}"
    guard = f"G {a['addr'] + 0x0E:#x} {st} {st}"           # el mismo pedido, que el servidor aún no leyó
    if new == old:                                          # ya es lo que iba a hacer
        return guard
    reply_at = a["reply_addr"] + 4 * entry
    return f"{guard};G {reply_at:#x} {struct.pack('<I', old).hex()} {struct.pack('<I', new).hex()}"


def unselectable(raw: bytes, move: int):
    """Lo que el juego no deja elegir (IsUnselectableMove): Objeto elección, Otra vez, Mofa, Tormento, Anulación.
    Anticura, Gravedad y Cerca no se comprueban: el juego hace fallar el movimiento al usarlo."""
    def param(key):
        return battle.condition_param(battle.condition_raw(raw, battle.CONDITION_ID[key]))

    if battle.has_condition(raw, "choice_lock") and battle.item_usable(raw):
        lock = param("choice_lock")
        known = [struct.unpack_from("<H", raw, battle.OFF_MOVES + battle.MOVE_STRIDE * i)[0] for i in range(4)]
        if lock in known and lock != move:
            return "está bloqueado por su objeto elección"
    if battle.has_condition(raw, "encore") and param("encore") != move:
        return "tiene Otra vez"
    info = gamedata.DATA.get("move_info", [])
    if battle.has_condition(raw, "taunt") and move < len(info) and info[move][1] == 0:
        return "tiene Mofa (solo movimientos de daño)"
    if battle.has_condition(raw, "torment") and move == struct.unpack_from("<H", raw, battle.OFF_PREV_MOVE)[0]:
        return "tiene Tormento (no puede repetir)"
    if battle.has_condition(raw, "disable") and param("disable") == move:
        return "ese movimiento está anulado"
    return None


def auto_release(b: dict | None) -> str:
    """Suelta la pausa cuando el rival no tiene nada que decidir (p. ej. solo se debilitó el tuyo)."""
    if not b or not (b.get("hold") or {}).get("active"):
        return ""
    a = b.get("adapters", {}).get(1)
    if not a or a["state"] != 2 or not a["returned"]:
        return ""
    acts = _actions(a)
    if all(x & 0xF in (0, SKIP) or (x & 0xF == CHANGE and x >> 10 & 1) for x in acts):
        return "HR"
    return ""
