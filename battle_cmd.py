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
    "FAINT": 0x39, "UPDATE_HP_GAUGE": 0x41, "FAINT_HP_GAUGE": 0x43, "EFFECT": 0x4C, "MOVE_MSG": 0x59,
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
