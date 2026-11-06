"""Registro del combate (EXPERIMENTAL): qué pasó en cada turno, para el jugador y para controlar al rival.

Fuentes:
  - Bloques del turno: lo que el servidor manda a la pantalla (comandos SC_*), que el Lua copia del adaptador del
    jugador en cuanto llegan (connector.lua) y battle_cmd.decode lee como el juego. Dicen quién usó qué movimiento,
    el daño, las curas, los cambios, los estados, las habilidades que se activaron y los objetos usados.
  - Foto al empezar cada turno (cuando se pide elegir acción): vida, PP, estado, cambios de estadísticas, condiciones,
    si está atrapado y si sigue un ataque encadenado o recarga.
Los textos de los mensajes del juego (MSG_*) no se traducen: solo se cuentan.
"""
import collections
import itertools
import struct
import time

import battle
import battle_cmd
import gamedata

STATUS_LABELS = {1: "parálisis", 2: "sueño", 3: "congelación", 4: "quemadura", 5: "envenenamiento"}
STAT_LABELS = {1: "Ataque", 2: "Defensa", 3: "Ataque Especial", 4: "Defensa Especial", 5: "Velocidad",
               6: "Precisión", 7: "Evasión"}
WEATHER_LABELS = {1: "sol", 2: "lluvia", 3: "granizo", 4: "tormenta de arena"}
MAX_TURNS = 300
# Mensajes del juego que sí se interpretan (btl_server_flow.c): golpe crítico (uno o varios objetivos), "no afecta"
MSG_STD_CRITICAL, MSG_SET_CRITICAL, MSG_SET_UNAFFECTED = 0x51, 0x180, 0xD8
KEEP_BATTLES = 3

_ids = itertools.count(1)
battles: collections.deque = collections.deque(maxlen=KEEP_BATTLES)   # el último es el actual
current: dict | None = None
version = 0                          # sube con cada cambio (para no reenviar el registro si no cambió)


def _name(n: int, kind: str) -> str:
    table = gamedata.DATA.get(kind, [])
    return table[n] if 0 <= n < len(table) else str(n)


def start() -> dict:
    """Combate nuevo."""
    global current, version
    current = {"id": next(_ids), "started": time.time(), "turn": 0, "turns": [], "revealed": {}, "lost_blocks": 0}
    battles.append(current)
    version += 1
    return current


def _mons(b: dict | None) -> dict:
    """pokeID → datos del combatiente (de battle.parse), con su lado."""
    out = {}
    for side in ("player", "enemy"):
        for m in (b or {}).get(side, []):
            out[m["poke_id"]] = {**m, "side": side}
    return out


def _label(mons: dict, poke_id: int) -> str:
    m = mons.get(poke_id)
    if m is None:
        return f"Pokémon {poke_id}"
    return f"tu {m.get('name', '?')}" if m["side"] == "player" else f"{m.get('name', '?')} rival"


def _actives(b: dict, side: str) -> list[dict]:
    idx = set(range(battle.ACTIVE_COUNT[side])) | {battle.SECOND_CLIENT}
    return [m for m in b.get(side, []) if m["index"] in idx and m["hp"] > 0]


def snapshot(b: dict) -> dict:
    """Los que están en el campo al empezar el turno."""
    out = {}
    for side, other in (("player", "enemy"), ("enemy", "player")):
        opponents = [battle.RAW[(other, m["index"], "real")][1] for m in _actives(b, other)
                     if (other, m["index"], "real") in battle.RAW]
        rows = []
        for m in _actives(b, side):
            raw = battle.RAW.get((side, m["index"], "real"), (0, b""))[1]
            rows.append({
                "index": m["index"], "name": m.get("name", "?"), "hp": m["hp"], "max_hp": m["max_hp"],
                "status": m.get("conditions", []),
                "moves": [{"move": x["name"], "pp": x["pp"], "max_pp": x["max_pp"]} for x in m.get("moves", [])],
                "stages": {k: v for k, v in m.get("stages", {}).items() if v},
                "volatile": [v["label"] + (f" ({v['move']})" if "move" in v else "") for v in m.get("volatile", [])],
                "locked": (m.get("locked") or {}).get("label"),
                "trapped": battle.trapped(raw, opponents) if len(raw) > battle.OFF_COND_FLAGS else None,
            })
        out[side] = rows
    return out


def _turn(n: int) -> dict:
    for t in reversed(current["turns"]):
        if t["turn"] == n:
            return t
    t = {"turn": n, "snapshot": None, "events": [], "messages": 0, "blocks": []}
    current["turns"].append(t)
    current["turns"].sort(key=lambda x: x["turn"])
    del current["turns"][:-MAX_TURNS]
    return t


def _reveal(mons: dict, poke_id: int, **what) -> None:
    m = mons.get(poke_id)
    if m is None or m["side"] != "enemy":
        return
    r = current["revealed"].setdefault(str(poke_id), {"name": m.get("name", "?"), "moves": {}, "ability": None,
                                                       "item": None})
    if "move" in what:
        r["moves"][what["move"]] = r["moves"].get(what["move"], 0) + 1
    for key in ("ability", "item"):
        if key in what:
            r[key] = what[key]


# Causas del daño y de las curas. El juego no dice la causa en el comando de la vida (OP_SUBTRACT_HP / OP_ADD_HP), pero
# la marca justo antes (btl_server_flow.c): una animación con su número (ServerDisplay_AddEffectAtPosition /
# ServerControl_ViewEffect: SC_EFFECT*, el número es el último argumento), el mensaje del clima, "usa su objeto"
# (USE_HELD_ITEM), la ventana de la habilidad (ABILITY_POPUP_IN ... OUT), el movimiento en curso (MOVE_MSG) y el final
# del turno (ServerControl_TurnCheck empieza con HIDE_MSG_WINDOW).
EFFECT_CAUSES = {0x257: ("status", "el veneno"), 0x258: ("status", "la quemadura"), 0x273: ("status", "la maldición"),
                 0x274: ("status", "la pesadilla"), 0x290: ("weather", "el clima")}
WEATHER_MSG_CAUSES = {0x18C: "la tormenta de arena", 0x18F: "el granizo"}


def _cause_text(cause: dict | None, mons: dict, target: int, heal: bool) -> str:
    if not cause:
        return ""
    k, n = cause["kind"], cause.get("name")
    if k == "move":
        if cause.get("by") == target:
            return f" con {n}"
        return f" por {n} de {_label(mons, cause['by'])}" if not heal else f" por {n}"
    if k == "recoil":
        return f" por el retroceso de {n}"
    if k == "item":
        own = cause.get("by") == target
        return (f" con su {n}" if heal else f" por su {n}") if own else f" por {n} de {_label(mons, cause['by'])}"
    if k == "ability":
        own = cause.get("by") == target
        return f" por su {n}" if own else f" por {n} de {_label(mons, cause['by'])}"
    if k in ("status", "weather"):
        return f" por {n}"
    if k == "confusion":
        return " al golpearse por la confusión"
    if k == "entry":
        return " al entrar al campo"
    if k == "end_turn":
        return " al final del turno"
    return ""


def events_of(cmds: list, mons: dict) -> list[dict]:
    """Comandos de un bloque → eventos legibles, con la causa de cada cambio de vida."""
    out = []
    ctx = {"move": None, "item": None, "ability": None, "effect": None, "end_turn": False, "entered": None}

    def add(kind, poke_id, text, **extra):
        side = mons.get(poke_id, {}).get("side") if poke_id is not None else None
        out.append({"type": kind, "side": side, "mon": poke_id, "text": text, **extra})

    def cause_for(target: int, heal: bool) -> dict | None:
        if ctx["effect"]:
            c, ctx["effect"] = ctx["effect"], None
            return c
        if ctx["ability"]:
            return ctx["ability"]
        if ctx["item"]:
            c, ctx["item"] = ctx["item"], None
            return c
        if ctx["move"]:
            by, move = ctx["move"]
            if by == target and not heal:
                return {"kind": "recoil", "name": move, "by": by}
            return {"kind": "move", "name": move, "by": by}
        if ctx["entered"] == target and not heal:
            return {"kind": "entry"}
        if ctx["end_turn"]:
            return {"kind": "end_turn"}
        return None

    for name, a in cmds:
        if name == "MOVE_MSG":
            mv = _name(a[1], "moves")
            ctx.update(move=(a[0], mv), item=None, effect=None, end_turn=False, entered=None)
            add("move", a[0], f"{_label(mons, a[0])} usó {mv}", move=mv)
            _reveal(mons, a[0], move=mv)
        elif name in ("OP_SUBTRACT_HP", "OP_ADD_HP"):
            heal = name == "OP_ADD_HP"
            cause = cause_for(a[0], heal)
            m = mons.get(a[0], {})
            pct = f" ({round(100 * a[1] / m['max_hp'])} %)" if m.get("max_hp") else ""
            verb = "recuperó" if heal else "perdió"
            add("heal" if heal else "damage", a[0],
                f"{_label(mons, a[0])} {verb} {a[1]} PS{pct}{_cause_text(cause, mons, a[0], heal)}",
                amount=a[1], target=_label(mons, a[0]),
                cause={k: (_label(mons, v) if k == "by" else v) for k, v in cause.items()} if cause else None)
        elif name in ("EFFECT", "EFFECT_BY_POS", "EFFECT_BETWEEN_POS"):
            if a[-1] in EFFECT_CAUSES:
                kind, label = EFFECT_CAUSES[a[-1]]
                if kind == "weather" and ctx["effect"] and ctx["effect"]["kind"] == "weather":
                    continue                          # el mensaje del clima ya dijo cuál
                ctx["effect"] = {"kind": kind, "name": label}
        elif name == "CONFUSION_DAMAGE":
            ctx["effect"] = {"kind": "confusion", "name": "confusión"}
        elif name == "HIDE_MSG_WINDOW":
            ctx.update(move=None, item=None, end_turn=True, entered=None)
        elif name == "DAMAGE" and a[1]:              # daño suelto (p. ej. golpe de un KO): con su crítico
            add("critical", a[0], f"¡Golpe crítico a {_label(mons, a[0])}!")
        elif name == "DAMAGE_PLURAL" and a[1] in (2, 3):   # [n, eficacia (1 normal, 2 muy, 3 poco), movimiento, pokeID...]
            who = ", ".join(_label(mons, m) for m in a[3:])
            text = "¡Es muy eficaz" if a[1] == 2 else "No es muy eficaz"
            add("effectiveness", a[3] if len(a) > 3 else None, f"{text} contra {who}!" if a[1] == 2 else
                f"{text} contra {who}...", effectiveness="super" if a[1] == 2 else "not_very")
        elif name == "MSG_STD" and a[0] == MSG_STD_CRITICAL:
            last = next((e for e in reversed(out) if e["type"] == "damage"), None)
            add("critical", last["mon"] if last else None, f"¡Golpe crítico{' a ' + last['target'] if last else ''}!")
        elif name == "MSG_SET" and a[0] == MSG_SET_CRITICAL and len(a) > 1:
            add("critical", a[1], f"¡Golpe crítico a {_label(mons, a[1])}!")
        elif name == "MSG_SET" and a[0] == MSG_SET_UNAFFECTED and len(a) > 1:
            add("immune", a[1], f"No afecta a {_label(mons, a[1])}")
        elif name == "MSG_SET" and a[0] in WEATHER_MSG_CAUSES:
            ctx["effect"] = {"kind": "weather", "name": WEATHER_MSG_CAUSES[a[0]]}
        elif name == "FAINT":
            add("faint", a[0], f"{_label(mons, a[0])} se debilitó")
        elif name == "OP_SET_CONDITION":
            label = STATUS_LABELS.get(a[1]) or battle.CONDITIONS.get(a[1], (None, f"condición {a[1]}"))[1]
            if a[1] == 5 and a[2] & 0x1FF == battle.TOXIC:      # Tóxico: veneno permanente con 15 "turnos"
                label = "envenenamiento grave"
            add("condition", a[0], f"{_label(mons, a[0])}: {label}", condition=label)
        elif name == "OP_CURE_CONDITION":
            add("cure", a[0], f"{_label(mons, a[0])} se curó de su estado")
        elif name == "OP_CURE_MOVE_CONDITION":
            label = battle.CONDITIONS.get(a[1], (None, f"condición {a[1]}"))[1]
            add("cure", a[0], f"{_label(mons, a[0])} ya no tiene {label}", condition=label)
        elif name in ("OP_RAISE_STAT_STAGE", "OP_LOWER_STAT_STAGE"):
            verb = "subió" if name == "OP_RAISE_STAT_STAGE" else "bajó"
            add("stat", a[0], f"{STAT_LABELS.get(a[1], a[1])} de {_label(mons, a[0])} {verb} {a[2]}",
                stat=STAT_LABELS.get(a[1], a[1]), delta=a[2] if verb == "subió" else -a[2])
        elif name == "ABILITY_POPUP_IN":
            ab = mons.get(a[0], {}).get("ability_now") or mons.get(a[0], {}).get("ability")
            ctx["ability"] = {"kind": "ability", "name": ab or "su habilidad", "by": a[0]}
            add("ability", a[0], f"Se activó {ab} de {_label(mons, a[0])}" if ab else
                f"Se activó la habilidad de {_label(mons, a[0])}", ability=ab)
            if ab:
                _reveal(mons, a[0], ability=ab)
        elif name == "ABILITY_POPUP_OUT":
            ctx["ability"] = None
        elif name == "OP_CHANGE_ABILITY":
            ab = _name(a[1], "abilities")
            add("ability", a[0], f"La habilidad de {_label(mons, a[0])} ahora es {ab}", ability=ab)
            _reveal(mons, a[0], ability=ab)
        elif name == "OP_CONSUME_ITEM":
            it = _name(a[1], "items")
            ctx["item"] = {"kind": "item", "name": it, "by": a[0]}
            add("item", a[0], f"{_label(mons, a[0])} gastó su {it}", item=it)
            _reveal(mons, a[0], item=f"{it} (gastado)")
        elif name == "USE_HELD_ITEM":
            m = mons.get(a[0], {})
            it = _name(m["item"], "items") if m.get("item") else None
            ctx["item"] = {"kind": "item", "name": it or "su objeto", "by": a[0]}
            add("item", a[0], f"{_label(mons, a[0])} usó su {it}" if it else f"{_label(mons, a[0])} usó su objeto",
                item=it)
            if it:
                _reveal(mons, a[0], item=it)
        elif name == "OP_SET_ITEM":
            it = _name(a[1], "items") if a[1] else "nada"
            add("item", a[0], f"{_label(mons, a[0])} ahora lleva {it}", item=it)
            _reveal(mons, a[0], item=it)
        elif name == "ILLUSION_BREAK":
            add("illusion", a[0], f"¡Se rompió la Ilusión de {_label(mons, a[0])}!")
        elif name == "RECALL_MSG":
            add("switch_out", a[1], f"Retira a {_label(mons, a[1])}")
        elif name == "OP_SEND_IN":
            side = "player" if a[0] in (0, 2) else "enemy"
            index = a[1] + (battle.SECOND_CLIENT if a[0] >= 2 else 0)
            pid, m = next(((k, x) for k, x in mons.items() if x["side"] == side and x["index"] == index), (None, None))
            who = (f"tu {m.get('name', '?')}" if side == "player" else f"{m.get('name', '?')} rival") if m else "?"
            ctx.update(move=None, item=None, entered=pid)
            out.append({"type": "switch_in", "side": side, "mon": pid, "text": f"Entra {who}"})
        elif name == "WEATHER_START":
            add("weather", None, f"Empieza: {WEATHER_LABELS.get(a[0], a[0])}")
        elif name == "WEATHER_END":
            add("weather", None, f"Termina: {WEATHER_LABELS.get(a[0], a[0])}")
        elif name == "OP_CREATE_SUBSTITUTE":
            add("substitute", a[0], f"{_label(mons, a[0])} creó un sustituto")
        elif name == "OP_DELETE_SUBSTITUTE":
            add("substitute", a[0], f"El sustituto de {_label(mons, a[0])} desapareció")
        elif name == "TRANSFORM":
            add("transform", a[0], f"{_label(mons, a[0])} se transformó en {_label(mons, a[1])}")
        elif name == "CHANGE_FORM":
            add("form", a[0], f"{_label(mons, a[0])} cambió de forma")
        elif name == "EXP_GAIN":
            add("exp", a[0], f"{_label(mons, a[0])} ganó {a[1]} puntos de experiencia", amount=a[1])
        elif name == "BALL_THROW":
            add("ball", None, f"Lanzas {_name(a[5], 'items')}: " + ("¡capturado!" if a[2] else f"{a[1]} sacudidas"))
    return out


def _fill_hp(events: list, mons: dict) -> None:
    """Vida tras cada cambio. La copia real ya tiene la vida del final de los bloques (el servidor calcula todo el
    turno antes de mandarlo), así que se va hacia atrás desde ella."""
    hp = {pid: m["hp"] for pid, m in mons.items() if "hp" in m}
    for e in reversed(events):
        pid = e.get("mon")
        if pid not in hp:
            continue
        if e["type"] in ("damage", "heal", "faint"):
            e["hp"], e["max_hp"] = hp[pid], mons[pid].get("max_hp")
            if e["type"] == "damage":
                hp[pid] = min(e["max_hp"] or 9999, hp[pid] + e["amount"])
            elif e["type"] == "heal":
                hp[pid] = max(0, hp[pid] - e["amount"])


def feed(b: dict | None, blocks: list) -> bool:
    """Un POLL: b = battle.parse (None fuera del combate), blocks = [(turno, bytes)] o ("lost", n).
    Devuelve True si el registro cambió."""
    global version
    if current is None:
        if not b:
            return False
        start()
    changed = False
    if b and b.get("turn", 0) > current["turn"]:
        current["turn"] = b["turn"]
        _turn(b["turn"])["snapshot"] = snapshot(b)
        changed = True
    mons = _mons(b) if b else current.get("_mons", {})
    if b:
        current["_mons"] = mons
    new_events = []
    for turn, data in blocks:
        if turn == "lost":
            current["lost_blocks"] += data
            continue
        t = _turn(turn)
        t["blocks"].append(data.hex())          # en crudo: para rehacer el registro (p. ej. estilo Showdown)
        changed = True
        try:
            cmds = battle_cmd.decode(data)
        except ValueError as e:                  # se guarda el bloque para investigarlo
            t["events"].append({"type": "error", "side": None, "mon": None, "text": f"bloque ilegible: {e}"})
            continue
        evs = events_of(cmds, mons)
        t["events"].extend(evs)
        new_events.extend(evs)
        t["messages"] += sum(1 for n, _ in cmds if n.startswith("MSG_"))
    if b and new_events:
        _fill_hp(new_events, mons)
    if changed:
        version += 1
    return changed


def parse_blocks(field: str) -> list:
    """"<turno>:<hex>|...|lost:<n>" (connector.lua) → [(turno, bytes)] y ("lost", n)."""
    out = []
    if field in ("", "-"):
        return out
    for part in field.split("|"):
        turn, _, data = part.partition(":")
        if turn == "lost":
            out.append(("lost", int(data)))
        elif data:
            out.append((int(turn), bytes.fromhex(data)))
    return out


def export(log: dict | None) -> dict | None:
    """Sin los datos internos."""
    if log is None:
        return None
    return {k: v for k, v in log.items() if not k.startswith("_")}
