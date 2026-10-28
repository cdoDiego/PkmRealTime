# PkmRealTime — Pokémon Black 2 / White 2 en tiempo real

Modifica una partida de **Pokémon White 2** mientras se juega en **BizHawk**, mediante una API HTTP.
Una app externa (un bot de chat, Postman, curl…) envía eventos como "quema a mi primer Pokémon",
"dale 5 Pociones" o "regala un Bulbasaur", y el puente los aplica en la RAM del juego, de forma segura.

> **Estado:** en desarrollo. Validado en White 2 USA/Europa (`IRDO`) con BizHawk 2.11.1 (núcleo melonDS).
> Usa siempre una partida de prueba: cada evento guarda antes un savestate de seguridad (ranura 9).

## Qué se puede hacer

| Área | Eventos | Estado |
| --- | --- | --- |
| Equipo | Cambiar HP y estado, curar, objeto equipado, movimientos | ✅ validado en el juego |
| Mochila y dinero | Dar y quitar objetos; dar, quitar o fijar el dinero | ✅ validado en el juego |
| Regalos | Crear un Pokémon nuevo en la caja 1 (nivel, variocolor, género, objeto, movimientos, habilidad oculta) o directamente en el equipo (lo crea el juego; si está lleno, a una caja) | ✅ validado en el juego |
| Combate | Vida (también debilitar), los 7 estados, estadísticas, PP y clima de cualquier combatiente, tuyo o rival, en el campo o en el banco; individual, doble y contra entrenador. Todo se anima con los gráficos del juego | 🧪 experimental, validado en el juego |
| Mapa | Forzar un combate salvaje contra cualquier Pokémon y nivel, o contra cualquier entrenador, en cualquier sitio; cambiar el clima; teletransporte a cualquier ciudad | 🧪 experimental, validado en el juego |
| Seguridad | Solo escribe con el personaje caminando libre (no en menús ni diálogos), comprueba que la memoria no cambió antes de escribir, y `POST /rollback` deshace el último evento | ✅ |

Funciona con **ROM aleatorizadas (randomizer)**: los datos de especies, movimientos y PP se leen de la ROM de cada persona.

## Cómo funciona

```
 App externa ──HTTP/WebSocket──▶ bridge.py ◀──TCP──▶ lua/connector.lua (dentro de BizHawk) ──▶ RAM del juego
```

`connector.lua` lee la RAM unas 6 veces por segundo y se la envía al puente. El puente descifra los Pokémon,
prepara los cambios y le dice al Lua qué escribir.

## Requisitos

- Python 3.10 o superior
- [BizHawk](https://tasvideos.org/BizHawk) 2.9 o superior (probado con 2.11.1), con el núcleo melonDS para NDS
- Tu propia ROM de Pokémon White 2 (USA/Europa). **El repositorio no incluye ninguna ROM.**

## Instalación

```bash
pip install -r requirements.txt
cp config_local.example.py config_local.py     # en Windows: copy config_local.example.py config_local.py
```

En `config_local.py`, pon la ruta a tu ROM en `ROM_PATH` y cambia el token de `API_TOKENS`.
Al arrancar, el puente genera `gen5_data.json` desde tu ROM. A mano: `python rom.py "ruta.nds"`.

## Uso

1. `python bridge.py`. Espera a que diga `Esperando a BizHawk...`.
2. Abre BizHawk conectado al puente (después del puente: BizHawk solo se conecta al abrirse):
   ```
   EmuHawk.exe --socket_ip=127.0.0.1 --socket_port=43884
   ```
3. Carga White 2 y, en *Tools > Lua Console*, abre `lua/connector.lua`.
4. Prueba la API (o importa `postman/postman_collection.json` en Postman):
   ```bash
   curl http://127.0.0.1:8000/state -H "x-token: <tu token>"
   curl -X POST http://127.0.0.1:8000/events -H "x-token: <tu token>" -H "content-type: application/json" \
        -d '{"type":"set_status","target":{"slot":0},"status":"burn"}'
   ```

Todos los eventos, la API y sus respuestas: [docs/DOCUMENTACION.md, sección 7](docs/DOCUMENTACION.md#7-api).

## Estructura

| Carpeta / archivo | Qué contiene |
| --- | --- |
| `bridge.py` | Puente: API HTTP/WebSocket y servidor TCP para BizHawk |
| `pk5.py`, `bag.py`, `gift.py`, `battle.py` | Equipo, mochila, regalos y combate |
| `rom.py`, `gamedata.py`, `move_pp.py` | Datos del juego leídos de la ROM |
| `config.py` | Direcciones de memoria y valores por defecto |
| `config_local.example.py` | Plantilla de tu configuración personal |
| `lua/` | Scripts de BizHawk: `connector.lua` (el conector), `dump_ram.lua` y `watch_ram.lua` (para investigar) |
| `tools/` | `ram_tool.py`: analiza volcados de RAM |
| `tests/` | Pruebas: `python tests/run_all.py` |
| `postman/` | Colección de Postman |
| `docs/` | Documentación técnica completa |

## Documentación

[**docs/DOCUMENTACION.md**](docs/DOCUMENTACION.md) tiene:
- el mapa de memoria completo (cada dirección, de dónde salió y si está validada en el juego);
- el formato de los Pokémon (PK5), la mochila, las cajas y el combate;
- el protocolo entre el Lua y el puente;
- cómo buscar direcciones nuevas (volcados de RAM y comparación);
- la bitácora de hallazgos y errores corregidos;
- las pruebas pendientes.

## Pruebas

```bash
python tests/run_all.py
```

Las pruebas que necesitan la ROM o los volcados se saltan si no los encuentran.

## Créditos

- [NDS Ironmon Tracker](https://github.com/Brian0255/NDS-Ironmon-Tracker): punto de partida para las direcciones de equipo y combate.
- [PKHeX](https://github.com/kwsch/PKHeX): formato PK5, mochila y estructuras del save, y tabla original de PP (`move_pp.py`) y listas de objetos (`bag.py`).
- [Project Pokémon](https://projectpokemon.org/): documentación de las estructuras de Gen 5.

Pokémon es una marca de Nintendo, Creatures Inc. y GAME FREAK inc. Este proyecto no está afiliado a ellos
y no distribuye ROMs ni datos extraídos de ellas.

**Licencia:** pendiente de elegir.
