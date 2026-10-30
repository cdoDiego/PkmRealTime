"""Crea Pokémon nuevos en formato PK5 de caja (136 bytes) para regalarlos.

Los datos de especies, experiencia y movimientos salen de gen5_data.json, generado desde la
ROM con rom.py (así respeta ROM aleatorizadas e idiomas).
El entrenador original (nombre, TID/SID, género, idioma, juego) se copia del bloque de datos
del jugador en RAM (puntero + config.TRAINER_PTR_OFF), así el regalo cuenta como suyo y le obedece.

Exportar un .pk5 para revisarlo en PKHeX:
  python gift.py 1 5 --dump dumps/mapa3.bin --out bulbasaur.pk5
"""
import argparse
import datetime
import json
import random
import struct

import gamedata
import pk5

DATA = gamedata.DATA   # mismo diccionario: se actualiza si el puente regenera los datos
MAX_SPECIES = 649
DISTANT_LAND = 30008   # "Distant Land" / "Tierra lejana": lugar de encuentro de los regalos
POKE_BALL = 4
NATURES = 25
GLYPHS = {"♂": 0x246D, "♀": 0x246E}   # cómo guarda Gen 5 los símbolos de género (PKHeX)


def species_info(species: int) -> dict:
    if not 1 <= species <= MAX_SPECIES:
        raise ValueError(f"especie fuera de rango (1-{MAX_SPECIES}): {species}")
    if "species" not in DATA:
        raise ValueError("faltan los datos del juego (gen5_data.json): genéralos con  python rom.py <ruta.nds>")
    return DATA["species"][str(species)]


def exp_for_level(species: int, level: int) -> int:
    return DATA["exp"][species_info(species)["growth"]][level - 1]


def default_moves(species: int, level: int) -> list[int]:
    """Los últimos 4 movimientos distintos aprendidos por nivel (como un Pokémon salvaje)."""
    moves: list[int] = []
    for lvl, move in species_info(species)["learnset"]:
        if lvl > level:
            break
        if move in moves:
            moves.remove(move)
        moves.append(move)
    return moves[-4:]


def encode_name(name: str, chars: int) -> bytes:
    """UTF-16 con terminador 0xFFFF; el último u16 del campo también va a 0xFFFF, como hace el juego."""
    units = [GLYPHS.get(c, ord(c)) for c in name][:chars - 1]
    out = units + [0xFFFF] + [0] * (chars - len(units) - 1)
    out[-1] = 0xFFFF
    return struct.pack(f"<{chars}H", *out)


def is_shiny(pid: int, tid: int, sid: int) -> bool:
    return (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8


def gender_of(pid: int, ratio: int) -> int:
    """0 macho, 1 hembra, 2 sin género (según el byte bajo del PID, como en Gen 3-5)."""
    if ratio == 255:
        return 2
    if ratio == 254:
        return 1
    if ratio == 0:
        return 0
    return 1 if (pid & 0xFF) < ratio else 0


def make_pid(rng: random.Random, tid: int, sid: int, ratio: int, shiny: bool, gender) -> int:
    for _ in range(100000):
        pid = rng.getrandbits(32)
        if shiny:   # fuerza variocolor: la mitad alta se ajusta a la baja y al ID
            pid = (((pid & 0xFFFF) ^ tid ^ sid ^ (rng.getrandbits(3))) << 16) | (pid & 0xFFFF)
        if is_shiny(pid, tid, sid) != shiny:
            continue
        if gender is not None and gender_of(pid, ratio) != gender:
            continue
        return pid
    raise ValueError("no se encontró un PID con ese género")


def trainer_from_status(raw: bytes) -> dict:
    """Bloque del jugador en RAM (MyStatus de PKHeX): nombre 0x04, TID 0x14, SID 0x16, idioma 0x1E, juego 0x1F, género 0x21."""
    return {"name": raw[0x04:0x14], "tid": struct.unpack_from("<H", raw, 0x14)[0], "sid": struct.unpack_from("<H", raw, 0x16)[0],
            "language": raw[0x1E], "version": raw[0x1F], "gender": raw[0x21] & 1}


def trainer_from_mon(plain: bytes) -> dict:
    """Plan B: copia el entrenador de un Pokémon descifrado (solo si es del jugador)."""
    return {"name": plain[0x68:0x78], "tid": struct.unpack_from("<H", plain, 0x0C)[0], "sid": struct.unpack_from("<H", plain, 0x0E)[0],
            "language": plain[0x17], "version": plain[0x5F], "gender": plain[0x84] >> 7}


def create(species: int, level: int, trainer: dict, *, moves=None, item: int = 0, nature=None,
           shiny: bool = False, gender=None, hidden_ability: bool = False, ivs=None,
           met_location: int = DISTANT_LAND, ball: int = POKE_BALL, today=None, rng=None) -> bytearray:
    """Devuelve el Pokémon DESCIFRADO (136 bytes, con checksum). trainer = dict de trainer_from_status()."""
    info = species_info(species)
    if not 1 <= level <= 100:
        raise ValueError(f"nivel fuera de rango (1-100): {level}")
    if not 0 <= item <= pk5.MAX_ITEM:
        raise ValueError(f"objeto fuera de rango (0-{pk5.MAX_ITEM}): {item}")
    rng = rng or random.Random()
    today = today or datetime.date.today()
    tid, sid = trainer["tid"], trainer["sid"]

    if gender is not None:
        gender = {"male": 0, "female": 1, "macho": 0, "hembra": 1}.get(gender, gender)
        fixed = info["gender"] in (0, 254, 255)          # solo macho, solo hembra o sin género
        if gender not in (0, 1) or fixed and gender != gender_of(0, info["gender"]):
            raise ValueError("esa especie no puede tener ese género")
    pid = make_pid(rng, tid, sid, info["gender"], shiny, gender)

    moves = list(moves) if moves else default_moves(species, level)
    if not moves or len(moves) > 4 or len(set(moves)) != len(moves):
        raise ValueError("hacen falta de 1 a 4 movimientos distintos")
    for m in moves:
        if not 1 <= m < len(DATA["moves"]):
            raise ValueError(f"movimiento fuera de rango: {m}")

    p = bytearray(pk5.BOX_SIZE)
    struct.pack_into("<I", p, 0x00, pid)
    struct.pack_into("<H", p, 0x08, species)
    struct.pack_into("<H", p, 0x0A, item)
    struct.pack_into("<HH", p, 0x0C, tid, sid)
    struct.pack_into("<I", p, 0x10, exp_for_level(species, level))
    p[0x14] = info["friendship"]
    a1, a2, ah = info["abilities"]
    if hidden_ability and ah:
        p[0x15], p[0x42] = ah, 0x01
    else:
        p[0x15] = a2 if (pid >> 16) & 1 and a2 else a1           # Gen 5: el bit 16 del PID elige la habilidad
    p[0x17] = trainer["language"]
    for i, m in enumerate(moves):
        struct.pack_into("<H", p, 0x28 + 2 * i, m)
        p[0x30 + i] = pk5.move_pp.max_pp(m)
    ivs = ivs or [rng.randrange(32) for _ in range(6)]
    iv32 = sum((iv & 31) << (5 * i) for i, iv in enumerate(ivs))   # HP, Atq, Def, Vel, AtE, DfE
    struct.pack_into("<I", p, 0x38, iv32)                       # sin huevo, sin mote
    p[0x40] = gender_of(pid, info["gender"]) << 1               # forma 0, sin encuentro fatídico
    p[0x41] = rng.randrange(NATURES) if nature is None else nature
    p[0x48:0x5E] = encode_name(info["name"], 11)                # nombre de la especie (sin mote)
    p[0x5F] = trainer["version"]                               # juego de origen
    p[0x68:0x78] = trainer["name"]                             # nombre del entrenador (con su relleno)
    p[0x7B:0x7E] = bytes([today.year % 100, today.month, today.day])
    struct.pack_into("<H", p, 0x80, met_location)
    p[0x83] = ball
    p[0x84] = (trainer["gender"] << 7) | level                 # género del entrenador + nivel de encuentro
    struct.pack_into("<H", p, 0x06, pk5.checksum(p))
    return p


def summary(plain: bytes) -> dict:
    s = pk5.summary(plain)
    sp = s["species"]
    pid, tid, sid = struct.unpack_from("<I", plain, 0)[0], *struct.unpack_from("<HH", plain, 0x0C)
    iv32 = struct.unpack_from("<I", plain, 0x38)[0]
    return {
        "species": sp, "name": DATA["species"][str(sp)]["name"] if 1 <= sp <= MAX_SPECIES else "?",
        "level": next(l for l in range(100, 0, -1) if struct.unpack_from("<I", plain, 0x10)[0] >= exp_for_level(sp, l)),
        "moves": [DATA["moves"][m] for m in s["moves"] if m],
        "item": DATA["items"][s["held_item"]] if s["held_item"] else None,
        "ability": DATA["abilities"][plain[0x15]],
        "nature": plain[0x41], "gender": ["macho", "hembra", "sin género"][(plain[0x40] >> 1) & 3],
        "ivs": [(iv32 >> (5 * i)) & 31 for i in range(6)], "shiny": is_shiny(pid, tid, sid), "valid": s["valid"],
    }


def is_empty_slot(raw: bytes) -> bool:
    """Un hueco vacío de la caja es un Pokémon cifrado con PID 0 y especie 0."""
    plain = pk5.decrypt_ro(bytes(raw))
    return struct.unpack_from("<I", plain, 0)[0] == 0 and struct.unpack_from("<H", plain, 0x08)[0] == 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un .pk5 para revisarlo en PKHeX")
    ap.add_argument("species", type=int)
    ap.add_argument("level", type=int)
    ap.add_argument("--dump", required=True, help="volcado de RAM (dump_ram.lua) para copiar el entrenador")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shiny", action="store_true")
    a = ap.parse_args()
    import config
    ram = open(a.dump, "rb").read()
    ptr = struct.unpack_from("<I", ram, config.MAIN_POINTER_OFF)[0] & 0xFFFFFF
    trainer = trainer_from_status(ram[ptr + config.TRAINER_PTR_OFF: ptr + config.TRAINER_PTR_OFF + config.TRAINER_SIZE])
    mon = create(a.species, a.level, trainer, shiny=a.shiny)
    open(a.out, "wb").write(bytes(mon))   # PKHeX lee los .pk5 descifrados
    print(json.dumps(summary(mon), ensure_ascii=False, indent=2))
    print(f"guardado en {a.out}")


if __name__ == "__main__":
    main()
