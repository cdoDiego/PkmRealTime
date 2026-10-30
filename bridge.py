"""Puente: API HTTP/WebSocket para la app externa + servidor TCP para el Lua de BizHawk.

Ejecutar:  pip install fastapi uvicorn websockets
           python bridge.py

Protocolo con Lua (texto, una petición por mensaje):
  Lua -> Python:  "POLL <modo> <dir. equipo 0x...> <hex equipo|-> <hex mochila|-> <hex caja 1|-> <hex jugador|-> <código:crc> <combate|->
                   <hex dinero|-> <compatibilidad: faint=1,inject=?,...|-> <zona:estación:dir. encuentros:hex encuentros|->"
                  (compatibilidad: 1 = código esperado, 0 = distinto, ? = sin ver; sin tabla de encuentros: "-" en sus campos)
  Python -> Lua:  comandos separados por ";"  (vacío = nada que hacer)
     W <addr> <hex>              escribe bytes
     G <addr> <hex_esperado> <hex_nuevo>   escribe solo si la memoria coincide
     SAVE                         savestate de seguridad
     LOAD                         restaura el savestate de seguridad
  Lua -> Python:  "RES <ok|fail> <detalle>"  tras ejecutar cada lote
BizHawk 2.6.2+ antepone "<longitud> " a todo mensaje, en ambos sentidos: aquí se quita al recibir y se añade al responder.
"""
import asyncio
import collections
import itertools
import json
import os
import struct
import time
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

import bag
import boxes
import battle
import battle_cmd
import config
import effects
import encounters
import field_script
import gamedata
import gift
import happenings
import pc
import roulette
import pk5

# ---------------------------------------------------------------- modelos
When = Literal["en_mapa", "en_combate", "cualquiera"]
WHEN_TO_MODES = {"en_mapa": {"map"}, "en_combate": {"battle"}, "cualquiera": {"map", "battle"},
                 "cualquiera_incluso_menu": {"map", "battle", "menu"}}   # solo para las herramientas de investigación
BATTLE_EVENTS = {"battle_set_hp", "battle_set_status", "battle_set_stage", "battle_set_pp", "battle_set_weather",
                 "battle_set_item"}   # siempre esperan al combate
FIELD_SCRIPT_EVENTS = {"start_wild_battle", "start_trainer_battle", "set_weather", "teleport", "give_egg"}   # esperan al mapa (personaje libre)


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")   # un campo mal escrito o mal colocado da error en vez de ignorarse

    type: Literal["set_hp", "set_status", "heal", "set_item", "set_move", "set_egg_cycles", "give_item", "take_item",
                  "give_pokemon", "give_egg", "move_pokemon", "remove_pokemon", "battle_set_hp", "battle_set_status",
                  "battle_set_stage", "battle_set_pp", "battle_set_weather", "battle_set_item", "give_money", "take_money", "set_money", "set_season",
                  "start_wild_battle", "start_trainer_battle", "set_weather", "teleport",
                  "debug_peek", "debug_poke", "debug_inject", "rollback"]
    when: When = "en_mapa"
    target: dict = {}          # {"side": "player", "slot": 0}; heal sin slot = todo el equipo; {"box": 2, "slot": 0} = caja
    hp: Optional[int] = None
    status: Optional[str] = None
    turns: Optional[int] = None      # sleep: turnos sin atacar (1-6, por defecto 3); battle_set_weather: turnos (sin turns = sin fin)
    item: Optional[int] = None       # set_item / battle_set_item: nº de objeto (0 = quitar)
    move: Optional[int] = None       # set_move: nº de movimiento
    move_slot: Optional[int] = None  # set_move: hueco 0-3
    qty: Optional[int] = None        # give_item / take_item (sin qty = todas); give/take/set_money: cantidad
    species: Optional[int] = None    # give_pokemon: nº de Pokédex (1-649)
    level: Optional[int] = None      # give_pokemon: 1-100 (por defecto 5)
    moves: Optional[list[int]] = None  # give_pokemon: 1-4 movimientos (por defecto, los de su nivel)
    shiny: bool = False
    gender: Optional[str] = None     # "macho" / "hembra"
    nature: Optional[int] = None     # 0-24
    hidden_ability: bool = False
    stat: Optional[str] = None       # battle_set_stage: atk, def, spa, spd, spe, acc, eva
    stage: Optional[int] = None      # battle_set_stage: valor final -6..+6
    delta: Optional[int] = None      # battle_set_stage: cuánto subir (+) o bajar (-)
    pp: Optional[int] = None         # battle_set_pp: PP (sin pp = al máximo)
    addr: Optional[str] = None       # debug_peek / debug_poke: dirección, ej. "0x022A8620"
    length: Optional[int] = None     # debug_peek: bytes a leer (máx. 1024)
    data: Optional[str] = None       # debug_poke: bytes en hex, ej. "01000000"
    expect: Optional[str] = None     # debug_poke: bytes que debe haber antes (opcional, como guarda)
    commands: Optional[list] = None  # debug_inject: [["UPDATE_HP_GAUGE", 12], ["SET_GAUGE_STATUS", 12, 1]]
    show: bool = True                # battle_set_hp / battle_set_status: actualizar también la pantalla
    trainer: Optional[int] = None    # start_trainer_battle: nº de entrenador (de la ROM)
    trainer2: Optional[int] = None   # start_trainer_battle: segundo entrenador (combate doble contra los dos)
    weather: Optional[str] = None    # set_weather: rain, snow, sandstorm... o número; battle_set_weather: none, sun, rain, sandstorm, hail
    destination: Optional[str] = None  # give_pokemon: "box1" (por defecto) o "party"; move_pokemon: "party" o "box1"-"box24"
    to_slot: Optional[int] = None      # move_pokemon a una caja: hueco 0-29 (por defecto, el primero libre)
    form: Optional[int] = None       # give_pokemon al equipo / start_wild_battle: forma
    no_flee: bool = False            # start_wild_battle: no se puede huir
    ball: Optional[int] = None       # give_pokemon al equipo: ball (4 = Poké Ball)
    zone: Optional[str] = None       # teleport: ciudad (aspertia, castelia...) o número de zona
    x: Optional[int] = None          # teleport: casilla (opcional, con z)
    z: Optional[int] = None
    season: Optional[str] = None     # set_season: spring/summer/autumn/winter (primavera/verano/otoño/invierno) o 0-3
    hatch_cycles: Optional[int] = None   # give_egg / set_egg_cycles: ciclos para eclosionar (0-255; 0 = casi ya)
    persist: bool = False            # set_weather: volver a ponerlo cada vez que se regresa al mapa tras un combate


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
pending_eggs: list = []   # give_egg con hatch_cycles: especie, ciclos y huevos de esa especie que ya había
persistent_weather: Optional[str] = None   # clima que se repone al volver de cada combate (set_weather con persist)
game = {"mode": "unknown", "game": None, "data_ok": False, "party_addr": 0, "party": [], "bag": {}, "box1": [], "battle": None,
        "money": None, "badges": None, "compat": {},
        "location": None, "encounters": None, "boxes": [], "box_current": None,
        "connected": False, "updated": 0.0}
NEEDS_DATA = {"heal", "set_move", "give_pokemon"}   # usan datos de la ROM (PP, especies, movimientos)
party_raw: list[bytes] = []
bag_raw: bytes = b""
box_raw: bytes = b""          # caja 1 (regalos)
box_main: bytes = b""         # bloque 0 de las cajas: nombres, caja abierta, cuántas hay
box_cache: dict = {}          # nº de caja (desde 0) -> sus datos, tal como llegaron por última vez
missing_polls: dict = {}      # PID -> lecturas seguidas sin verlo (para no avisar "left" antes de releer todas las cajas)
trainer_raw: bytes = b""
misc_raw: bytes = b""          # dinero y medallas
enc_raw: bytes = b""           # tabla de encuentros de la zona, tal como está en la RAM
enc_addr: int = 0
last_snap = None               # última lectura para los avisos (happenings.py)
happening_log: collections.deque = collections.deque(maxlen=500)
_happening_ids = itertools.count(1)
in_flight: Optional[int] = None


class WsClient:
    """Un overlay/app conectado por WebSocket. Tiene su propia cola y su propia tarea de envío: si el navegador deja de
    leer (pestaña congelada, DevTools en pausa), solo se atrasa él; el puente sigue contestando al Lua y el juego no se traba."""
    MAX_PENDING = 200          # avisos y eventos sin enviar; si se pasa, el cliente se da por muerto
    SEND_TIMEOUT = 10          # segundos para enviar un mensaje antes de cerrar la conexión

    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.pending: collections.deque = collections.deque()   # avisos y eventos: se mandan todos, en orden
        self.state: Optional[str] = None                        # estado: solo importa el último
        self.wake = asyncio.Event()
        self.dead = False

    def push(self, text: str, is_state: bool) -> None:
        if self.dead:
            return
        if is_state:
            self.state = text
        elif len(self.pending) >= self.MAX_PENDING:
            self.dead = True
        else:
            self.pending.append(text)
        self.wake.set()

    async def run(self) -> None:
        try:
            while not self.dead:
                await self.wake.wait()
                self.wake.clear()
                while not self.dead and (self.pending or self.state is not None):
                    if self.pending:
                        text = self.pending.popleft()
                    else:
                        text, self.state = self.state, None
                    await asyncio.wait_for(self.ws.send_text(text), self.SEND_TIMEOUT)
        except Exception:
            pass
        finally:
            self.dead = True
            ws_clients.discard(self)
            try:
                await asyncio.wait_for(self.ws.close(), 1)
            except Exception:
                pass


ws_clients: set[WsClient] = set()

# ---------------------------------------------------------------- lógica de eventos


def build_commands(ev: Event) -> str:
    """Convierte un evento en comandos para Lua. Lanza ValueError si no aplica."""
    d = ev.data
    unknown = set(d["target"]) - {"side", "slot", "box"}
    if unknown:
        raise ValueError(f"target solo admite side, slot y box, no {sorted(unknown)}")
    if "box" in d["target"] and d["type"] not in ("move_pokemon", "remove_pokemon"):
        raise ValueError("target.box solo vale para move_pokemon y remove_pokemon")
    if d["type"] == "rollback":
        return "LOAD"
    if d["type"] in ("debug_peek", "debug_poke", "debug_inject"):   # herramientas de investigación
        if not getattr(config, "DEBUG_WRITES", False):
            raise ValueError("herramientas de investigación desactivadas: pon DEBUG_WRITES = True en config_local.py")
        if d["type"] == "debug_inject":
            return f"J {battle_cmd.block(need(d, 'commands')).hex()}"
        addr = int(str(need(d, "addr")), 16)
        if not 0x02000000 <= addr < 0x02400000:
            raise ValueError("la dirección debe estar en la Main RAM (0x02000000-0x023FFFFF)")
        if d["type"] == "debug_peek":
            return f"R {addr:#x} {int(d['length'] or 16)}"
        data = bytes.fromhex(str(need(d, "data"))).hex()
        if d["expect"]:
            return f"SAVE;G {addr:#x} {bytes.fromhex(d['expect']).hex()} {data}"
        return f"SAVE;W {addr:#x} {data}"
    if d["type"] in FIELD_SCRIPT_EVENTS:   # guiones propios: el juego los ejecuta con el personaje libre en el mapa
        if game["mode"] == "battle":
            raise ValueError("no se puede durante un combate")
        require_compat("script")
        if d["type"] == "start_wild_battle":
            return "SAVE;S " + field_script.wild_battle(int(need(d, "species")), int(d["level"] or 5), int(d.get("form") or 0),
                                                        True if d["shiny"] else None, d["hidden_ability"], d["gender"],
                                                        d.get("no_flee"))
        if d["type"] == "start_trainer_battle":
            t1, t2 = int(need(d, "trainer")), int(d.get("trainer2") or 0)
            script = field_script.trainer_battle(t1, t2)
            able = sum(1 for m in game["party"] if not m.get("egg") and m.get("hp", 0) > 0)
            if able < field_script.party_needed(t1, t2):
                raise ValueError(f"para este combate hacen falta {field_script.party_needed(t1, t2)} Pokémon que puedan "
                                 f"luchar y tienes {able}")
            return "SAVE;S " + script
        if d["type"] == "give_egg":
            if len(party_raw) >= 6:
                raise ValueError("el equipo está lleno: el juego solo da huevos al equipo")
            cmds = "SAVE;S " + field_script.give_egg(int(need(d, "species")), int(d.get("form") or 0))
            if d.get("hatch_cycles") is not None:
                if not 0 <= int(d["hatch_cycles"]) <= 255:
                    raise ValueError("hatch_cycles debe ir de 0 a 255")
                # en cuanto aparezca en el equipo se le ponen los ciclos (set_egg_cycles); su hueco puede cambiar si
                # antes llega otro regalo, así que se busca un huevo de esa especie que no estuviera ya
                sp = int(d["species"])
                pending_eggs.append({"species": sp, "cycles": int(d["hatch_cycles"]),
                                     "known": {i for i, m in enumerate(game["party"]) if m.get("egg") and m["species"] == sp}})
            return cmds
        if d["type"] == "teleport":
            return "SAVE;S " + field_script.teleport(str(need(d, "zone")), d.get("x"), d.get("z"))
        global persistent_weather
        w = str(need(d, "weather"))
        cmds = "SAVE;S " + field_script.field_weather(int(w) if w.isdigit() else w)
        if d.get("persist") or w == "zone":
            persistent_weather = None if w == "zone" else w
        return cmds
    if d["type"] in BATTLE_EVENTS:   # fase 5 (experimental): escribe en las dos copias del combatiente
        if game["mode"] != "battle":
            raise ValueError("no hay combate en curso")
        if d["type"] == "battle_set_weather":
            require_compat("weather")
            return "SAVE;" + battle.set_weather_command(str(need(d, "weather")), d.get("turns"))
        show = d.get("show", True) and game["compat"].get("inject") is not False   # sin pantalla si el código no es el esperado
        side = d["target"].get("side", "enemy")
        if side not in ("player", "enemy"):
            raise ValueError("side debe ser 'player' o 'enemy'")
        slot = int(d["target"].get("slot", 0))
        if d["type"] == "battle_set_hp":
            if int(need(d, "hp")) == 0:
                require_compat("faint")
            cmds = "SAVE;" + battle.set_hp_command(side, slot, int(need(d, "hp")))
            return cmds + (";" + battle.show_hp_command(side, slot) if show else "")
        if d["type"] == "battle_set_stage":
            return "SAVE;" + battle.set_stage_command(side, slot, str(need(d, "stat")), d["stage"], d["delta"])
        if d["type"] == "battle_set_item":
            require_compat("item")
            return "SAVE;" + battle.set_item_command(side, slot, int(need(d, "item")))
        if d["type"] == "battle_set_pp":
            return "SAVE;" + battle.set_pp_command(side, slot, int(need(d, "move_slot")), d["pp"])
        cmds = "SAVE;" + battle.set_status_command(side, slot, str(need(d, "status")), d.get("turns"))
        return cmds + (";" + battle.show_status_command(side, slot, d["status"]) if show else "")
    if d["type"] in NEEDS_DATA and not game["data_ok"]:
        raise ValueError("gen5_data.json no es de la ROM que se está jugando: configura ROM_PATH en config_local.py "
                         "o ejecuta  python rom.py <ruta.nds>  y reinicia el puente")
    if d["target"].get("side", "player") != "player":
        raise ValueError("eventos sobre el rival requieren la estructura de batalla (fase 5)")
    if d["type"] in ("give_item", "take_item"):   # también en combate (con "when": "cualquiera" o "en_combate")
        return bag_commands(d)
    if d["when"] == "en_combate" or game["mode"] == "battle":
        raise ValueError("en combate se escribe en la estructura de batalla (fase 5)")
    if d["type"] in ("give_money", "take_money", "set_money"):
        return money_commands(d)
    if d["type"] == "set_season":
        return season_command(str(need(d, "season")))
    if d["type"] == "give_pokemon" and d.get("destination") == "party":   # con la orden del juego (guion propio)
        require_compat("script")
        if d["moves"] or d["nature"] is not None:
            raise ValueError("al equipo no se pueden elegir movimientos ni naturaleza (los decide el juego); usa destination box1")
        return "SAVE;S " + field_script.give_pokemon(int(need(d, "species")), int(d["level"] or 5), int(d.get("form") or 0),
                                                     d["hidden_ability"], d["gender"], int(d["item"] or 0),
                                                     int(d.get("ball") or 4), d["shiny"])
    if d["type"] == "give_pokemon":
        return gift_commands(d)
    if d["type"] in ("move_pokemon", "remove_pokemon"):
        return pc_commands(d)
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
    if t == "set_egg_cycles":
        return pk5.set_egg_cycles(old, int(need(d, "hatch_cycles")))
    if t == "set_move":
        return pk5.set_move(old, int(need(d, "move_slot")), int(need(d, "move")))
    raise ValueError(f"tipo no implementado: {t}")


# Funciones que dependen de código del juego en una dirección fija (el Lua comprueba sus bytes; ver "sigs" en connector.lua)
COMPAT_NAMES = {"faint": "debilitar (vida 0 en combate)", "inject": "actualizar la pantalla del combate",
                "item": "objeto en combate", "weather": "clima del combate", "script": "guiones propios (combates forzados, "
                "clima del mapa, teletransporte, regalos al equipo, huevos)",
                "encounters": "encuentros salvajes de la zona"}


def parse_compat(field: str) -> dict:
    """'faint=1,item=?' -> {"faint": True, "item": None}"""
    out = {}
    for part in field.split(",") if field != "-" else []:
        name, _, v = part.partition("=")
        out[name] = {"1": True, "0": False}.get(v)
    return out


def require_compat(feature: str) -> None:
    if game["compat"].get(feature) is False:
        raise ValueError(f"{COMPAT_NAMES[feature]}: desactivado, el código de este juego no es el esperado "
                         "(¿romhack?); ver 'compat' en /state")


def need(d: dict, key: str):
    if d.get(key) is None:
        raise ValueError(f"falta el campo '{key}' para {d['type']}")
    return d[key]


def battle_ready(d: dict) -> bool:
    if d["type"] == "battle_set_weather":
        return True
    side = d["target"].get("side", "enemy")
    return (side, 0, "real") in battle.RAW and (side, 0, "visual") in battle.RAW


def next_commands() -> str:
    global in_flight
    if in_flight is not None or game["party_addr"] == 0:
        return ""
    for eid in list(queue):
        ev = events[eid]
        when = "en_combate" if ev.data["type"] in BATTLE_EVENTS else ev.data["when"]
        if ev.data["type"] in ("debug_peek", "debug_poke", "debug_inject"):
            when = "cualquiera_incluso_menu"
        if game["mode"] not in WHEN_TO_MODES[when] and ev.data["type"] != "rollback":
            continue
        if ev.data["type"] in BATTLE_EVENTS and not battle_ready(ev.data):
            continue    # el combate acaba de empezar y aún no están los combatientes: esperar, no fallar
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
    species = gamedata.DATA.get("species", {})
    game["party"] = [{**s, "name": species.get(str(s["species"]), {}).get("name", "")}
                     for s in (pk5.summary(pk5.decrypt_ro(bytes(r))) for r in party_raw)]
    for p in list(pending_eggs):
        new = [i for i, m in enumerate(game["party"])
               if m["valid"] and m.get("egg") and m["species"] == p["species"] and i not in p["known"]]
        if new:
            add_event(EventIn(type="set_egg_cycles", target={"slot": new[0]}, hatch_cycles=p["cycles"]), "eclosión rápida")
            pending_eggs.remove(p)
    # slots vacíos o inválidos se marcan con valid=False; la app puede ocultarlos


_last_state_text: Optional[str] = None


async def broadcast(msg: dict) -> None:
    """Deja el mensaje en la cola de cada cliente y vuelve enseguida (nunca espera a un navegador)."""
    global _last_state_text
    text = json.dumps(msg)
    is_state = msg.get("kind") == "state"
    if is_state:
        if text == _last_state_text:   # sin cambios: no se reenvía
            return
        _last_state_text = text
    for c in list(ws_clients):
        c.push(text, is_state)

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
    if info.get("code") == r.code and info.get("header_crc") == r.header_crc and "zones" in gamedata.DATA:
        print(f"Datos del juego: {r.title} {r.code} (al día)")
        return
    print(f"Generando datos del juego desde {r.title} {r.code}...")
    with open(gamedata.PATH, "w", encoding="utf-8") as f:
        json.dump(rom.build_data(r), f, ensure_ascii=False, separators=(",", ":"))
    gamedata.load()


def update_box(hexbox: str, hextrainer: str) -> None:
    global box_raw, box_main, trainer_raw
    main, found = boxes.parse_field(hexbox)
    if main:
        box_main = main
        box_cache.update(found)
        box_raw = box_cache.get(0, box_raw)
        game["box1"] = boxes.summary(box_raw) if box_raw else []
        game["box_current"] = boxes.current(main) + 1
        game["boxes"] = [{"box": n + 1, "name": boxes.name(main, n), "pokemon": boxes.summary(box_cache[n])}
                         for n in range(boxes.count(main)) if n in box_cache]
    t = bytes.fromhex(hextrainer) if hextrainer not in ("", "-") else b""
    if len(t) == config.TRAINER_SIZE:
        trainer_raw = t


def update_misc(hexdata: str) -> None:
    global misc_raw
    raw = bytes.fromhex(hexdata) if hexdata not in ("", "-") else b""
    if len(raw) == config.MISC_SIZE:
        misc_raw = raw
        game["money"] = struct.unpack_from("<I", raw, 0)[0]
        game["badges"] = bin(raw[4]).count("1")


def update_location(field: str) -> None:
    global enc_raw, enc_addr
    loc, addr, raw = encounters.parse_location(field)
    if loc is None:
        return
    game["location"] = loc
    if raw != enc_raw:
        game["encounters"] = encounters.parse(raw) if raw else None
    enc_raw, enc_addr = raw, addr


def record_happenings(mode: str) -> list:
    """Compara con la lectura anterior y guarda los avisos nuevos (GET /happenings, y por el WebSocket)."""
    global last_snap
    badges = misc_raw[4] if len(misc_raw) == config.MISC_SIZE else None
    snap = happenings.snapshot(mode, game["location"], badges, party_raw, box_cache)
    if snap["mons"] is None and last_snap is not None:   # en combate o a medio escribir: se conserva la última buena
        snap["mons"] = last_snap["mons"]
    elif last_snap is not None and last_snap["mons"] is not None:
        # un Pokémon que pasa a una caja que aún no se ha releído falta un momento: se espera una vuelta de cajas
        wait = (boxes.count(box_main) if box_main else 1) + 2
        for pid, m in last_snap["mons"].items():
            if pid in snap["mons"]:
                missing_polls.pop(pid, None)
            elif missing_polls.get(pid, 0) < wait:
                missing_polls[pid] = missing_polls.get(pid, 0) + 1
                snap["mons"][pid] = m
            else:
                missing_polls.pop(pid, None)
    found = happenings.diff(last_snap, snap)
    last_snap = snap
    out = []
    for kind, data in found:
        for key in ("zone", "from"):     # nombres de lugar para leerlo sin buscar
            if kind == "zone":
                data[key + "_name"] = encounters.place_name(data[key])
        if "met_location" in data:
            places = gamedata.DATA.get("places", [])
            data["met_place"] = places[data["met_location"]] if data["met_location"] < len(places) else ""
        h = {"id": next(_happening_ids), "time": time.time(), "type": kind, **data}
        happening_log.append(h)
        out.append(h)
    return out


def pc_commands(d: dict) -> str:
    """Mover un Pokémon entre el equipo y las cajas, o quitarlo (liberar). Todo con guardas: si algo cambió, no se escribe."""
    t = d["target"]
    if "slot" not in t:
        raise ValueError("falta target.slot (y target.box si está en una caja)")
    slot = int(t["slot"])
    ptr = game["party_addr"] - config.PARTY_PTR_OFF
    count = boxes.count(box_main) if box_main else 1

    def box_index(n) -> int:
        n = int(n) - 1
        if not 0 <= n < count:
            raise ValueError(f"caja {n + 1} no válida (hay {count})")
        if n not in box_cache:
            raise ValueError(f"la caja {n + 1} aún no se ha leído; reintenta en un momento")
        return n

    def box_slot_addr(n, s):
        return ptr + config.BOX_PTR_OFF + n * boxes.STRIDE + s * pc.BOX_SLOT

    party_addr = ptr + config.PARTY_COUNT_PTR_OFF
    old_party = struct.pack("<I", len(party_raw)) + b"".join(party_raw)
    cmds = ["SAVE"]
    if "box" in t:                                   # origen: una caja
        src_box = box_index(t["box"])
        if not 0 <= slot < boxes.SLOTS:
            raise ValueError("target.slot de una caja va de 0 a 29")
        raw = box_cache[src_box][slot * pc.BOX_SLOT:(slot + 1) * pc.BOX_SLOT]
        if pc.is_empty(raw):
            raise ValueError(f"no hay Pokémon en la caja {src_box + 1}, hueco {slot}")
        if not pk5.is_valid(pk5.decrypt(raw)):
            raise ValueError("datos del Pokémon no válidos ahora mismo (checksum); reintenta")
        clear_src = f"G {box_slot_addr(src_box, slot):#x} {raw.hex()} {pc.EMPTY_BOX.hex()}"
        new_party = None
    else:                                            # origen: el equipo
        src_box = None
        if not 0 <= slot < len(party_raw):
            raise ValueError(f"no hay Pokémon en el slot {slot} del equipo")
        raw = party_raw[slot]
        if not pk5.is_valid(pk5.decrypt(raw)):
            raise ValueError(f"datos del slot {slot} no válidos ahora mismo (checksum); reintenta en el mapa")
        rest = party_raw[:slot] + party_raw[slot + 1:]
        if not any(pc.able(r) for r in rest):
            raise ValueError("el equipo debe quedarse con al menos un Pokémon que pueda luchar")
        new_party = struct.pack("<I", len(rest)) + b"".join(rest) + pc.EMPTY_PARTY
        clear_src = f"G {party_addr:#x} {old_party.hex()} {new_party.hex()}"
    if d["type"] == "remove_pokemon":
        return ";".join(cmds + [clear_src])
    dest = str(d.get("destination") or "")
    if dest == "party":
        if src_box is None:
            raise ValueError("ya está en el equipo")
        if len(party_raw) >= pc.PARTY_MAX:
            raise ValueError("el equipo está lleno (6)")
        mon = pc.to_party(raw, d.get("hp"))
        grown = struct.pack("<I", len(party_raw) + 1) + b"".join(party_raw)
        return ";".join(cmds + [clear_src, f"G {party_addr:#x} {old_party.hex()} {grown.hex()}",
                                f"W {game['party_addr'] + len(party_raw) * pc.PARTY_SLOT:#x} {mon.hex()}"])
    if not dest.startswith("box") or not dest[3:].isdigit():
        raise ValueError('destination debe ser "party" o "box1"-"box24"')
    dst_box = box_index(dest[3:])
    box = bytearray(box_cache[dst_box])
    if src_box == dst_box:                           # dentro de la misma caja, el hueco de origen queda libre
        box[slot * pc.BOX_SLOT:(slot + 1) * pc.BOX_SLOT] = pc.EMPTY_BOX
    to = d.get("to_slot")
    to = pc.first_free(bytes(box)) if to is None else int(to)
    if to is None:
        raise ValueError(f"la caja {dst_box + 1} está llena")
    if src_box == dst_box and to == slot:
        raise ValueError("ya está en ese hueco")
    if not 0 <= to < boxes.SLOTS or not pc.is_empty(bytes(box[to * pc.BOX_SLOT:(to + 1) * pc.BOX_SLOT])):
        raise ValueError(f"el hueco {to} de la caja {dst_box + 1} no está libre")
    put = f"G {box_slot_addr(dst_box, to):#x} {pc.EMPTY_BOX.hex()} {raw[:pc.BOX_SLOT].hex()}"
    return ";".join(cmds + [clear_src, put])


def money_commands(d: dict) -> str:
    if len(misc_raw) != config.MISC_SIZE:
        raise ValueError("todavía no se ha leído el dinero")
    qty = int(need(d, "qty"))
    if qty < 0:
        raise ValueError("qty no puede ser negativo")
    now = struct.unpack_from("<I", misc_raw, 0)[0]
    new = {"give_money": now + qty, "take_money": now - qty, "set_money": qty}[d["type"]]
    new = max(0, min(new, config.MAX_MONEY))   # el juego no pasa de 9.999.999 ni baja de 0
    addr = game["party_addr"] - config.PARTY_PTR_OFF + config.MISC_PTR_OFF
    return f"SAVE;G {addr:#x} {misc_raw[:4].hex()} {struct.pack('<I', new).hex()}"


SEASONS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3, "primavera": 0, "verano": 1, "otoño": 2, "invierno": 3}


def season_command(season: str) -> str:
    """Estación del mapa. Al cambiar de mapa el juego compara su estación (GameData + 0x1C8) con la del reloj (el mes)
    y, si no coinciden, pone la del reloj; salvo que esté activa la sincronización forzada (GameData + 0x1D2, la que
    se usa al jugar conectado con otro jugador), así que la activamos. "real" la desactiva y vuelve la del reloj.
    El cambio se ve al cambiar de mapa (p. ej. salir de un edificio). La marca no se guarda: al cargar la partida
    vuelve la estación del reloj."""
    addr = game["party_addr"] - config.PARTY_PTR_OFF + config.SEASON_PTR_OFF
    force = addr + config.SEASON_FORCE_OFF
    if season.lower() in ("real", "reloj", "auto"):
        return f"SAVE;W {force:#x} 00"
    value = int(season) if season.isdigit() else SEASONS.get(season.lower())
    if value is None or not 0 <= value <= 3:
        raise ValueError(f"estación desconocida: {season} (válidas: spring, summer, autumn, winter, 0-3 o real)")
    return f"SAVE;W {force:#x} 01;W {addr:#x} {value:02x}"


def update_bag(hexdata: str) -> None:
    global bag_raw
    raw = bytes.fromhex(hexdata) if hexdata not in ("", "-") else b""
    if len(raw) == bag.SIZE:
        bag_raw = raw
        game["bag"] = bag.summary(raw)


async def handle_lua(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global in_flight, last_snap
    game["connected"] = True
    print("Lua conectado")
    try:
        while msg := await read_message(reader):
            kind, _, rest = msg.partition(" ")
            if kind == "POLL":
                mode, _, rest = rest.partition(" ")
                addr, _, rest = rest.partition(" ")
                hexparty, hexbag, hexbox, hextrainer, gamefield, battlefield, hexmisc, compatfield, locfield = (rest.split(" ") + ["-"] * 9)[:9]
                update_game(gamefield)
                game["compat"] = parse_compat(compatfield)
                if mode != "battle":
                    battle.RAW.clear()   # sin datos viejos: el siguiente combate espera a tener los suyos
                try:
                    game["battle"] = battle.parse(battlefield) if mode == "battle" else None
                except (ValueError, IndexError, struct.error) as e:   # datos raros: se informan, no tumban el puente
                    game["battle"] = {"error": str(e)}
                if game["mode"] == "battle" and mode != "battle" and persistent_weather:   # el mapa vuelve con su clima
                    add_event(EventIn(type="set_weather", weather=persistent_weather), "clima persistente")
                game["mode"], game["updated"] = mode, time.time()
                game["party_addr"] = int(addr, 16) if addr else 0   # el puntero puede moverse
                update_bag(hexbag)     # también en combate: la mochila del combate es la misma
                if mode != "battle":   # en combate el bloque del equipo puede no estar al día
                    update_party("" if hexparty == "-" else hexparty)
                    update_box(hexbox, hextrainer)
                    update_misc(hexmisc)
                    update_location(locfield)
                for h in record_happenings(mode):
                    await broadcast({"kind": "happening", "happening": h})
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
        box_cache.clear()
        missing_polls.clear()
        last_snap = None   # al reconectar se empieza de cero (sin avisos de todo lo que ya había)
        game["connected"] = False
        in_flight = None
        print("Lua desconectado")

# ---------------------------------------------------------------- API

app = FastAPI(title="White 2 en tiempo real")
OVERLAY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay")
if os.path.isdir(OVERLAY_DIR):   # páginas para OBS (fuente de navegador); leen el estado por el WebSocket con ?token=
    app.mount("/overlay", StaticFiles(directory=OVERLAY_DIR, html=True), name="overlay")


def auth(token: Optional[str]) -> str:
    if token not in config.API_TOKENS:
        raise HTTPException(401, "token inválido")
    return config.API_TOKENS[token]


@app.get("/happenings")
async def list_happenings(since: int = 0, x_token: Optional[str] = Header(None)):
    """Avisos con id > since (los últimos 500)."""
    auth(x_token)
    return [h for h in happening_log if h["id"] > since]


@app.post("/events")
async def post_event(ev: EventIn, x_token: Optional[str] = Header(None)):
    e = add_event(ev, auth(x_token))
    return {"id": e.id, "state": e.state}


def add_event(ev: EventIn, source: str) -> Event:
    e = Event(id=next(_ids), data=ev.model_dump(), source=source)
    events[e.id] = e
    queue.append(e.id)
    return e


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


# ---------------------------------------------------------------- ruleta

ROULETTE_MAX_QUEUE = 50
roulette_queue: Optional[asyncio.Queue] = None      # se crea en main() (necesita el bucle de asyncio)
roulette_current: Optional[dict] = None
roulette_log: collections.deque = collections.deque(maxlen=50)
_spin_ids = itertools.count(1)


async def roulette_worker() -> None:
    """Gira las tiradas de una en una: avisa al overlay (gira la rueda), espera a que pare y aplica el premio."""
    global roulette_current
    while True:
        source = await roulette_queue.get()
        segs, idx = roulette.pick(roulette.load())
        spin = {"id": next(_spin_ids), "source": source, "seconds": roulette.SPIN_SECONDS, "result": idx,
                "segments": [{"label": p["label"], "weight": p["weight"]} for p in segs], "label": segs[idx]["label"]}
        roulette_current = spin
        await broadcast({"kind": "roulette", "phase": "spin", "spin": spin})
        await asyncio.sleep(roulette.SPIN_SECONDS)
        try:
            text, evs = effects.apply(segs[idx]["effect"], game)
            spin["events"] = [add_event(EventIn(**e), f"ruleta ({source})").id for e in evs]
        except Exception as e:   # un premio que no se puede aplicar no para la ruleta
            text, spin["events"] = f"No se pudo aplicar: {e}", []
        spin["text"], spin["time"] = text, time.time()
        roulette_log.append(spin)
        await broadcast({"kind": "roulette", "phase": "done", "spin": spin})
        await asyncio.sleep(4)   # tiempo para leer el resultado antes de la siguiente tirada
        roulette_current = None


@app.get("/roulette")
async def get_roulette(x_token: Optional[str] = Header(None)):
    auth(x_token)
    return {"effects": effects.catalog(), "prizes": roulette.load(), "spin_seconds": roulette.SPIN_SECONDS,
            "spinning": roulette_current, "queued": roulette_queue.qsize() if roulette_queue else 0,
            "last": list(roulette_log)[-10:]}


@app.put("/roulette")
async def put_roulette(body: dict = Body(...), x_token: Optional[str] = Header(None)):
    auth(x_token)
    try:
        if body.get("reset"):   # volver a los premios de fábrica
            return {"prizes": roulette.save(effects.default_prizes())}
        return {"prizes": roulette.save(body.get("prizes") or [])}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/roulette/spin")
async def spin_roulette(body: dict = Body(default={}), x_token: Optional[str] = Header(None)):
    who = auth(x_token)
    if roulette_queue is None:
        raise HTTPException(503, "la ruleta aún no está lista")
    if roulette_queue.qsize() >= ROULETTE_MAX_QUEUE:
        raise HTTPException(429, f"ya hay {ROULETTE_MAX_QUEUE} tiradas en cola")
    roulette_queue.put_nowait(str(body.get("source") or who)[:40])
    return {"queued": roulette_queue.qsize(), "spinning": roulette_current is not None}


@app.get("/overlay-token")
async def overlay_token(request: Request):
    """Token para la página del overlay, solo si se abre desde esta misma computadora (así nadie lo copia a mano)."""
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "solo desde esta computadora")
    return {"token": next(iter(config.API_TOKENS), "")}


@app.post("/rollback")
async def rollback(x_token: Optional[str] = Header(None)):
    return await post_event(EventIn(type="rollback", when="cualquiera"), x_token)


@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = ""):
    if token not in config.API_TOKENS:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    client = WsClient(websocket)
    client.push(json.dumps({"kind": "state", "state": game}), True)   # para pintar ya, sin esperar a la próxima lectura
    ws_clients.add(client)
    sender = asyncio.create_task(client.run())
    try:
        while not client.dead:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        client.dead = True
        client.wake.set()
        ws_clients.discard(client)
        await asyncio.gather(sender, return_exceptions=True)


async def main() -> None:
    global roulette_queue
    prepare_data()
    roulette_queue = asyncio.Queue()
    worker = asyncio.create_task(roulette_worker())
    lua_server = await asyncio.start_server(handle_lua, config.BRIDGE_HOST, config.LUA_PORT)
    # timeout_graceful_shutdown: al pulsar Ctrl+C no se espera a que el overlay (WebSocket abierto) cierre solo
    api = uvicorn.Server(uvicorn.Config(app, host=config.BRIDGE_HOST, port=config.API_PORT, log_level="info",
                                        timeout_graceful_shutdown=1))
    print(f"Esperando a BizHawk en {config.BRIDGE_HOST}:{config.LUA_PORT}; API en :{config.API_PORT}")
    token = next(iter(config.API_TOKENS), "")
    print(f"Overlay para OBS (ábrelo en el navegador para configurarlo): http://localhost:{config.API_PORT}/overlay/?token={token}")
    async with lua_server:
        lua_task = asyncio.create_task(lua_server.serve_forever())
        await api.serve()          # termina con Ctrl+C
        lua_task.cancel()
        worker.cancel()


if __name__ == "__main__":
    asyncio.run(main())
