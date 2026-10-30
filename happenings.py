"""Avisos de lo que pasa en el juego (capturas, debilitados, medallas, cambios de zona...), comparando cada lectura con
la anterior. Los Pokémon se siguen por su PID, así se reconocen aunque cambien de hueco o pasen del equipo a la caja.

Solo se ven el equipo y la caja 1: un Pokémon que va a otra caja sale como "left".
"""
import struct

import gamedata
import gift
import pk5

GIFT_PLACES = 30000   # lugares de encuentro 30000+ (p. ej. 30008 "Tierra lejana"): regalos y eventos, no una zona


def _mon(plain: bytes, where: str, slot: int, party: bool) -> dict:
    s = pk5.summary(plain)
    egg_loc, met = struct.unpack_from("<HH", plain, 0x7E)
    m = {"pid": struct.unpack_from("<I", plain, 0)[0], "species": s["species"],
         "name": gamedata.DATA.get("species", {}).get(str(s["species"]), {}).get("name", ""),
         "egg": s["egg"], "where": where, "slot": slot, "met_location": met, "ball": plain[0x83]}
    if party:
        m.update(level=s["level"], hp=s["hp"])
    else:
        m["level"] = gift.summary(plain)["level"]
    return m


def snapshot(mode: str, location, badges_byte, party_raw: list, box_raw: bytes, box_slot_size: int) -> dict:
    """Lo que se compara entre lecturas. mons = None si algún Pokémon no se pudo leer (a medio escribir)."""
    snap = {"mode": mode, "zone": location["zone"] if location else None, "badges": badges_byte, "mons": None}
    if mode == "battle":            # en combate el equipo no se lee: se compara al salir
        return snap
    mons = {}
    try:
        for i, raw in enumerate(party_raw):
            plain = pk5.decrypt(raw)
            if not pk5.is_valid(plain):
                return snap
            mons[struct.unpack_from("<I", plain, 0)[0]] = _mon(plain, "party", i, True)
        for i in range(len(box_raw) // box_slot_size):
            chunk = box_raw[i * box_slot_size:(i + 1) * box_slot_size]
            if gift.is_empty_slot(chunk):
                continue
            plain = pk5.decrypt(chunk)
            if not pk5.is_valid(plain):
                return snap
            mons.setdefault(struct.unpack_from("<I", plain, 0)[0], _mon(plain, "box1", i, False))
    except (ValueError, IndexError, KeyError, struct.error):
        return snap
    snap["mons"] = mons
    return snap


def place_of_zone(zone) -> int:
    zones = gamedata.DATA.get("zones", [])
    return zones[zone][0] if zone is not None and 0 <= zone < len(zones) else -1


def _short(m: dict) -> dict:
    return {k: m[k] for k in ("pid", "species", "name", "level", "where", "slot") if k in m}


def diff(prev, cur) -> list:
    """[(tipo, datos)] entre dos lecturas. Sin lectura anterior no hay avisos (al conectar no se avisa de todo)."""
    if prev is None:
        return []
    out = []
    if prev["mode"] != "battle" and cur["mode"] == "battle":
        out.append(("battle_start", {}))
    if prev["mode"] == "battle" and cur["mode"] != "battle":
        out.append(("battle_end", {}))
    if cur["zone"] is not None and prev["zone"] is not None and cur["zone"] != prev["zone"]:
        out.append(("zone", {"zone": cur["zone"], "from": prev["zone"]}))
    if prev["badges"] is not None and cur["badges"] is not None:
        for b in range(8):
            if cur["badges"] >> b & 1 and not prev["badges"] >> b & 1:
                out.append(("badge", {"badge": b + 1, "count": bin(cur["badges"]).count("1")}))
    a, b = prev["mons"], cur["mons"]
    if a is None or b is None:
        return out
    here = place_of_zone(cur["zone"])
    for pid, m in b.items():
        old = a.get(pid)
        if old is None:
            caught = not m["egg"] and m["met_location"] == here and m["met_location"] < GIFT_PLACES
            out.append(("caught" if caught else "obtained", {**_short(m), "egg": m["egg"], "ball": m["ball"],
                                                              "met_location": m["met_location"]}))
            continue
        if old["egg"] and not m["egg"]:
            out.append(("hatched", _short(m)))
        elif old["species"] != m["species"] and not m["egg"]:
            out.append(("evolved", {**_short(m), "from_species": old["species"], "from_name": old["name"]}))
        if m["level"] > old["level"] and not m["egg"]:
            out.append(("level_up", {**_short(m), "from_level": old["level"]}))
        if "hp" in m and "hp" in old and not m["egg"]:
            if old["hp"] > 0 and m["hp"] == 0:
                out.append(("fainted", _short(m)))
            elif old["hp"] == 0 and m["hp"] > 0:
                out.append(("revived", _short(m)))
        if old["where"] != m["where"]:
            out.append(("moved", {**_short(m), "from": old["where"], "from_slot": old["slot"]}))
    for pid, old in a.items():
        if pid not in b:
            out.append(("left", _short(old)))   # liberado, a otra caja o intercambiado
    return out
