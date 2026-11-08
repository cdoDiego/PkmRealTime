"""Pruebas de tools/merge_redux.py (python tests/test_merge_redux.py). Sin ROMs, con datos sintéticos."""
import os, struct, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import merge_redux as mr
import rom


def text(lines):
    """Texto de Gen 5 cifrado, como el del juego (la clave sale del último carácter)."""
    out = []
    for s in lines:
        dec = [ord(c) for c in s] + [0xFFFF]
        key, enc = 0x1234, [0] * len(dec)
        for j in range(len(dec) - 1, -1, -1):
            enc[j] = dec[j] ^ key
            key = ((key >> 3) | (key << 13)) & 0xFFFF
        out.append((struct.pack(f"<{len(enc)}H", *enc), 0))
    return mr.build_text(out)


# texto: ida y vuelta y mezcla línea por línea (Redux donde cambia; la base en el resto y en las que añade)
o = text(["Pound", "Comet Punch", "Mist Ball"])
r = text(["Pound", "Power-Up Punch", "Moonblast"])
b = text(["Pound", "Comet Punch", "Mist Ball", "Flying Press"])
assert rom.decode_text(o) == ["Pound", "Comet Punch", "Mist Ball"]
assert mr.build_text(mr.text_lines(b)) == b and len(b) % 4 == 0
assert rom.decode_text(mr.merge_lines(o, r, b)) == ["Pound", "Power-Up Punch", "Moonblast", "Flying Press"]


# evoluciones: las de Redux en el formato de la base (8 huecos) y las de la base hacia especies nuevas
def evo(*evs, slots):
    evs = list(evs) + [(0, 0, 0)] * (slots - len(evs))
    return b"".join(struct.pack("<HHH", *e) for e in evs)


red = evo(*[(7, 85 + k, 134 + k) for k in range(7)], slots=7)                   # Eevee de Redux: 7 huecos llenos
base = evo((7, 82, 134), (8, 109, 700), slots=8)                               # la base añade Sylveon (700)
m = mr.evolutions(mr.merge_evolution(red, base))
assert len(m) == 8 and m[:7] == [(7, 85 + k, 134 + k) for k in range(7)] and m[7] == (8, 109, 700)


# formas: la forma 685 de la original es la 722 de la base
def personal(form_start, forms):
    e = bytearray(76)
    struct.pack_into("<H", e, 0x1C, form_start); e[0x20] = forms
    return bytes(e)


po = [personal(0, 1)] * 650; pb = [personal(0, 1)] * 650
po[386], pb[386] = personal(685, 4), personal(722, 4)
assert mr.form_map(po, pb) == {685: 722, 686: 723, 687: 724}

# especies: los datos de Redux con los campos de formas de la base (megas)
o_l = [personal(0, 1)] * 709; r_l = list(o_l); b_l = [personal(0, 1)] * 760
r_l[3] = bytes([80, 87]) + o_l[3][2:]
b_l[3] = personal(758, 2)
out = mr.merge_species("a/0/1/6", o_l, r_l, b_l, {}, lambda *_: None)
assert out[3][:2] == bytes([80, 87]) and out[3][mr.FORM_FIELDS] == b_l[3][mr.FORM_FIELDS]

# entradas añadidas: si las dos añaden lo mismo, no se duplica
assert mr.merge_narc("x", [b"a"], [b"a", b"z"], [b"a", b"z"], lambda *_: None) == [b"a", b"z"]
assert mr.merge_narc("x", [b"a"], [b"b", b"z"], [b"a"], lambda *_: None) == [b"b", b"z"]
assert mr.merge_narc("a/0/0/7", [b"a"], [b"r"], [b"u"], lambda *_: None) == [b"u"]   # iconos: los de la base
assert mr.merge_narc("a/0/0/7", [b"p", b"a"], [b"P", b"a"], [b"p", b"u"], lambda *_: None) == [b"p", b"u"]   # y sus paletas
print("ok merge_redux")
