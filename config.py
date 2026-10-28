"""Configuración y direcciones de memoria (Pokémon Black 2 / White 2).

Lo personal (ruta de la ROM, tokens, puertos) NO se edita aquí: copia config_local.example.py
como config_local.py y cámbialo ahí. config_local.py no se sube a git.

Fuente: NDS Ironmon Tracker (constants/MemoryAddresses.lua, WHITE2).
En B2/W2 el equipo NO está en una dirección fija: hay un puntero en
MAIN_RAM_BASE + MAIN_POINTER_OFF y todo se calcula como puntero + offset.
connector.lua resuelve el puntero en cada consulta y le manda a Python la
dirección real del equipo, así que estos valores solo son de referencia en Python.
Validar en un save desechable antes de usar en la partida real.
"""

MAIN_RAM_BASE = 0x02000000   # BizHawk usa offsets desde aquí en el dominio "Main RAM"

MAIN_POINTER_OFF = 0x24      # u32 en 0x02000024; se descarta el byte alto
PARTY_PTR_OFF = 0x19728      # equipo = puntero + esto   (tracker: playerBase)
PARTY_COUNT_PTR_OFF = 0x19724  # nº de Pokémon = puntero + esto (tracker: totalMonsParty)
PARTY_SLOT_SIZE = 220

BATTLE_STATUS_ADDR = 0x021B5178   # u16 fijo; 0x2100/0x2101 = en combate (tracker: battleStatus)
BATTLE_STATUS_IN_BATTLE = (0x2100, 0x2101)

# En nuestras pruebas: puntero 0x02204D04 -> equipo en 0x0221E42C, contador en 0x0221E428.
# Ver DOCUMENTACION.md para la tabla completa.

BOX_PTR_OFF = 0xD20          # caja 1, slot 1 = puntero + esto (encontrado con ram_tool.py boxes, 2026-10-25)
# Slot n de la caja 1 = puntero + BOX_PTR_OFF + n * BOX_SLOT_SIZE.
BOX_SLOT_SIZE = 136
BOX_STRIDE = 0x1000          # cada caja: 30 huecos (0xFF0) + pie de 16 bytes con CRC (el juego lo recalcula al guardar)
BOX_SLOTS = 30
# Hueco vacío = Pokémon cifrado con PID 0 y especie 0 (no ceros). Validado con volcados el 2026-10-27.

TRAINER_PTR_OFF = 0x19D20    # datos del jugador (MyStatus): nombre, TID/SID, idioma, juego, género
TRAINER_SIZE = 0x24
SEASON_PTR_OFF = 0x36834     # estación u8 (0 primavera, 1 verano, 2 otoño, 3 invierno); código Action Replay "Season Changing"
SEASON_FORCE_OFF = 0x0A     # desde la estación: sincronización forzada u8 (GameData + 0x1D2; la estación es + 0x1C8)
MISC_PTR_OFF = 0x21A20       # bloque Misc del save (0x21100): dinero u32, medallas u8 en +4
MISC_SIZE = 8
MAX_MONEY = 9_999_999
# La RAM es una copia del save desplazada: RAM = puntero + 0x920 + offset en el save de B2W2
# (mochila 0x18400, equipo 0x18E00, jugador 0x19400, cajas 0x400). Validado con volcados.

BAG_PTR_OFF = 0x18D20        # mochila = puntero + esto (sin cifrar; 0x998 bytes, ver bag.py)
# Validado con volcados el 2026-10-26: Poké Ball x9 en objetos, Poción x1 en medicinas.
# Bolsillo de medicinas = puntero + 0x194F8 (el "itemStartNoBattle" del tracker).

MAILBOX_VAR_ADDR = 0x0       # TODO variable de script para el buzón (no está en el tracker; aún no se usa)

MENU_FLAG_ADDR = 0x0223B2F5  # u8: 0 = caminando libre; 1 = menú/diálogo/equipo/datos/mochila/combate
# Encontrado con ram_tool.py diff + watch_ram.lua (2026-10-26). Puntero en esa prueba: 0x02204D04
# (puntero+0x365F1). Sigue funcionando tras reiniciar el juego (validado 26-oct).

# Valores que el Lua manda como "modo" (los decide connector.lua)
MODES = ("map", "battle", "menu", "unknown")

# ---------------------------------------------------------------- valores por defecto (se cambian en config_local.py)

# Ruta a la ROM (.nds) que se juega. Si está puesta, el puente genera gen5_data.json desde ella al arrancar
# (y lo rehace si cambia la ROM). Así se usan las habilidades, movimientos, PP y nombres de ESA ROM.
# Puede ser absoluta o relativa a esta carpeta.
ROM_PATH = ""

BRIDGE_HOST = "127.0.0.1"
LUA_PORT = 43884             # BizHawk se lanza con --socket_ip=127.0.0.1 --socket_port=43884
API_PORT = 8000
API_TOKENS = {"dev-token-cambiame": "yo"}   # token -> nombre del cliente. Cámbialo en config_local.py

# Herramientas de investigación (eventos debug_peek / debug_poke: leer y escribir cualquier dirección).
# Desactivadas por defecto: actívalas en config_local.py solo con una partida de prueba.
DEBUG_WRITES = False

try:
    from config_local import *  # noqa: F401,F403  (configuración personal, no se sube a git)
except ImportError:
    pass


def rom_path() -> str:
    """ROM_PATH como ruta absoluta (las relativas cuentan desde la carpeta del proyecto), o "" si no hay."""
    import os
    if not ROM_PATH:
        return ""
    return ROM_PATH if os.path.isabs(ROM_PATH) else os.path.join(os.path.dirname(os.path.abspath(__file__)), ROM_PATH)
