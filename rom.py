"""Lee datos directamente de la ROM (.nds) de Pokémon B2/W2, aleatorizada o no.

Así cada persona usa los datos de SU juego (habilidades, movimientos por nivel, curvas de
experiencia, PP, nombres en su idioma) en vez de los del juego original.

  python rom.py "ruta/al/juego.nds"            genera gen5_data.json desde la ROM
  python rom.py "ruta/al/juego.nds" --info     solo muestra qué juego es

Formatos: cabecera NDS + FNT/FAT (GBATEK), contenedores NARC, texto cifrado de Gen 5.
"""
import argparse
import json
import os
import struct

# Rutas dentro de la ROM de B2/W2 (iguales en todas las regiones)
PERSONAL = "a/0/1/6"     # datos de cada especie (0x4C bytes)
LEARNSET = "a/0/1/8"     # movimientos por nivel
MOVES = "a/0/2/1"        # datos de cada movimiento
TEXT = "a/0/0/2"         # textos del juego
TRDATA = "a/0/9/1"       # entrenadores: tipo de datos, clase, tipo de combate, nº de Pokémon...
TEXT_SPECIES = 90        # archivo de texto con los nombres de especie (B2/W2)
TEXT_ABILITIES = 374
TEXT_MOVES = 403
TEXT_ITEMS = 64
TEXT_TRAINER_CLASSES = 383

# Curvas de experiencia: fórmulas oficiales (iguales en todas las ROM; el randomizer solo cambia qué curva usa cada especie)
def _exp_curve(growth: int, n: int) -> int:
    if n <= 1:
        return 0
    if growth == 0:                                  # medium fast
        return n ** 3
    if growth == 1:                                  # erratic
        if n <= 50: return n ** 3 * (100 - n) // 50
        if n <= 68: return n ** 3 * (150 - n) // 100
        if n <= 98: return n ** 3 * ((1911 - 10 * n) // 3) // 500
        return n ** 3 * (160 - n) // 100
    if growth == 2:                                  # fluctuating
        if n <= 15: return n ** 3 * ((n + 1) // 3 + 24) // 50
        if n <= 36: return n ** 3 * (n + 14) // 50
        return n ** 3 * (n // 2 + 32) // 50
    if growth == 3:                                  # medium slow
        return 6 * n ** 3 // 5 - 15 * n ** 2 + 100 * n - 140
    if growth == 4:                                  # fast
        return 4 * n ** 3 // 5
    if growth == 5:                                  # slow
        return 5 * n ** 3 // 4
    raise ValueError(growth)


EXP_TABLES = [[_exp_curve(g, n) for n in range(1, 101)] for g in range(6)]


class Rom:
    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        self.title = d[0x00:0x0C].rstrip(b"\0").decode("ascii", "replace")
        self.code = d[0x0C:0x10].decode("ascii", "replace")
        self.version = d[0x1E]
        self.header_crc = struct.unpack_from("<H", d, 0x15E)[0]
        self._fnt, _ = struct.unpack_from("<II", d, 0x40)
        self._fat, _ = struct.unpack_from("<II", d, 0x48)
        self._paths = self._read_fnt()

    # --- sistema de archivos NitroFS
    def _read_fnt(self) -> dict[str, int]:
        d, fnt = self.data, self._fnt
        paths: dict[str, int] = {}

        def walk(dir_id: int, prefix: str) -> None:
            off, first_file, _ = struct.unpack_from("<IHH", d, fnt + 8 * (dir_id & 0xFFF))
            pos, file_id = fnt + off, first_file
            while True:
                b = d[pos]; pos += 1
                if b == 0:
                    return
                name = d[pos:pos + (b & 0x7F)].decode("ascii", "replace"); pos += b & 0x7F
                if b & 0x80:                                  # subdirectorio
                    sub = struct.unpack_from("<H", d, pos)[0]; pos += 2
                    walk(sub, prefix + name + "/")
                else:
                    paths[prefix + name] = file_id
                    file_id += 1

        walk(0xF000, "")
        return paths

    def file(self, path: str) -> bytes:
        fid = self._paths[path]
        start, end = struct.unpack_from("<II", self.data, self._fat + 8 * fid)
        return self.data[start:end]

    def narc(self, path: str) -> list[bytes]:
        """Archivos dentro de un contenedor NARC."""
        d = self.file(path)
        if d[:4] != b"NARC":
            raise ValueError(f"{path} no es un NARC")
        pos = struct.unpack_from("<H", d, 0x0C)[0]           # tamaño de la cabecera
        assert d[pos:pos + 4] == b"BTAF"
        btaf_size, count = struct.unpack_from("<IH", d, pos + 4)
        entries = [struct.unpack_from("<II", d, pos + 12 + 8 * i) for i in range(count)]
        pos += btaf_size
        assert d[pos:pos + 4] == b"BTNF"
        pos += struct.unpack_from("<I", d, pos + 4)[0]
        assert d[pos:pos + 4] == b"GMIF"
        base = pos + 8
        return [d[base + s:base + e] for s, e in entries]

    # --- datos del juego
    def personal(self) -> list[bytes]:
        return self.narc(PERSONAL)

    def learnsets(self) -> list[list[list[int]]]:
        """Por especie: [[nivel, movimiento], ...]. Formato Gen 5: u16 movimiento, u16 nivel; fin 0xFFFF."""
        out = []
        for raw in self.narc(LEARNSET):
            moves = []
            for i in range(0, len(raw) - 3, 4):
                move, level = struct.unpack_from("<HH", raw, i)
                if move == 0xFFFF:
                    break
                moves.append([level, move])
            out.append(moves)
        return out

    def move_pp(self) -> list[int]:
        return [raw[5] if len(raw) > 5 else 0 for raw in self.narc(MOVES)]   # byte 5 = PP base

    def text(self, index: int) -> list[str]:
        return decode_text(self.narc(TEXT)[index])


def decode_text(d: bytes) -> list[str]:
    """Texto cifrado de Gen 5 (formato de B/W y B2/W2)."""
    sections, lines = struct.unpack_from("<HH", d, 0)
    section_off = struct.unpack_from("<I", d, 0x0C)[0]       # primera sección (idioma principal)
    out = []
    for i in range(lines):
        off, length, _ = struct.unpack_from("<IHH", d, section_off + 4 + 8 * i)
        enc = struct.unpack_from(f"<{length}H", d, section_off + off)
        key = enc[-1] ^ 0xFFFF
        dec = [0] * length
        for j in range(length - 1, -1, -1):
            dec[j] = enc[j] ^ key
            key = ((key >> 3) | (key << 13)) & 0xFFFF
        chars = []
        for c in dec:
            if c == 0xFFFF:
                break
            if c == 0xF100:          # texto comprimido (9 bits): no aparece en los nombres que usamos
                chars.append("?")
                break
            chars.append({0x246D: "♂", 0x246E: "♀", 0xFFFE: "\n"}.get(c, chr(c)))
        out.append("".join(chars))
    return out


def build_data(rom: Rom) -> dict:
    personal = rom.personal()
    learn = rom.learnsets()
    names = rom.text(TEXT_SPECIES)
    species = {}
    for sp in range(1, 650):
        e = personal[sp]
        species[str(sp)] = {"name": names[sp], "stats": list(e[0:6]), "gender": e[0x12], "friendship": e[0x14],
                            "growth": e[0x15], "abilities": [e[0x18], e[0x19], e[0x1A]], "learnset": learn[sp]}
    return {
        "_fuente": f"ROM {rom.title} {rom.code} (v{rom.version}, crc cabecera {rom.header_crc:04x})",
        "rom": {"title": rom.title, "code": rom.code, "version": rom.version, "header_crc": rom.header_crc},
        "exp": EXP_TABLES,
        "species": species,
        "move_pp": rom.move_pp()[:560],
        "abilities": rom.text(TEXT_ABILITIES)[:165],
        "moves": rom.text(TEXT_MOVES)[:560],
        "items": rom.text(TEXT_ITEMS)[:639],
        # cada entrenador: [clase, tipo de combate (0 individual, 1 doble, 2 triple, 3 rotatorio), nº de Pokémon]
        "trainers": [[d[1], d[2], d[3]] if len(d) >= 4 else [0, 0, 0] for d in rom.narc(TRDATA)],
        "trainer_classes": rom.text(TEXT_TRAINER_CLASSES),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen5_data.json"))
    a = ap.parse_args()
    rom = Rom(a.rom)
    print(f"{rom.title}  código {rom.code}  versión {rom.version}  crc cabecera {rom.header_crc:04x}")
    if a.info:
        return
    data = build_data(rom)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"guardado en {a.out}")


if __name__ == "__main__":
    main()
