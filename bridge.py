"""Puente: API HTTP/WebSocket para la app externa + servidor TCP para el Lua de BizHawk.

Ejecutar:  pip install fastapi uvicorn
           python bridge.py

Protocolo con Lua (texto, una petición por mensaje):
  Lua -> Python:  "POLL <modo> <dir. equipo 0x...> <hex equipo|-> <hex mochila|-> <hex caja 1|-> <hex jugador|-> <código:crc> <combate|->"
  Python -> Lua:  comandos separados por ";"  (vacío = nada que hacer)
     W <addr> <hex>              escribe bytes
     G <addr> <hex_esperado> <hex_nuevo>   escribe solo si la memoria coincide
     SAVE                         savestate de seguridad
     LOAD                         restaura el savestate de seguridad
  Lua -> Python:  "RES <ok|fail> <detalle>"  tras ejecutar cada lote
BizHawk 2.6.2+ antepone "<longitud> " a todo mensaje, en ambos sentidos: aquí se quita al recibir y se añade al responder.
"""
import asyncio
import itertools
import json
import os
import struct
import time
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import bag
import battle
import config
import gamedata
import gift
import pk5

# ---------------------------------------------------------------- modelos
When = Literal["en_mapa", "en_combate", "cualquiera"]
WHEN_TO_MODES = {"en_mapa": {"map"}, "en_combate": {"battle"}, "cualquiera": {"map", "battle"}}
BATTLE_EVENTS = {"battle_set_hp", "battle_set_status"}   # siempre esperan al combate, aunque no se indique "when"


class EventIn(BaseModel):
    type: Literal["set_hp", "set_status", "heal", "set_item", "set_move", "give_item", "take_item",
                  "give_pokemon", "battle_set_hp", "battle_set_status", "rollback"]
    when: When = "en_mapa"
    target: dict = {}          # {"side": "player", "slot": 0}; heal sin slot = todo el equipo
    hp: Optional[int] = None
    status: Optional[str] = None
    item: Optional[int] = None       # set_item: nº de objeto (0 = quitar)
    move: Optional[int] = None       # set_move: nº de movimiento
    move_slot: Optional[int] = None  # set_move: hueco 0-3
    qty: Optional[int] = None        # give_item / take_item (take_item sin qty = todas)
    species: Optional[int] = None    # give_pokemon: nº de Pokédex (1-649)
    level: Optional[int] = None      # give_pokemon: 1-100 (por defecto 5)
    moves: Optional[list[int]] = None  # give_pokemon: 1-4 movimientos (por defecto, los de su nivel)
    shiny: bool = False
    gender: Optional[str] = None     # "macho" / "hembra"
    nature: Optional[int] = None     # 0-24
    hidden_ability: bool = False


@dataclass
class Event:
    id: int
    data: dict
    source: str
    state: str = "pendiente"   # pendiente | enviado | aplicado | fallo | cancelado
    detail: str = ""
    created: float = field(default_factory=time.time)


_ids = itertools.count(1)
events: dict[int, Event] = {}
queue: list[int] = []
game = {"mode": "unknown", "game": None, "data_ok": False, "party_addr": 0, "party": [], "bag": {}, "box1": [], "battle": None,
        "connected": False, "updated": 0.0}
NEEDS_DATA = {"heal", "set_move", "give_pokemon"}   # usan datos de la ROM (PP, especies, movimientos)
party_raw: list[bytes] = []
bag_raw: bytes = b""
box_raw: bytes = b""
trainer_raw: bytes = b""
in_flight: Optional[int] = None
ws_clients: set[WebSocket] = set()

# ---------------------------------------------------------------- lógica de eventos


def build_commands(ev: Event) -> str:
    """Convierte un evento en comandos para Lua. Lanza ValueError si no aplica."""
    d = ev.data
    if d["type"] == "rollback":
        return "LOAD"
    if d["type"] in BATTLE_EVENTS:   # fase 5 (experimental): escribe en las dos copias del combatiente
        if game["mode"] != "battle":
            raise ValueError("no hay combate en curso")
        side = d["target"].get("side", "enemy")
        if side not in ("player", "enemy"):
            raise ValueError("side debe ser 'player' o 'enemy'")
        slot = int(d["target"].get("slot", 0))
        if d["type"] == "battle_set_hp":
            return "SAVE;" + battle.set_hp_command(side, slot, int(need(d, "hp")))
        return "SAVE;" + battle.set_status_command(side, slot, str(need(d, "status")))
    if d["type"] in NEEDS_DATA and not game["data_ok"]:
        raise ValueError("gen5_data.json no es de la ROM que se está jugando: configura ROM_PATH en config_local.py "
                         "o ejecuta  python rom.py <ruta.nds>  y reinicia el puente")
    if d["target"].get("side", "player") != "player":
        raise ValueError("eventos sobre el rival requieren la estructura de batalla (fase 5)")
    if d["when"] == "en_combate" or game["mode"] == "battle":
        raise ValueError("en combate se escribe en la estructura de batalla (fase 5)")
    if d["type"] in ("give_item", "take_item"):
        return bag_commands(d)
    if d["type"] == "give_pokemon":
        return gift_commands(d)
    if d["type"] == "heal" and "slot" not in d["target"]:
        slots = list(range(len(party_raw)))
    else:
        slots = [int(d["target"].get("slot", 0))]
    cmds = ["SAVE"]
    for slot in slots:
        if not 0 <= slot < len(party_raw):
            raise ValueError(f"no hay Pokémon en el slot {slot}")
        old = party_raw[slot]
        if not pk5.is_valid(pk5.decrypt(old)):
            # el juego puede tener el Pokémon descifrado a medias; reescribirlo lo corrompería
            raise ValueError(f"datos del slot {slot} no válidos ahora mismo (checksum); reintenta en el mapa")
        new = apply_change(d, old)
        addr = game["party_addr"] + slot * config.PARTY_SLOT_SIZE
        cmds.append(f"G {addr:#x} {old.hex()} {bytes(new).hex()}")
    return ";".join(cmds)


def bag_commands(d: dict) -> str:
    if len(bag_raw) != bag.SIZE:
        raise ValueError("todavía no se ha leído la mochila")
    item = int(need(d, "item"))
    if d["type"] == "give_item":
        new = bag.give(bag_raw, item, int(d["qty"] or 1))
    else:
        new = bag.take(bag_raw, item, d["qty"])
    off, length = bag.pocket_range(bag.pocket_for(item)[0])   # solo se escribe ese bolsillo
    addr = game["party_addr"] - config.PARTY_PTR_OFF + config.BAG_PTR_OFF + off
    return f"SAVE;G {addr:#x} {bag_raw[off:off + length].hex()} {new[off:off + length].hex()}"


def gift_commands(d: dict) -> str:
    size = config.BOX_SLOT_SIZE
    if len(box_raw) != config.BOX_SLOTS * size or len(trainer_raw) != config.TRAINER_SIZE:
        raise ValueError("todavía no se han leído la caja 1 y los datos del jugador")
    slot = next((i for i in range(config.BOX_SLOTS) if gift.is_empty_slot(box_raw[i * size:(i + 1) * size])), None)
    if slot is None:
        raise ValueError("la caja 1 está llena")
    mon = gift.create(int(need(d, "species")), int(d["level"] or 5), gift.trainer_from_status(trainer_raw),
                      moves=d["moves"], item=int(d["item"] or 0), nature=d["nature"], shiny=d["shiny"],
                      gender=d["gender"], hidden_ability=d["hidden_ability"])
    old = box_raw[slot * size:(slot + 1) * size]
    addr = game["party_addr"] - config.PARTY_PTR_OFF + config.BOX_PTR_OFF + slot * size
    return f"SAVE;G {addr:#x} {old.hex()} {bytes(pk5.encrypt(mon)).hex()}"


def apply_change(d: dict, old: bytes) -> bytearray:
    """Bytes nuevos de un Pokémon según el evento. Lanza ValueError si los datos no sirven."""
    t = d["type"]
    if t == "set_hp":
        return pk5.set_hp(old, int(need(d, "hp")))
    if t == "set_status":
        if d["status"] not in pk5.STATUS_CODES:
            raise ValueError(f"estado desconocido: {d['status']} (válidos: {', '.join(pk5.STATUS_CODES)})")
        return pk5.set_status(old, d["status"])
    if t == "heal":
        return pk5.heal(old)
    if t == "set_item":
        return pk5.set_item(old, int(need(d, "item")))
    if t == "set_move":
        return pk5.set_move(old, int(need(d, "move_slot")), int(need(d, "move")))
    raise ValueError(f"tipo no implementado: {t}")


def need(d: dict, key: str):
    if d.get(key) is None:
        raise ValueError(f"falta el campo '{key}' para {d['type']}")
    return d[key]


def next_commands() -> str:
    global in_flight
    if in_flight is not None or game["party_addr"] == 0:
        return ""
    for eid in list(queue):
        ev = events[eid]
        when = "en_combate" if ev.data["type"] in BATTLE_EVENTS else ev.data["when"]
        if game["mode"] not in WHEN_TO_MODES[when] and ev.data["type"] != "rollback":
            continue
        queue.remove(eid)
        try:
            cmds = build_commands(ev)
        except ValueError as e:
            ev.state, ev.detail = "fallo", str(e)
            continue
        ev.state, in_flight = "enviado", eid
        return cmds
    return ""


def update_party(hexdata: str) -> None:
    raw = bytes.fromhex(hexdata) if hexdata else b""
    size = config.PARTY_SLOT_SIZE
    party_raw[:] = [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]
    game["party"] = [pk5.summary(pk5.decrypt(r)) for r in party_raw]
    # slots vacíos o inválidos se marcan con valid=False; la app puede ocultarlos


async def broadcast(msg: dict) -> None:
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)

# ---------------------------------------------------------------- servidor TCP para Lua


async def read_message(reader: asyncio.StreamReader) -> str:
    """Lee un mensaje completo de BizHawk: "<longitud> <mensaje>". Devuelve "" si se cerró."""
    try:
        head = await reader.readuntil(b" ")
        return (await reader.readexactly(int(head[:-1]))).decode(errors="replace").strip()
    except (asyncio.IncompleteReadError, ConnectionError):
        return ""


def update_game(field: str) -> None:
    """field = "IRDO:d75c" (código del cartucho y CRC de la cabecera)."""
    code, _, crc = field.partition(":")
    if not crc:
        return
    game["game"] = {"code": code, "header_crc": crc}
    info = gamedata.rom_info()
    game["data_ok"] = info.get("code") == code and f"{info.get('header_crc', -1):04x}" == crc


def prepare_data() -> None:
    """Genera gen5_data.json desde config.ROM_PATH si falta o es de otra ROM."""
    path = config.rom_path()
    if not path:
        print("ROM_PATH vacío (config_local.py): se usa gen5_data.json tal como está")
        return
    if not os.path.exists(path):
        print(f"AVISO: no existe la ROM {path}; se usa gen5_data.json tal como está")
        return
    import rom
    r = rom.Rom(path)
    info = gamedata.rom_info()
    if info.get("code") == r.code and info.get("header_crc") == r.header_crc:
        print(f"Datos del juego: {r.title} {r.code} (al día)")
        return
    print(f"Generando datos del juego desde {r.title} {r.code}...")
    with open(gamedata.PATH, "w", encoding="utf-8") as f:
        json.dump(rom.build_data(r), f, ensure_ascii=False, separators=(",", ":"))
    gamedata.load()


def update_box(hexbox: str, hextrainer: str) -> None:
    global box_raw, trainer_raw
    size = config.BOX_SLOT_SIZE
    raw = bytes.fromhex(hexbox) if hexbox not in ("", "-") else b""
    if len(raw) == config.BOX_SLOTS * size:
        box_raw = raw
        box = []
        for i in range(config.BOX_SLOTS):
            chunk = raw[i * size:(i + 1) * size]
            if not gift.is_empty_slot(chunk):
                try:
                    info = gift.summary(pk5.decrypt(chunk))
                    box.append({"slot": i, **{k: info[k] for k in ("species", "name", "level", "valid")}})
                except (ValueError, IndexError, KeyError, StopIteration):   # datos raros: se marcan, no se tumba el puente
                    box.append({"slot": i, "valid": False})
        game["box1"] = box
    t = bytes.fromhex(hextrainer) if hextrainer not in ("", "-") else b""
    if len(t) == config.TRAINER_SIZE:
        trainer_raw = t


def update_bag(hexdata: str) -> None:
    global bag_raw
    raw = bytes.fromhex(hexdata) if hexdata not in ("", "-") else b""
    if len(raw) == bag.SIZE:
        bag_raw = raw
        game["bag"] = bag.summary(raw)


async def handle_lua(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global in_flight
    game["connected"] = True
    print("Lua conectado")
    try:
        while msg := await read_message(reader):
            kind, _, rest = msg.partition(" ")
            if kind == "POLL":
                mode, _, rest = rest.partition(" ")
                addr, _, rest = rest.partition(" ")
                hexparty, hexbag, hexbox, hextrainer, gamefield, battlefield = (rest.split(" ") + ["-"] * 6)[:6]
                update_game(gamefield)
                try:
                    game["battle"] = battle.parse(battlefield) if mode == "battle" else None
                except (ValueError, IndexError, struct.error) as e:   # datos raros: se informan, no tumban el puente
                    game["battle"] = {"error": str(e)}
                game["mode"], game["updated"] = mode, time.time()
                game["party_addr"] = int(addr, 16) if addr else 0   # el puntero puede moverse
                if mode != "battle":   # en combate el bloque del equipo puede no estar al día
                    update_party("" if hexparty == "-" else hexparty)
                    update_bag(hexbag)
                    update_box(hexbox, hextrainer)
                # BizHawk 2.6.2+ solo lee respuestas "<longitud> <mensaje>"; sin eso se bloquea esperando
                payload = next_commands().encode()
                writer.write(str(len(payload)).encode() + b" " + payload)
                await writer.drain()
                await broadcast({"kind": "state", "state": game})
            elif kind == "RES" and in_flight is not None:
                ok, _, detail = rest.partition(" ")
                ev = events[in_flight]
                ev.state, ev.detail, in_flight = ("aplicado" if ok == "ok" else "fallo"), detail, None
                await broadcast({"kind": "event", "event": asdict(ev)})
    finally:
        game["connected"] = False
        in_flight = None
        print("Lua desconectado")

# ---------------------------------------------------------------- API

app = FastAPI(title="White 2 en tiempo real")


def auth(token: Optional[str]) -> str:
    if token not in config.API_TOKENS:
        raise HTTPException(401, "token inválido")
    return config.API_TOKENS[token]


@app.post("/events")
async def post_event(ev: EventIn, x_token: Optional[str] = Header(None)):
    source = auth(x_token)
    e = Event(id=next(_ids), data=ev.model_dump(), source=source)
    events[e.id] = e
    queue.append(e.id)
    return {"id": e.id, "state": e.state}


@app.get("/events")
async def list_events(x_token: Optional[str] = Header(None)):
    auth(x_token)
    return [asdict(e) for e in events.values()]


@app.delete("/events/{eid}")
async def cancel_event(eid: int, x_token: Optional[str] = Header(None)):
    auth(x_token)
    if eid not in events:
        raise HTTPException(404)
    ev = events[eid]
    if ev.state != "pendiente":   # ya enviado o terminado: no se puede deshacer así (usar /rollback)
        raise HTTPException(409, f"el evento está '{ev.state}', solo se cancelan los pendientes")
    queue.remove(eid)
    ev.state = "cancelado"
    await broadcast({"kind": "event", "event": asdict(ev)})
    return asdict(ev)


@app.get("/events/{eid}")
async def get_event(eid: int, x_token: Optional[str] = Header(None)):
    auth(x_token)
    if eid not in events:
        raise HTTPException(404)
    return asdict(events[eid])


@app.get("/state")
async def get_state(x_token: Optional[str] = Header(None)):
    auth(x_token)
    return game


@app.post("/rollback")
async def rollback(x_token: Optional[str] = Header(None)):
    return await post_event(EventIn(type="rollback", when="cualquiera"), x_token)


@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = ""):
    if token not in config.API_TOKENS:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)


async def main() -> None:
    prepare_data()
    lua_server = await asyncio.start_server(handle_lua, config.BRIDGE_HOST, config.LUA_PORT)
    api = uvicorn.Server(uvicorn.Config(app, host=config.BRIDGE_HOST, port=config.API_PORT, log_level="info"))
    print(f"Esperando a BizHawk en {config.BRIDGE_HOST}:{config.LUA_PORT}; API en :{config.API_PORT}")
    async with lua_server:
        await asyncio.gather(lua_server.serve_forever(), api.serve())


if __name__ == "__main__":
    asyncio.run(main())
