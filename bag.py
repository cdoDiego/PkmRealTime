"""Mochila de B2/W2 en RAM: sin cifrar, 5 bolsillos de espacios (objeto u16, cantidad u16).

Posiciones y límites de PKHeX (PlayerBag5B2W2.cs); listas de objetos de ItemStorage5*.cs.
En RAM empieza en puntero + config.BAG_PTR_OFF (validado con volcados el 2026-10-26).
"""
import struct

_GENERAL = frozenset((
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
    55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70,
    71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86,
    87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102,
    103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 116, 117, 118, 119, 135, 136,
    137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 213, 214, 215, 216,
    217, 218, 219, 220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232,
    233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248,
    249, 250, 251, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264,
    265, 266, 267, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280,
    281, 282, 283, 284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295, 296,
    297, 298, 299, 300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312,
    313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 323, 324, 325, 326, 327, 492,
    493, 494, 495, 496, 497, 498, 499, 500, 537, 538, 539, 540, 541, 542, 543, 544,
    545, 546, 547, 548, 549, 550, 551, 552, 553, 554, 555, 556, 557, 558, 559, 560,
    561, 562, 563, 564, 571, 572, 573, 575, 576, 577, 580, 581, 582, 583, 584, 585,
    586, 587, 588, 589, 590,
))
_MACHINE = frozenset((
    328, 329, 330, 331, 332, 333, 334, 335, 336, 337, 338, 339, 340, 341, 342, 343,
    344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355, 356, 357, 358, 359,
    360, 361, 362, 363, 364, 365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375,
    376, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391,
    392, 393, 394, 395, 396, 397, 398, 399, 400, 401, 402, 403, 404, 405, 406, 407,
    408, 409, 410, 411, 412, 413, 414, 415, 416, 417, 418, 419, 618, 619, 620, 420,
    421, 422, 423, 424, 425,
))
_MEDICINE = frozenset((
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
    33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
    49, 50, 51, 52, 53, 54, 134, 504, 565, 566, 567, 568, 569, 570, 591,
))
_BERRY = frozenset((
    149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164,
    165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180,
    181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196,
    197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212,
))
_KEY = frozenset((
    437, 442, 447, 450, 453, 458, 465, 466, 471, 504, 578, 616, 617, 621, 626, 627,
    628, 629, 630, 631, 632, 633, 634, 635, 636, 637, 638,
))
UNRELEASED = frozenset((
    5, 16, 260, 261, 262, 263, 264, 492, 493, 494, 495, 496, 497, 498, 499, 500,
    576,
))

# nombre, offset dentro de la mochila, nº de espacios, cantidad máxima, objetos permitidos
POCKETS = (
    ("objetos", 0x000, 310, 999, _GENERAL),
    ("clave", 0x4D8, 83, 1, _KEY),
    ("mt", 0x624, 109, 1, _MACHINE),
    ("medicinas", 0x7D8, 48, 999, _MEDICINE),
    ("bayas", 0x898, 64, 999, _BERRY),
)
SIZE = 0x998
# Orden de búsqueda al dar un objeto (504 está en medicinas y en clave: gana medicinas)
_GIVE_ORDER = ("objetos", "medicinas", "bayas", "mt", "clave")


def pocket_for(item: int):
    for name in _GIVE_ORDER:
        p = next(p for p in POCKETS if p[0] == name)
        if item in p[4]:
            return p
    raise ValueError(f"el objeto {item} no existe en B2/W2")


def read_pocket(bag: bytes, pocket) -> list[tuple[int, int]]:
    _, off, slots, _, _ = pocket
    out = []
    for i in range(slots):
        item, qty = struct.unpack_from("<HH", bag, off + 4 * i)
        if item != 0:       # se leen todos por si hubiera huecos; al escribir se compactan
            out.append((item, qty))
    return out


def write_pocket(bag: bytes, pocket, entries: list[tuple[int, int]]) -> bytes:
    """Devuelve una copia de la mochila con el bolsillo reescrito (sin huecos, resto a cero)."""
    _, off, slots, _, _ = pocket
    if len(entries) > slots:
        raise ValueError(f"el bolsillo {pocket[0]} está lleno")
    data = bytearray(bag)
    data[off:off + 4 * slots] = bytes(4 * slots)
    for i, (item, qty) in enumerate(entries):
        struct.pack_into("<HH", data, off + 4 * i, item, qty)
    return bytes(data)


def give(bag: bytes, item: int, qty: int, allow_key: bool = False) -> bytes:
    if qty < 1:
        raise ValueError("la cantidad debe ser al menos 1")
    if item in UNRELEASED:
        raise ValueError(f"el objeto {item} no se distribuyó en B2/W2 (el juego podría no manejarlo)")
    pocket = pocket_for(item)
    if pocket[0] == "clave" and not allow_key:
        raise ValueError("los objetos clave pueden romper la historia; no se dan por evento")
    entries = read_pocket(bag, pocket)
    limit = pocket[3]
    for i, (it, q) in enumerate(entries):
        if it == item:
            if q >= limit:
                raise ValueError(f"ya tienes el máximo ({limit}) del objeto {item}")
            entries[i] = (it, min(limit, q + qty))
            return write_pocket(bag, pocket, entries)
    entries.append((item, min(limit, qty)))
    return write_pocket(bag, pocket, entries)


def take(bag: bytes, item: int, qty: int | None = None) -> bytes:
    """Quita qty unidades (None = todas). Si llega a 0 se borra y los de detrás suben."""
    pocket = pocket_for(item)
    if pocket[0] == "clave":
        raise ValueError("los objetos clave pueden romper la historia; no se quitan por evento")
    entries = read_pocket(bag, pocket)
    for i, (it, q) in enumerate(entries):
        if it == item:
            left = 0 if qty is None else q - qty
            if left > 0:
                entries[i] = (it, left)
            else:
                del entries[i]
            return write_pocket(bag, pocket, entries)
    raise ValueError(f"no tienes el objeto {item}")


def pocket_range(name: str) -> tuple[int, int]:
    """(offset, longitud en bytes) de un bolsillo dentro de la mochila."""
    p = next(p for p in POCKETS if p[0] == name)
    return p[1], 4 * p[2]


def summary(bag: bytes) -> dict:
    return {p[0]: [{"item": it, "qty": q} for it, q in read_pocket(bag, p)] for p in POCKETS}
