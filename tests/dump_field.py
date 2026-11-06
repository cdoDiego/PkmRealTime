"""Arma, desde un volcado de RAM en combate, el mismo campo "combate" que manda connector.lua (para las pruebas)."""
import struct

BASE = 0x02000000
ADAPTERS = 0x021DD8AC        # sAdapters de White 2
BATTLER_SIZE = 0x160         # como connector.lua


def field(ram: bytes, extra: str = "") -> str:
    u32 = lambda a: struct.unpack_from("<I", ram, a - BASE)[0]
    ptr = BASE + (u32(BASE + 0x24) & 0xFFFFFF)
    tbl, srv = ptr + 0x526A8, ptr + 0x52790
    parts = ["T:" + ram[tbl - BASE:tbl - BASE + 0x70].hex()]
    for side, base in (("p", tbl), ("e", tbl + 0x1C), ("a", tbl + 0x38), ("f", tbl + 0x54),
                       ("P", srv), ("E", srv + 0x1C), ("A", srv + 0x38), ("F", srv + 0x54)):
        for i in range(6):
            a = u32(base + 4 * i) & 0xFFFFFF
            if a:
                pk = u32(BASE + a) & 0xFFFFFF
                mon = ram[pk:pk + 220].hex() if pk else "-"
                parts.append(f"{side}{i}:{BASE + a:08x}:{ram[a:a + BATTLER_SIZE].hex()}:{mon}")
    for i in range(4):
        a = u32(ADAPTERS + 4 * i)
        if BASE <= a < BASE + 0x400000:
            rp, rs = u32(a + 4), u32(a + 8)
            ret = ram[rp - BASE:rp - BASE + rs].hex() if BASE <= rp < BASE + 0x400000 and 0 < rs <= 32 else "-"
            parts.append(f"Q{i}:{a:08x}:{ram[a - BASE + 0x0C:a - BASE + 0x14].hex()}:{rp:08x}:{ret}:"
                         f"{ram[a - BASE + 0x14:a - BASE + 0x1C].hex()}")
    return ",".join(parts) + extra
