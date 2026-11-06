"""Comandos de combate de B2/W2: lo que la lógica (servidor) manda a la pantalla (cliente) para que lo reproduzca.

Números y formatos de la decompilación pokebw2 (include/battle/btl_server_cmd.h, src/ov167/btl_server_cmd.c),
tal como los empaqueta showdown-bw2 (src/bw/servercmd.ts). Cada comando: número en u16 big-endian y sus
argumentos empaquetados según su formato (los nombres dan el ancho en bits; U8/U16/U32 son campos enteros big-endian).
Validado con bloques reales de White 2 (ver tests/test_battle_cmd.py).
"""

SC = {
    "OP_SUBTRACT_HP": 0x01, "OP_ADD_HP": 0x02, "OP_ZERO_HP": 0x03, "OP_SUBTRACT_PP": 0x04,
    "OP_SET_MOVE_USED": 0x06, "OP_ADD_PP": 0x07, "OP_RAISE_STAT_STAGE": 0x09, "OP_LOWER_STAT_STAGE": 0x0A,
    "OP_SET_CONDITION": 0x0F, "OP_CURE_CONDITION": 0x10,
    "MOVE_ANIM": 0x30, "DAMAGE": 0x32, "SET_GAUGE_STATUS": 0x35, "STAT_UP_EFFECT": 0x37, "STAT_DOWN_EFFECT": 0x38,
    "FAINT": 0x39, "WEATHER_START": 0x3F, "WEATHER_END": 0x40, "UPDATE_HP_GAUGE": 0x41, "FAINT_HP_GAUGE": 0x43, "EFFECT": 0x4C, "MOVE_MSG": 0x59,
    "MSG_STD": 0x5A, "MSG_SET": 0x5B, "RESERVE": 0x5F,
}

# Formato de cada comando por número (tabla del juego en 0x021d6e50 de Black 2). Los mensajes (0x5A-0x5D) van aparte.
FORMATS = [
    "NONE", "U8_U16", "U8_U16", "U8", "5_3_U8", "5_3_U8", "5_3", "5_3_U8", "5_3_U8", "5_3_U8", "5_3_U8", "U8X8", "U8",
    "U8", "U8_U32", "U8_U8_U32", "U8", "U8_U16", "5_3_U8_U16", "5_5_14", "U8_U16", "U8_U8_U32", "U8_U16", "U8_U16",
    "5_5_5_5_U16_U16", "U8_U8", "U8_U8", "U8_U8", "U8_U8", "U8_U16", "U8_U16", "5_3_7_1_U16", "U8", "U8_U32", "U8_U8",
    "U8", "U8", "5_5_14", "U8_U8", "U8_U16", "U8", "4_4", "U8", "U8", "U8_U8", "5_5_5_5_U16_U16", "U8", "U8",
    # 0x30: los que muestran algo
    "5_5_14_U8", "5_3", "U8_U8_U16", "U8_U8_U16", "U8", "U8_U8", "U8", "5_5_5", "5_5_5", "U8", "U8", "U8_U8", "U8_U16",
    "5_3_5_3", "U8X7", "U8_U8", "U8", "U8", "U8", "5_3", "5_5_5", "U8_U32", "3_2_1_1_1_U16", "U8_U16", "4_4", "U8_U16",
    "U8_U8_U16_U16", "U8", "U16", "U8_U16", "U8_U8_U16", "U8_U8", "5_3_5_3", "U8", "U8", "U8_U8", "5_3_U16", "U16", "U8",
    "U8", "U8", "U8_U16",
]
MSG_ARG_END = 0xFFFF0000
QUEUE_SIZE = 3000


def _n_args(fmt: str) -> int:
    if fmt == "NONE":
        return 0
    return sum(int(p[3:]) if p.startswith("U8X") else 1 for p in fmt.split("_"))


def encode(cmd, *args) -> bytes:
    """Un comando. cmd = número o nombre de SC."""
    num = SC[cmd] if isinstance(cmd, str) else cmd
    out = bytearray(num.to_bytes(2, "big"))
    if num in (SC["MSG_STD"], SC["MSG_SET"]):          # mensaje u16 + argumentos u32 + fin
        msg, *rest = args
        out += int(msg).to_bytes(2, "big")
        for a in rest:
            out += int(a).to_bytes(4, "big")
        out += MSG_ARG_END.to_bytes(4, "big")
        return bytes(out)
    fmt = FORMATS[num]
    if len(args) != _n_args(fmt):
        raise ValueError(f"el comando {num:#x} ({fmt}) lleva {_n_args(fmt)} argumentos, no {len(args)}")
    a = [int(x) for x in args]
    bits = lambda v, n: v & ((1 << n) - 1)
    if fmt == "NONE":
        pass
    elif fmt == "5_3_7_1_U16":              # dos u16 de campos + u16 (como showdown-bw2)
        out += ((bits(a[0], 5) << 3) | bits(a[1], 3)).to_bytes(2, "big")
        out += ((bits(a[2], 7) << 1) | bits(a[3], 1)).to_bytes(2, "big")
        out += bits(a[4], 16).to_bytes(2, "big")
    elif fmt == "5_5_5_5_5_5":              # dos grupos de 15 bits, cada uno en un u16
        out += ((bits(a[0], 5) << 10) | (bits(a[1], 5) << 5) | bits(a[2], 5)).to_bytes(2, "big")
        out += ((bits(a[3], 5) << 10) | (bits(a[4], 5) << 5) | bits(a[5], 5)).to_bytes(2, "big")
    elif fmt.startswith("U8X"):
        out += bytes(x & 0xFF for x in a)
    else:
        # campos de bits (5_3, 5_5_14, ...) se agrupan hasta llenar bytes; U8/U16/U32 van enteros
        parts, i, acc, acc_bits = fmt.split("_"), 0, 0, 0
        for p in parts:
            if p in ("U8", "U16", "U32"):
                if acc_bits:
                    out += acc.to_bytes((acc_bits + 7) // 8, "big"); acc, acc_bits = 0, 0
                out += (a[i] & ((1 << int(p[1:])) - 1)).to_bytes(int(p[1:]) // 8, "big")
            else:
                n = int(p)
                acc, acc_bits = (acc << n) | bits(a[i], n), acc_bits + n
            i += 1
        if acc_bits:
            out += acc.to_bytes((acc_bits + 7) // 8, "big")   # se rellena por arriba hasta bytes completos
    return bytes(out)


def block(commands: list) -> bytes:
    """Varios comandos seguidos: [["UPDATE_HP_GAUGE", 12], ["SET_GAUGE_STATUS", 12, 1]]."""
    data = b"".join(encode(c[0], *c[1:]) for c in commands)
    if len(data) > QUEUE_SIZE:
        raise ValueError(f"el bloque ocupa {len(data)} bytes; la cola admite {QUEUE_SIZE}")
    return data


# ---------------------------------------------------------------- lectura de bloques (registro de combate)
# Nombres y formatos tal como los lee el juego (BtlServerCmdQueue_Read y sCmdFormats en src/ov167/btl_server_cmd.c de
# pokebw2), en el orden del enum BtlServerCmd. Los anchos van en bits cuando varios comparten bytes.
READ_TABLE = [
    ("NULL", ""), ("OP_SUBTRACT_HP", "U8_U16"), ("OP_ADD_HP", "U8_U16"), ("OP_ZERO_HP", "U8"),
    ("OP_SUBTRACT_PP", "5_3_U8"), ("OP_SUBTRACT_ORIGINAL_PP", "5_3_U8"), ("OP_SET_MOVE_USED", "5_3"),
    ("OP_ADD_PP", "5_3_U8"), ("OP_ADD_ORIGINAL_PP", "5_3_U8"), ("OP_RAISE_STAT_STAGE", "5_3_U8"),
    ("OP_LOWER_STAT_STAGE", "5_3_U8"), ("OP_SET_STAT_STAGES", "U8X8"), ("OP_RECOVER_STAT_STAGES", "U8"),
    ("OP_RESET_STAT_STAGES", "U8"), ("OP_ADD_CRIT_STAGE", "U8_U32"), ("OP_SET_CONDITION", "U8_U8_U32"),
    ("OP_CURE_CONDITION", "U8"), ("OP_CURE_MOVE_CONDITION", "U8_U16"), ("OP_SEND_IN", "5_3_U8_U16"),
    ("OP_SET_BASE_STAT", "5_5_14"), ("OP_SET_WEIGHT", "U8_U16"), ("OP_CONDITION_TURN_CHECK", "U8_U8_U32"),
    ("OP_CHANGE_TYPE", "U8_U16"), ("OP_CONSUME_ITEM", "U8_U16"), ("OP_UPDATE_USED_MOVE", "5_5_5_5_U16_U16"),
    ("OP_SET_CONDITION_FLAG", "U8_U8"), ("OP_CLEAR_CONDITION_FLAG", "U8_U8"), ("OP_SET_TURN_FLAG", "U8_U8"),
    ("OP_CLEAR_TURN_FLAG", "U8_U8"), ("OP_CHANGE_ABILITY", "U8_U16"), ("OP_SET_ITEM", "U8_U16"),
    ("OP_UPDATE_MOVE", "5_3_7_1_U16"), ("OP_CLEAR_FOR_SWITCH", "U8"), ("OP_ADD_FIELD_EFFECT", "U8_U32"),
    ("OP_ADD_FIELD_EFFECT_DEPEND_MON", "U8_U8"), ("OP_REMOVE_FIELD_EFFECT_DEPEND_MON", "U8"),
    ("OP_REMOVE_FIELD_EFFECT", "U8"), ("OP_SET_COUNTER", "5_5_14"), ("OP_BATON_PASS", "U8_U8"),
    ("OP_CREATE_SUBSTITUTE", "U8_U16"), ("OP_DELETE_SUBSTITUTE", "U8"), ("OP_ADD_SHOOTER_ENERGY", "4_4"),
    ("OP_SETUP_ILLUSION", "U8"), ("OP_CLEAR_CONSUMED_ITEM", "U8"), ("OP_CURE_MON_DEPENDENT_CONDITIONS", "U8_U8"),
    ("OP_ADD_DAMAGE_RECORD", "5_5_5_5_U16_U16"), ("OP_TURN_CHECK", "U8"), ("OP_FIELD_TURN_CHECK", "U8"),
    ("MOVE_ANIM", "5_5_14_U8"), ("SET_MON_VISIBLE", "5_3"), ("DAMAGE", "U8_U8_U16"), ("DAMAGE_PLURAL", "U8_U8_U16"),
    ("ONE_HIT_KO", "U8"), ("SET_GAUGE_STATUS", "U8_U8"), ("CONFUSION_DAMAGE", "U8"), ("STAT_UP_EFFECT", "5_5_5"),
    ("STAT_DOWN_EFFECT", "5_5_5"), ("FAINT", "U8"), ("SHOW_MON", "U8"), ("RECALL_MSG", "U8_U8"), ("RECALL", "U8_U16"),
    ("SEND_OUT", "5_3_5_3"), ("ADD_EVS", "U8X7"), ("WEATHER_START", "U8_U8"), ("WEATHER_END", "U8"),
    ("UPDATE_HP_GAUGE", "U8"), ("USE_HELD_ITEM", "U8"), ("FAINT_HP_GAUGE", "5_3"), ("SWAP_POS", "5_5_5"),
    ("EXP_GAIN", "U8_U32"), ("BALL_THROW", "3_2_1_1_1_U16"), ("BALL_THROW_TRAINER", "U8_U16"), ("ROTATION", "4_4"),
    ("CHANGE_ABILITY", "U8_U16"), ("SWAP_ABILITY", "U8_U8_U16_U16"), ("ILLUSION_BREAK", "U8"), ("EFFECT", "U16"),
    ("EFFECT_BY_POS", "U8_U16"), ("EFFECT_BETWEEN_POS", "U8_U8_U16"), ("CHANGE_FORM", "U8_U8"),
    ("MOVE_TO_CENTER", "5_3_5_3"), ("SUBSTITUTE_CREATE", "U8"), ("SUBSTITUTE_DELETE", "U8"), ("TRANSFORM", "U8_U8"),
    ("DAMAGE_EFFECT", "5_3_U16"), ("PLAY_BGM", "U16"), ("HIDE_MSG_WINDOW", "U8"), ("ABILITY_POPUP_IN", "U8"),
    ("ABILITY_POPUP_OUT", "U8"), ("MOVE_MSG", "U8_U16"), ("MSG_STD", "MSG"), ("MSG_SET", "MSG"),
    ("MSG_STD_SE", "MSG_SE"), ("MSG_SET_SE", "MSG"), ("NONE", ""), ("RESERVE", "RESERVE"),
]
SC_NAME = {i: name for i, (name, _) in enumerate(READ_TABLE)}


def _read_args(data: bytes, pos: int, fmt: str) -> tuple[list, int]:
    """Argumentos de un comando, como ReadCmdArgs: los campos de bits se leen de un u8, u16 o u24 big-endian."""
    out = []

    def take(n):
        nonlocal pos
        if pos + n > len(data):
            raise ValueError("bloque cortado")
        v = int.from_bytes(data[pos:pos + n], "big")
        pos += n
        return v

    if fmt.startswith("U8X"):
        return [take(1) for _ in range(int(fmt[3:]))], pos
    special = {"5_3_7_1_U16": None, "5_5_5_5_U16_U16": None}
    if fmt in special:
        if fmt == "5_3_7_1_U16":
            v, v2 = take(2) & 0xFF, take(2) & 0xFF
            return [(v >> 3) & 0x1F, v & 7, (v2 >> 1) & 0x7F, v2 & 1, take(2)], pos
        v = take(3)
        return [(v >> 15) & 0x1F, (v >> 10) & 0x1F, (v >> 5) & 0x1F, v & 0x1F, take(2), take(2)], pos
    parts = fmt.split("_") if fmt else []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in ("U8", "U16", "U32"):
            out.append(take(int(p[1:]) // 8))
            i += 1
            continue
        group = []                                  # campos de bits seguidos: 8, 16 o 24 bits en total
        while i < len(parts) and parts[i] not in ("U8", "U16", "U32"):
            group.append(int(parts[i]))
            i += 1
        total = sum(group)
        width = 1 if total <= 8 else 2 if total <= 16 else 3
        v, shift = take(width), width * 8
        if total != shift:                          # 5_5_14 (24), 5_5_5 (15 en u16), 3_2_1_1_1 (8)...
            shift = total
        for n in group:
            shift -= n
            out.append((v >> shift) & ((1 << n) - 1))
    return out, pos


def decode(data: bytes) -> list[tuple[str, list]]:
    """Bloque de comandos del servidor → [(nombre, argumentos)], como BtlServerCmdQueue_Read (salta RESERVE)."""
    out, pos = [], 0
    while pos + 2 <= len(data):
        num = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        if num >= len(READ_TABLE):
            raise ValueError(f"comando desconocido {num:#x} en la posición {pos - 2}")
        name, fmt = READ_TABLE[num]
        if fmt == "RESERVE":                        # hueco reservado que nadie llenó: u8 tamaño y se salta
            pos += 1 + data[pos]
            continue
        if fmt in ("MSG", "MSG_SE"):
            args = [int.from_bytes(data[pos:pos + 2], "big")]
            pos += 2
            if name == "MSG_STD_SE":
                args.append(int.from_bytes(data[pos:pos + 2], "big"))
                pos += 2
            for _ in range(15):
                if pos + 4 > len(data):
                    raise ValueError("mensaje cortado")
                a = int.from_bytes(data[pos:pos + 4], "big")
                pos += 4
                if a == MSG_ARG_END:
                    break
                args.append(a)
            out.append((name, args))
            continue
        args, pos = _read_args(data, pos, fmt)
        if name == "DAMAGE_PLURAL":                 # detrás van los pokeID de los golpeados, un byte cada uno
            args += list(data[pos:pos + args[0]])   # (ServerDisplay_Damage en btl_server_flow.c, BtlServerCmdQueue_PutByte)
            pos += args[0]
        out.append((name, args))
    return out


for _i, (_n, _) in enumerate(READ_TABLE):   # encode() acepta también los nombres de la tabla completa
    assert SC.setdefault(_n, _i) == _i, _n
