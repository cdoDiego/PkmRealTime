"""Prueba del Regalo Misterioso en vivo (EXPERIMENTAL): lee y escribe el álbum de Tarjetas Misteriosas
a través del puente, con debug_peek / debug_poke (necesita DEBUG_WRITES = True en config_local.py).

Con el puente y BizHawk en marcha y la partida cargada:
  python tools/wonder_card.py list
      tarjetas del álbum y IDs marcados como recibidos
  python tools/wonder_card.py give --pgf "0128 Keldeo.pgf"
      mete una tarjeta oficial (.pgf o .wc5full) en el primer hueco libre (o en el de una ya recogida)
  python tools/wonder_card.py give --species 25 --level 10 --shiny --title "Pikachu de prueba"
      tarjeta hecha a medida (movimientos de su nivel, sacados de gen5_data.json)
  python tools/wonder_card.py give --item 50 --title "Caramelo raro"
  python tools/wonder_card.py clear --slot 0
      vacía un hueco del álbum (no toca las banderas de recibido)
  python tools/wonder_card.py dump --out album.bin
      guarda el bloque entero (cifrado) para compararlo luego

Lo mismo desde el puente: evento give_wonder_card. Cada escritura crea antes un savestate de seguridad: POST /rollback lo deshace.
"""
import argparse
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # módulos de la raíz
import config
import wondercard as wc

API = f"http://127.0.0.1:{config.API_PORT}"
TOKEN = next(iter(config.API_TOKENS))
PEEK_MAX = 0x400


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method, headers={"X-Token": TOKEN, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"el puente respondió {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"no se pudo hablar con el puente en {API} ({e.reason}): ¿está en marcha?")


def _run(event: dict, timeout: float = 15) -> str:
    eid = _call("POST", "/events", event)["id"]
    end = time.time() + timeout
    while time.time() < end:
        ev = _call("GET", f"/events/{eid}")
        if ev["state"] == "aplicado":
            return ev["detail"]
        if ev["state"] in ("fallo", "cancelado"):
            sys.exit(f"evento {eid} ({event['type']}): {ev['state']}: {ev['detail']}")
        time.sleep(0.1)
    _call("DELETE", f"/events/{eid}")
    sys.exit(f"evento {eid} sin respuesta en {timeout} s: ¿está BizHawk conectado al puente?")


def peek(addr: int, length: int) -> bytes:
    out = b""
    while len(out) < length:
        n = min(PEEK_MAX, length - len(out))
        detail = _run({"type": "debug_peek", "addr": hex(addr + len(out)), "length": n})
        hexpart = detail[detail.index("R:") + 2:].split(",")[0].strip()
        out += bytes.fromhex(hexpart)
    return out


def poke(addr: int, old: bytes, new: bytes) -> None:
    if old != new:
        _run({"type": "debug_poke", "addr": hex(addr), "expect": old.hex(), "data": new.hex()})


def album_addr() -> int:
    ptr = struct.unpack("<I", peek(config.MAIN_RAM_BASE + config.MAIN_POINTER_OFF, 4))[0] & 0xFFFFFF
    return config.MAIN_RAM_BASE + ptr + wc.MYSTERY_PTR_OFF


def read_block() -> tuple[int, bytes]:
    addr = album_addr()
    return addr, peek(addr, wc.BLOCK_SIZE)


def cmd_list(_a) -> None:
    addr, block = read_block()
    plain = wc.decrypt_block(block)
    print(f"álbum en {addr:#010x}, semilla {wc.seed_of(block):#010x}")
    for slot in range(wc.CARDS):
        o = wc.card_offset(slot)
        card = plain[o:o + wc.CARD_SIZE]
        print(f"  hueco {slot:2}: " + ("vacío" if not any(card) else json.dumps(wc.summary(card), ensure_ascii=False)))
    print("  recibidos:", wc.received_ids(plain) or "ninguno")


def cmd_give(a) -> None:
    custom = not a.pgf
    if a.pgf:
        card = wc.load_pgf(a.pgf)
    elif a.species:
        import gift   # necesita gen5_data.json
        moves = a.moves or gift.default_moves(a.species, a.level)
        card = wc.pokemon_card(a.species, a.level, moves, card_id=0, title=a.title or "Regalo misterioso",
                               ot=a.ot, shiny=a.shiny, item=a.held)
    elif a.item:
        card = wc.item_card(a.item, card_id=0, title=a.title or "Regalo misterioso")
    else:
        sys.exit("indica --pgf, --species o --item")
    addr, block = read_block()
    if custom:
        card = wc.set_card_id(card, a.card_id if a.card_id is not None else wc.free_card_id(wc.decrypt_block(block)))
    print("tarjeta:", json.dumps(wc.summary(card), ensure_ascii=False))
    try:
        slot, writes = wc.add_card_writes(block, card, set_flag=not a.no_flag)
    except ValueError as e:
        sys.exit(str(e))
    if a.dry_run:
        print(f"(simulación) se escribiría en el hueco {slot}, {addr + wc.card_offset(slot):#010x}")
        return
    for o, old, new in writes:
        poke(addr + o, old, new)
    print(f"escrita en el hueco {slot}. Ahora: sal y vuelve a entrar a un Centro Pokémon y habla con el repartidor.")


def cmd_clear(a) -> None:
    addr, block = read_block()
    o = wc.card_offset(a.slot)
    old, new = wc.patch(block, o, bytes(wc.CARD_SIZE))
    poke(addr + o, old, new)
    print(f"hueco {a.slot} vaciado")


def cmd_dump(a) -> None:
    addr, block = read_block()
    with open(a.out, "wb") as f:
        f.write(block)
    print(f"{len(block)} bytes de {addr:#010x} → {a.out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    g = sub.add_parser("give")
    g.add_argument("--pgf", help="tarjeta .pgf o .wc5full")
    g.add_argument("--species", type=int)
    g.add_argument("--level", type=int, default=10)
    g.add_argument("--moves", type=int, nargs="+")
    g.add_argument("--shiny", action="store_true")
    g.add_argument("--held", type=int, default=0, help="objeto que lleva el Pokémon")
    g.add_argument("--item", type=int, help="tarjeta de objeto (n.º de objeto)")
    g.add_argument("--title", help="título de la tarjeta (máx. 36 letras)")
    g.add_argument("--ot", default="Regalo", help="entrenador original (máx. 7 letras)")
    g.add_argument("--card-id", type=int, help="ID de la tarjeta (0-2047; por defecto uno libre de 1500-2045)")
    g.add_argument("--no-flag", action="store_true", help="no marcar el ID como recibido")
    g.add_argument("--dry-run", action="store_true", help="solo mostrar lo que haría")
    g.set_defaults(fn=cmd_give)
    c = sub.add_parser("clear")
    c.add_argument("--slot", type=int, required=True)
    c.set_defaults(fn=cmd_clear)
    d = sub.add_parser("dump")
    d.add_argument("--out", required=True)
    d.set_defaults(fn=cmd_dump)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
