# Documentación — White 2 en tiempo real

Qué hace cada pieza, qué direcciones de memoria usamos, cómo se encontraron y qué falta probar.
Juego: **Pokémon White 2 USA** (código `IRDO`) · Emulador: **BizHawk 2.11.1** (núcleo melonDS).

---

## 0. Estructura del repositorio

```
├── bridge.py              Puente: API HTTP/WebSocket + servidor TCP para BizHawk
├── pk5.py                 Cifrado PK5 y cambios en Pokémon (HP, estado, curar, objeto, movimientos)
├── bag.py                 Mochila: bolsillos, dar y quitar objetos
├── gift.py                Crear Pokémon nuevos (regalos); exporta .pk5 para PKHeX
├── battle.py              Estructura de combate (fase 5): lectura y escrituras; condiciones, atrapado, ataque encadenado
├── battle_cmd.py          Comandos del servidor del combate: codificar (inyección) y leer bloques (registro)
├── battle_log.py          Registro del combate: qué pasó en cada turno y lo que el rival ha revelado
├── rival.py               Control del rival: ver y cambiar lo que eligió la IA, pausa del turno
├── encounters.py          Zona actual y tabla de encuentros salvajes de la zona
├── happenings.py          Avisos de lo que pasa en el juego (capturas, debilitados, medallas, zona...)
├── boxes.py               Cajas del PC: nombres, caja abierta, Pokémon de cada caja
├── pc.py                  Mover y quitar Pokémon entre equipo y cajas
├── effects.py             Catálogo de efectos con nombre (premios de la ruleta; luego Twitch y cartas)
├── roulette.py            Ruleta: premios guardados en roulette.json y elección por peso
├── wondercard.py          Regalo Misterioso: tarjetas PGF y cifrado del álbum
├── rom.py                 Lee datos de la ROM → gen5_data.json
├── gamedata.py            Carga gen5_data.json
├── move_pp.py             PP máximos (usa los de la ROM; tabla original de respaldo)
├── config.py              Direcciones de memoria y valores por defecto
├── config_local.example.py  Plantilla de configuración personal (copiar como config_local.py)
├── requirements.txt
├── overlay/               Overlay y ruleta para OBS (páginas de configuración + vistas); lo sirve el puente en /overlay/
├── lua/                   Scripts de BizHawk: connector.lua, dump_ram.lua, watch_ram.lua
├── tools/                 ram_tool.py (análisis de volcados), wonder_card.py (álbum del Regalo Misterioso),
│                          rom_compare.py (romhacks), sprites_gen5.py (sprites de Showdown en la ROM),
│                          w2u_build/ (compilar White2Upgrade con Docker)
├── tests/                 Pruebas (run_all.py las ejecuta todas)
├── postman/               Colección de Postman con todas las peticiones
├── docs/                  Esta documentación
├── dumps/                 Volcados de RAM (no se suben)
├── wondercards/           Tarjetas oficiales .pgf descargadas (no se suben)
└── pk5_export/            .pk5 generados (no se suben)
```

No se suben a git (ver `.gitignore`): `config_local.py`, `roulette.json`, ROMs y partidas, `gen5_data.json` (sale de la ROM de cada persona),
`dumps/`, `pk5_export/`, `wondercards/` y `sprites_showdown/` (sprites descargados).

## 1. Cómo encaja todo

```
 App externa ──HTTP/WebSocket──▶ bridge.py ◀──TCP 43884──▶ connector.lua (dentro de BizHawk) ──▶ RAM del juego
 (curl, etc.)   puerto 8000      (Python)                   (Lua)
```

1. `lua/connector.lua` lee la RAM cada 10 frames (~6 veces por segundo) y manda a `bridge.py`:
   el modo del juego (`map`, `menu`, `battle`, `unknown`), la dirección del equipo y los bytes del equipo (cifrados).
2. `bridge.py` descifra el equipo con `pk5.py` y lo muestra en `GET /state`.
3. Cuando llega un evento (`POST /events`), el puente espera al modo correcto, prepara los bytes nuevos
   (descifrar → cambiar → recalcular checksum → cifrar) y se los manda al Lua.
4. El Lua guarda un savestate de seguridad (ranura 9) y escribe **solo si la memoria sigue igual** que cuando se leyó.

**Orden de arranque:** primero `python bridge.py`, después BizHawk (se conecta solo una vez, al abrirse),
después `lua/connector.lua`. Si cierras el puente hay que reiniciar BizHawk.

---

## 2. Mapa de memoria

Todas las direcciones son de la ARM9 Main RAM (`0x02000000`–`0x023FFFFF`).
En BizHawk, dominio `"Main RAM"`, se usa el offset: `dirección − 0x02000000`.

### El puntero base

En B2/W2 los datos de la partida **no están en una dirección fija**. El juego guarda un puntero:

```
puntero = u32 en 0x02000024, quitando el byte alto  (valor & 0xFFFFFF, + 0x02000000)
```

En nuestras pruebas el puntero vale siempre `0x02204D04`, pero el código lo vuelve a leer en cada consulta por si cambia.

### Tabla de direcciones

| Nombre | Dirección | Tipo | Significado | Fuente | Estado |
| --- | --- | --- | --- | --- | --- |
| Puntero base | `0x02000024` | u32 | Base de los datos de la partida | Ironmon Tracker (`MAIN_POINTER`) | ✅ validado 25-oct |
| Nº de Pokémon en el equipo | puntero + `0x19724` | u8 | 1–6 | Tracker (`totalMonsParty`) | ✅ validado 25-oct |
| Equipo, slot 0 | puntero + `0x19728` | 6 × 220 bytes | Pokémon cifrados (formato PK5). En la prueba: `0x0221E42C` | Tracker (`playerBase`) | ✅ leído y escrito 25-oct |
| Equipo, slot n | slot 0 + n × `0xDC` | 220 bytes | `0xDC` = 220 | — | ✅ (slot 0 y 1) |
| Caja 1, slot 1 | puntero + `0xD20` | 136 bytes | Pokémon de caja cifrado. En la prueba: `0x02205A24` | `ram_tool.py boxes` | ✅ leído 25-oct |
| Caja 1, slot n | caja 1 + n × `0x88` | 136 bytes | `0x88` = 136. Hueco vacío = Pokémon cifrado con PID 0 y especie 0 (no ceros) | Volcados | ✅ escrito 27-oct (regalos) |
| Caja b | caja 1 + b × `0x1000` | `0x1000` | 30 huecos (`0xFF0`) + pie de 16 bytes con CRC16 de la caja | Volcados + PKHeX | ✅ leído y escrito 29-oct (cajas 2 y 3) |
| Bloque 0 de las cajas | puntero + `0x920` | `0x3E0` | Nombres (`+0x04`, 24 × `0x28`, UTF-16 hasta `0xFFFF`), fondos (`+0x3C4`, 24 × u8), caja abierta u8 (`+0x3DC`), nº de cajas desbloqueadas u8 (`+0x3DD`: 8, 16 o 24) | pokebw2 `box.h` + RAM | ✅ leído 29-oct |
| Equipo: contador | puntero + `0x19724` | u32 | Nº de Pokémon; los huecos libres son un Pokémon "cero" cifrado (220 bytes) | RAM | ✅ escrito 29-oct (mover/quitar) |
| Datos del jugador | puntero + `0x19D20` | `0x24` bytes | Nombre (`+0x04`), TID (`+0x14`), SID (`+0x16`), idioma (`+0x1E`), juego (`+0x1F`), género (`+0x21`) | Volcados + PKHeX (`MyStatus5`) | ✅ usado en regalos 27-oct |
| Mochila | puntero + `0x18D20` | `0x998` bytes | 5 bolsillos sin cifrar (ver abajo). En la prueba: `0x0221DA24` | Volcados + PKHeX (`PlayerBag5B2W2`) | ✅ leída y escrita 27-oct |
| Estado de combate | `0x021B5178` | u16 | `0x2100` o `0x2101` = en combate | Tracker (`battleStatus`, W2) | ✅ validado 25-oct |
| Bandera de control libre | `0x0223B2F5` (puntero + `0x365F1`) | u8 | `0` = caminando libre; `1` = menú, diálogo, equipo, datos, mochila, combate. El Lua la lee relativa al puntero base: en White2Upgrade está en `0x0223E3D5` | `ram_tool.py diff` + `watch_ram.lua` | ✅ validado 26-oct (también tras reiniciar el juego) |
| Dinero y medallas (bloque Misc) | puntero + `0x21A20` | u32 + u8 | Dinero (tope 9.999.999) y medallas (un bit cada una, en `+4`). Bloque Misc del save (`0x21100`) | PKHeX (`Misc5`) + tracker (`badges` = `0x21A24`) | ✅ leído y escrito 27-oct (₽7188 → ₽8188, se conserva al guardar) |
| Variable del buzón | — | — | Idea inicial para pasar mensajes al juego | — | ➖ ya no hace falta: los guiones propios (`S`) cubren ese uso |
| `FieldStatus_GetReserveScript` | `0x0201936C` | código | Lee el guion reservado (`FieldStatus` + `0x12`, u16) | pokebw2 (B2 `0x02019340` + `0x2C`) | ✅ usado 27-oct (combates forzados) |
| `FieldEncount_CreateWildPkm` | `0x021A0E00` (overlay 36) | código | Crea el Pokémon salvaje; nº de tiradas de PID en `movs r6,#1` (`+0x18`) | pokebw2 `src/ov036/enc_pokeset.c` + símbolos `w2_us` + ROM | ✅ parcheado 30-oct (variocolor) |
| `FieldScript_AttachOpcodeGuard` | `0x02153DC8` | código | Se llama al crear la máquina de un guion (`r0` = VM, `pc` en `+0x20`) | pokebw2 (B2 + `0x40`) | ✅ usado 27-oct |
| Clima del combate (`sField`) | `0x021DD928` | 2 × u32 | Clima (0 nada, 1 sol, 2 lluvia, 3 granizo, 4 arena) y turnos (`0xFF` = sin fin) | pokebw2 (B2 + `0x40`; confirmado en el volcado) | ✅ escrito 27-oct |
| `ServerControl_CheckFainted` | `0x021A8A64` | código | Decide si un combatiente se debilita (`r1` = copia real) | pokebw2 (B2 + `0x40`) | ✅ usado 27-oct |
| `sItemEventAddTable` | `0x021D8F68` | 171 × {u32 objeto, función} | Objetos con efecto en combate; cada función es `movs r1,#n; str r1,[r0]; ldr r0,=tabla; bx lr` (nº de efectos y su tabla) | pokebw2 (B2 + `0x40`; confirmado en el volcado) | ✅ usado 28-oct |
| Lista de efectos del combate | `0x021DB1D4` (+ huecos libres en `0x021DB1E0`) | u32 profundidad, primera entrada, nº en uso | Efectos registrados (habilidades, objetos...), por prioridad. Entradas de `0x3C` bytes | pokebw2 `battle_event.c` (B2 + `0x40`; confirmado en el volcado) | ✅ escrito 28-oct |
| Estación y sincronización forzada (`GameData`) | puntero + `0x36834` (estación) y `+ 0x0A` (marca) | u8 + u8 | Estación (0 primavera, 1 verano, 2 otoño, 3 invierno) en `GameData + 0x1C8`; marca de sincronización forzada en `GameData + 0x1D2` | Código Action Replay "Season Changing" (documentos de Volt White 2) + pokebw2 `GameData_GetSeasons` | ✅ escrito 28-oct (nieve en octubre) |
| Álbum del Regalo Misterioso | puntero + `0x1D120` | `0xA94` bytes | Bloque del save `0x1C800`, **cifrado también en RAM** (LCRNG de PK5 sobre `0xA90` bytes; semilla = checksum u16 `+0xA90` + clave u16 `+0xA92` << 16). `+0x000` banderas "ya recibido" (2048 bits), `+0x100` 12 tarjetas PGF de `0xCC` (tipo `+0xB3`: 1 Pokémon, 2 objeto, 3 poder; ID `+0xB0`; `+0xB4` bit 0 = una vez, bit 1 = entregada) | pokebw2 `save/mystery_gift.h`, `system/mystery_data.c` + PKHeX (`PGF`, `MysteryBlock5`) | ✅ escrito 03-nov (Genesect, Pikachu y objeto entregados) |

Leyenda: ✅ validado en el juego · 🟡 encontrado, falta confirmar algo · ⚪ pendiente.

### La RAM es una copia del save

Todo lo que cuelga del puntero es el archivo de guardado de B2W2 desplazado `0x920` bytes:
**RAM = puntero + `0x920` + offset en el save**. Así, las posiciones del save que documenta PKHeX sirven para la RAM:

| Bloque | Offset en el save | En RAM |
| --- | --- | --- |
| Cajas | `0x400` | puntero + `0xD20` |
| Mochila | `0x18400` | puntero + `0x18D20` |
| Equipo (+4 contador, +8 Pokémon) | `0x18E00` | puntero + `0x19720` |
| Jugador | `0x19400` | puntero + `0x19D20` |

El pie con CRC de cada caja **no se actualiza en RAM** cuando depositas un Pokémon: el juego lo recalcula al guardar.
Por eso el puente tampoco lo toca.

### Mochila

Sin cifrar. Cada espacio son 4 bytes: objeto (u16) y cantidad (u16). El juego mantiene cada bolsillo sin huecos.

| Bolsillo | Offset desde el inicio | Espacios | Máximo por objeto |
| --- | --- | --- | --- |
| Objetos | `0x000` | 310 | 999 |
| Objetos clave | `0x4D8` | 83 | 1 |
| MT/MO | `0x624` | 109 | 1 |
| Medicinas | `0x7D8` (= puntero + `0x194F8`, el `itemStartNoBattle` del tracker) | 48 | 999 |
| Bayas | `0x898` (= puntero + `0x195B8`, el `berryBagStart` del tracker) | 64 | 999 |

Qué objeto va en qué bolsillo: listas de PKHeX copiadas en `bag.py`.

### Cómo decide el modo `connector.lua`

```
si el puntero o el nº de Pokémon no son válidos   → "unknown"   (no se escribe nada)
si u16 en 0x021B5178 es 0x2100 o 0x2101          → "battle"
si u8  en puntero + 0x365F1 ≠ 0                   → "menu"     (0x0223B2F5 en W2; 0x0223E3D5 en White2Upgrade)
si no                                             → "map"
```

Los eventos `en_mapa` (por defecto) solo se aplican en `map`, es decir, con el personaje caminando libre.

### Combate (fase 5)

Cada Pokémon en combate tiene **dos copias** de su estructura de combate, con el mismo formato:

| Copia | Tabla de punteros | Para qué la usa el juego |
| --- | --- | --- |
| **Real** | puntero + `0x52790` | Calcula el daño y decide si se debilita |
| **Visual** | puntero + `0x526A8` (la que lee el tracker) | Lo que se muestra; la barra de vida se anima hacia este valor cuando hay un cambio de vida |

Cada tabla tiene 6 punteros del jugador (el activo primero) + un contador, y desde `+0x1C`, los del rival + su contador.
Siguen otros dos bloques iguales: `+0x38` el compañero del jugador (combate multi) y `+0x54` el segundo rival (combate
contra dos entrenadores, visto el 28-oct); el puente los muestra con los índices 6-11 de su lado.
En la prueba, cada copia real estaba `0xEFC` bytes después de su visual, pero se usan las tablas, no esa distancia.

**Estructura de cada combatiente** (sin cifrar):

| Offset | Campo | Estado |
| --- | --- | --- |
| `+0x00` | Puntero al Pokémon (PK5 cifrado, 220 bytes) | ✅ leído |
| `+0x04` | Puntero de Ilusión | — |
| `+0x0E` / `+0x10` | Vida máxima / vida actual (u16) | ✅ leídas · ✅ vida escrita 27-oct |
| `+0x18` | Nivel | ✅ leído |
| `+0x1C` | **Condiciones**: lista de u32, una por condición (índice = nº de estado de Gen 5). 0 = no la tiene, 1 = permanente. Parálisis `+0x20`, sueño `+0x24`, congelado `+0x28`, quemado `+0x2C`, envenenado `+0x30` | ✅ parálisis leída · ✅ quemadura escrita 27-oct |
| `+0xEE` | Ataque, Defensa, At. Esp., Def. Esp., Velocidad (u16) | ✅ leídos |
| `+0xFC` | Cambios de estadísticas: Atq, Def, AtE, DfE, Vel, Precisión, Evasión (1 byte cada uno, 0–12, 6 = sin cambio) | ✅ leídos: Ataque (Gruñido) y Defensa (Malicioso, Látigo); el resto, por orden |
| `+0x104` | 4 movimientos × 14 bytes: u16 movimiento, u8 PP, u8 PP máx, 2 bytes, y en `+6` una copia de respaldo de esos 6 bytes (para volver tras Transformación/Mimético) | ✅ leídos (PP bajan al usarlos) |

**Lo que se aprendió escribiendo la vida:**
- Escribir solo la copia visual: la barra no cambia. Al siguiente golpe, el juego calcula el daño con la copia real
  (el Patrat seguía vivo con 3) y la barra se vació igual, porque la visual restó el daño a 1. Combate incoherente.
- Escribir **las dos copias**: la barra sigue igual hasta el siguiente cambio de vida, y entonces se anima al valor correcto.
  Con 1 de vida, un Placaje lo debilitó, Oshawott ganó experiencia y el combate terminó bien.
- Pendiente: que la barra se actualice al momento (habría que encontrar el dato del indicador en pantalla).

**Lo que se aprendió con el estado:**
- El tracker lee el estado como un único u32 en `+0x20`, pero en realidad es la **entrada de parálisis** de una lista
  (su bucle parece pensado para recorrer la lista, pero siempre lee la misma dirección).
- Escribir 4 en `+0x20` no quemó: solo cambió la "duración" de la parálisis, que siguió activa.
- Borrar la entrada de parálisis y poner 1 en la de quemadura (`+0x2C`), en las dos copias: al final del turno salió
  la animación y el mensaje de quemadura, y el Purrloin perdió 2 de 17 (1/8). Sin efectos de parálisis.
- El **ícono de estado y el color** del Pokémon son de la interfaz y no cambian (siguió con PAR y en amarillo).
  Es el mismo caso que la barra de vida: la parte visual se actualiza solo con los eventos del combate.

### Indicadores de vida en pantalla (opción A, en investigación)

La pantalla de arriba tiene un **indicador** por Pokémon. Zona base: u32 en puntero + `0x90088` (tracker: `someBattleUIPtr`),
que en las pruebas apuntaba siempre a `0x022A8514`. Tu indicador está en la zona + `0x88` (`0x022A859C`) y el del rival en
la zona + `0x10C` (`0x022A8620`).

| Offset | Campo |
| --- | --- |
| `+0x00` | Vida (u32): la de antes de la animación; al terminarla, la nueva |
| `+0x04` | Vida máxima (u32) |
| `+0x08` | Vida dibujada × 256 (u32) durante la animación; 0 en reposo |
| `+0x20` | Daño de la última animación (u32) |
| `+0x24` | Nivel (byte 0); bytes 1 y 3: género |
| `+0x2C` | 1 desde la primera animación |

Grabado durante un golpe (16 → 6): `+0x20` = 10, `+0x08` baja 16 → 15,3 → 12 → 8,7…, y al final `+0x00` = 6 y `+0x08` = 0.

**Conclusión:** la barra **solo se redibuja mientras corre la animación** que pone en marcha el propio combate.
Cambiar `+0x00` o `+0x08` a mano no la redibuja, y volver de la pantalla de Pokémon o de la mochila solo reconstruye
la pantalla de abajo. El ícono de estado tampoco está en el indicador: no se encontró dónde lo guarda.

### Servidor, cliente y comandos de combate (opción 3, investigación)

Fuentes: [showdown-bw2](https://github.com/LuciPengu/showdown-bw2) (reproduce combates de Showdown dentro de BW2
escribiendo en RAM con melonDS) y la decompilación [pokebw2](https://github.com/fuddlesworth/pokebw2)
(`include/battle/btl_server_cmd.h`). Sus direcciones son de Black 2; en White 2 están **+0x40**.

El combate es un **servidor** (la lógica) que manda **bloques de comandos** a los **clientes** (la pantalla del jugador y la IA)
a través de un **adaptador** en RAM. El cliente copia el bloque a su cola interna y lo reproduce con las animaciones del juego.

| Pieza | Black 2 | White 2 (volcados) |
| --- | --- | --- |
| `sAdapters[4]` (punteros a los adaptadores) | `0x021DD86C` | `0x021DD8AC` |
| Función principal del cliente (Thumb) | `0x021B19D5` | `0x021B1A15` |
| Cliente del jugador / su adaptador (en las pruebas) | — | `0x0225FFF4` / `0x02260274` |
| Cola interna del cliente (puntero en cliente + `0x13C`) | — | `0x02260E70` |
| Servidor (en las pruebas) | — | `0x0225D01C` |

- **Adaptador:** `+0x04` datos de respuesta, `+0x08` tamaño de respuesta, `+0x0C` respondido (bit bajo), `+0x10` comando (u16:
  3 = elegir acción, 8 = bloque de comandos), `+0x12` tamaño (u16), `+0x14` datos.
- **Cliente:** `+0x00` módulo principal, `+0x28` función principal, `+0x50` adaptador, `+0x13C` cola interna,
  `+0x1AF` tipo (0 = jugador), `+0x1B0` estado (0 libre, 1 ejecutando, 2 respondiendo).
- **Cola:** `u32 escritura; u32 lectura; u8 búfer[3000]`. Al recibir un bloque: escritura = tamaño, lectura = 0.
  Está vacía cuando lectura = escritura.
- **Formato de un comando:** número de comando en u16 big-endian y sus argumentos empaquetados (tabla de formatos en
  `src/bw/servercmd.ts` de showdown-bw2). Comprobado: los bloques reales de White 2 se leen igual
  (ej. `00 0a 62 01` = `OP_LOWER_STAT_STAGE`, Pokémon 12, Defensa −1).
- **Identificador de cada Pokémon (pokeID):** byte `+0x19` de su estructura de combate. Tu equipo 0–5; el rival en las pruebas, 12.
- Comandos útiles: `OP_SUBTRACT_HP` (`0x01`), `OP_ADD_HP` (`0x02`), `OP_SET_CONDITION` (`0x0F`), `OP_CURE_CONDITION` (`0x10`),
  `SET_GAUGE_STATUS` (`0x35`, ícono de estado), `UPDATE_HP_GAUGE` (`0x41`, anima la barra), `STAT_UP/DOWN_EFFECT`,
  `MSG_STD`/`MSG_SET` (mensajes).

**Rastreo de un turno** (`lua/trace_adapter.lua`): tras elegir acción, el servidor manda el bloque del turno (137 bytes) y el
cliente **lo toma en el mismo frame**; luego lo reproduce durante unos 790 frames (13 s). Entre turnos el cliente queda libre
solo 3 frames antes del siguiente "¿Qué hará…?".

**Veredicto (27-oct):** es viable insertar comandos propios **en la cola interna del cliente mientras reproduce un turno**
(en la posición de lectura, para que se vean enseguida). Límite: con el menú de acción abierto el cliente está ocupado, así que
un evento enviado en ese momento se vería al empezar a reproducirse el turno siguiente.

**Implementado y validado (27-oct):**
- `battle_cmd.py` codifica los comandos; produce byte a byte los mismos bloques que el juego (`tests/test_battle_cmd.py`).
- Comando `J <hex>` del Lua: deja el bloque pendiente (varios se acumulan). En cuanto el cliente del jugador está reproduciendo
  un bloque del servidor (estado 1, comando 8) y le quedan comandos por leer, inserta el bloque en la posición de lectura y
  sube la de escritura. Si el combate termina con algo pendiente, se descarta. En pantalla: línea "inyección: …".
- `battle_set_hp` añade `UPDATE_HP_GAUGE` y `battle_set_status` añade `SET_GAUGE_STATUS` (con el mismo número de estado).
- Prueba en el juego: Purrloin a 1 de vida y quemado → al empezar el turno, la barra bajó animada y apareció el ícono de
  quemado; al final del turno la quemadura lo debilitó con su animación, y Oshawott ganó experiencia y subió de nivel.
  Antes, con la inyección manual: barra + ícono PAR + color amarillo de la parálisis.

### Debilitar con vida 0

**Problema (27-oct):** con la vida puesta a 0 por fuera, tu Pokémon no se debilitó y el rival se quedó atacando y fallando en bucle.

**Causa (decompilación pokebw2, `src/ov167/btl_server_flow.c`):** el juego solo debilita en `ServerControl_CheckFainted(flow, mon)`
(mensaje, comando `FAINT`, experiencia y registro para pedir el cambio). La llama tras cada golpe (atacante y objetivos) y al final
del turno para cada Pokémon **vivo** (`BtlFlow_IsMonAlive` = vida distinta de 0). Uno puesto a 0 por fuera ya cuenta como
debilitado: no actúa, no se le puede atacar y la revisión del final del turno lo salta, así que nunca se procesa.

**Solución:** la copia real queda a 1 y el Lua la pone a 0 justo cuando el juego llama a `CheckFainted` con ese Pokémon.
- `CheckFainted` en White 2: `0x021A8A64` (Black 2 `0x021A8A24` + 0x40; empieza por `push {r3-r7, lr}` en los volcados).
- BizHawk (melonDS) avisa al Lua al ejecutarse una dirección: `event.on_bus_exec`. El registro `ARM9 r1` es el `mon`, la dirección
  de la copia real. Comprobado con `lua/trace_faint.lua`: en un turno sin daño hubo 10 llamadas (5 etapas del final del turno × 2).
- Comando `F <dir>` del Lua: deja pendiente esa copia y registra el aviso (solo mientras hay algo pendiente, porque cada
  instrucción se compara con la dirección). Al llegar la llamada, si sigue a 1 de vida, escribe 0; si cambió, se cancela.
  Si el combate termina, se descarta. En pantalla: línea "debilitar: …".
- `battle_set_hp` con 0 manda `F` (primero, para no escribir nada si el Lua no puede), la copia real a 1, la visual a 0 y
  `UPDATE_HP_GAUGE` (la barra se vacía al empezar el turno).
- Límite: el Pokémon aún ataca ese turno antes de debilitarse (la primera revisión llega tras su propio golpe).
  **Mejora futura:** que caiga antes de actuar, cambiando el `r1` de una de las primeras llamadas a `CheckFainted` del turno por
  el nuestro. Riesgo: el Pokémon que debía revisarse en esa llamada podría quedarse sin procesar (el mismo limbo de antes).

**Posibilidad futura: verlo al instante con el menú abierto.** Con "¿Qué hará…?" abierto el cliente está ejecutando el comando
de elegir acción. showdown-bw2 muestra que se puede: pausar la lógica (`server.state` = 2), cerrar el menú respondiéndolo
(pulsaciones simuladas), mandar un bloque propio, volver a abrir el menú y, en nuestro caso, reanudar la lógica para que reciba
la elección real. Es factible pero frágil (el menú se cierra y reabre, y pausar/reanudar la lógica puede trabar el combate).
Decisión (27-oct): no por ahora; alternativa barata si hiciera falta, un aviso dibujado por el Lua mientras el evento espera.

### Control del rival, pausa y registro de turnos (04-nov, experimental)

Fuente: decompilación pokebw2 (`src/ov167/btl_client.c`, `btl_server.c`, `btl_adapter.c`, `btl_server_cmd.c`,
`include/battle/btl_action.h`, `btl_pokeparam.h`). Direcciones W2 de `config/w2_us/arm9/overlays/ov167/symbols.txt`.

**Cómo decide el rival.** El servidor pide a cada cliente, por su adaptador, "elegir acción" (comando `3`), "cambio tras
debilitarse" (`5`) o "cambio a mitad de turno" (`6`, Ida y Vuelta, Voltiocambio...). La IA responde en 2-3 frames
(`AISelectAction`, `AISelectChangePoke`) y su respuesta (un `BattleAction` u32 por posición) queda en RAM, apuntada por el
adaptador (`+0x04`, tamaño en `+0x08`). El servidor la copia **sin revisarla** (`BattleServer_StoreClientActions`) cuando
todos han respondido (`BattleServer_AllClientsReplied`); los tres pedidos pasan por ahí, también el aviso del estilo
"Cambio" ("va a sacar a X"), que se lee después. Validado en `combate2.bin`: rival con `0x501` (Arañazo contra la posición 0)
mientras el jugador seguía en el menú.

| `BattleAction` (u32) | Bits |
| --- | --- |
| Tipo | 0-3: 0 nada, 1 atacar, 2 objeto, 3 cambiar, 4 huir, 7 sin acción (recarga) |
| Atacar | 4-6 posición del objetivo (individual: 0 = jugador), 7-22 movimiento |
| Cambiar | 4-6 posición, 7-9 hueco del equipo (orden del combate: 0 = el que está en el campo), 10 "no queda nadie" |

**Estado del adaptador** (`+0x0E`): 0 libre, 1 enviar, 3 esperando respuesta, 4 respondido. El 4 no significa leído: el
servidor la lee cuando todos respondieron y lo deja en 0 en el mismo frame. Con 1-4 la respuesta aún se puede cambiar
(`rival_action` escribe con `G`, con guarda en la respuesta y en ese byte).

**Pausa (sin parches de código).** Con el estado del adaptador del rival en **2** (valor que el juego no usa),
`BtlAdapter_WaitCmd` devuelve FALSE y el servidor espera aunque los dos ya hayan elegido. El menú y la IA no se tocan. El Lua lo
hace en cada frame en cuanto llega un pedido 3/5/6 (orden `H 1 <frames>`), y lo suelta (vuelve a 3) con `HR`, al pasar el
tiempo máximo, al desactivarla o al cerrar el script. El puente la suelta sola si el rival no tiene nada que decidir (p. ej.
solo se debilitó el tuyo) y tras aplicar un `rival_action` (salvo `keep_paused`). En pantalla: "pausa del rival: ...".

**Bloquear los botones del jugador** (investigado, no implementado): `joypad.set` de BizHawk no deja claro si `false` anula la
entrada del usuario, y en DS el menú del combate también se usa con la pantalla táctil. La pausa del servidor cubre la necesidad
(el jugador puede elegir, pero el turno no avanza hasta la decisión), así que no hace falta.

**Comprobaciones** (las que el juego hace solo en el cliente, `btl_client.c`): no cambia si está atrapado (`IsMonTrapped`:
Sombra Trampa, Trampa Arena con sus excepciones de volador/Levitación/Globo/Levitón/Telequinesis y Bola Férrea/Derribo/Arraigo,
Imán con tipo acero; condiciones Mal de Ojo/Bloqueo, Atadura y similares, Arraigo; Muda Concha lo libra), ni hacia un
debilitado, el que está en el campo o uno que ya va a entrar. No se elige nada si el turno lo decide el juego
(`AutoSelectAction`: ataque encadenado, cargando, bandera 12 = recarga). Movimiento: con PP, y no bloqueado por Objeto elección,
Otra vez, Mofa (movimientos de estado, con la categoría de la ROM), Tormento o Anulación. No se ven la Gravedad ni Cerca (efectos
del campo): ahí el juego hace fallar el movimiento al usarlo.

**Más de la estructura del combatiente** (`BattleMon`, validado en los volcados): `+0xF8` tipos, `+0x13C` habilidad activa,
`+0x146` turnos en el campo, `+0x14A` último movimiento, `+0x152` último objetivo, `+0x155` banderas de estado (2 bytes).
Condiciones `+0x1C` (36 × u32): bits 0-2 tipo, 3-8 turnos, y un dato (movimiento de Otra vez, Anulación, Objeto elección o
ataque encadenado) en los bits 9-24 (15-30 en el tipo 4). `/state` las muestra en `volatile` y `locked`. El Lua envía ahora
`0x160` bytes por combatiente.

**Registro de turnos.** Cada vez que el servidor manda el bloque del turno al jugador (comando `8`), el Lua lo copia del
adaptador (en cada frame, no solo en cada consulta) con el número de turno (sube con cada "elegir acción") y lo envía en la
siguiente consulta (último campo del `POLL`). `battle_cmd.decode` lo lee como el juego (`BtlServerCmdQueue_Read`, tabla de
formatos de la decomp, saltando los huecos `RESERVE`), y `battle_log.py` lo convierte en eventos: movimiento usado, daño (y %),
golpe crítico, curas, debilitado, entra/retira, estados y condiciones, cambios de estadísticas, habilidad activada, objeto usado
o gastado, Ilusión rota, clima, sustituto, transformación, experiencia, Poké Ball. Al empezar cada turno guarda una foto de los que
están en el campo (vida, PP, estado, cambios, condiciones, atrapado, encadenado). `revealed` junta lo que el rival ha mostrado
(movimientos usados, habilidad, objeto), útil para un overlay sin trampas.

**Causa de cada cambio de vida** (`cause` en el evento y al final del texto): el comando de la vida no la dice, pero el juego
la marca justo antes (`btl_server_flow.c`): animación con su número (`0x257` veneno, `0x258` quemadura, `0x273` maldición,
`0x274` pesadilla, `0x290` clima; último argumento de `SC_EFFECT*`), mensaje del clima (`0x18C` arena, `0x18F` granizo),
`USE_HELD_ITEM` u `OP_CONSUME_ITEM` (objeto: Restos, Casco Dentado, bayas), la ventana de la habilidad (`ABILITY_POPUP_IN`…`OUT`:
Piel Tosca, Cura Lluvia), el movimiento en curso (`MOVE_MSG`: daño al objetivo o retroceso al atacante), la entrada al campo
(trampas) y el final del turno (`ServerControl_TurnCheck` empieza con `HIDE_MSG_WINDOW`). Lo que no tiene marca propia
(Drenadoras, Atadura) sale como "al final del turno". Cada daño o cura lleva además `hp`/`max_hp` tras el golpe: la copia real
ya tiene la vida del final del bloque (el servidor calcula el turno entero antes de mandarlo) y se calcula hacia atrás.
Cada turno guarda sus bloques en crudo (`blocks`), para rehacer el registro más adelante.

**Siguiente fase (pendiente):** registro estilo Pokémon Showdown (`|move|`, `|-damage|… [from] item: Leftovers`, `|switch|`,
`|-supereffective|`, `|turn|`…) en la parte visual. Los eventos ya tienen lo necesario (quién, qué, causa, vida y % tras cada
golpe, turno). Los textos de los mensajes del juego (`MSG_*`) no se
traducen todavía, solo se cuentan. Se guardan los 3 últimos combates.

### Objeto en combate

**Problema:** el objeto de un combatiente está en `+0x12` (`heldItem`; `+0x14` es el objeto ya consumido), pero cambiarlo ahí no
basta. Los efectos de los objetos (Restos, bayas...) son entradas en una lista de efectos del combate, y el juego solo las registra
cuando el Pokémon entra al campo o cuando un movimiento cambia el objeto (`ServerControl_ChangeHeldItem`: `ItemEvent_RemoveItem`,
`SetItem`, `ItemEvent_AddItem`; `src/ov167/item_handlers.c` y `battle_event.c` en pokebw2).

**Solución (orden `I <copia real> <objeto>` del Lua):** hace lo mismo desde fuera, entre frames, solo si la profundidad de la lista
es 0 (el juego no está ejecutando efectos):
1. quita las entradas de tipo 5 (objeto) de ese pokeID que no sean temporales (`work[6]` = 0): las desengancha y devuelve el hueco;
2. escribe el objeto en `+0x12` de la copia real (Python escribe la visual con `G`);
3. busca el objeto en `sItemEventAddTable`, lee de su función el nº de efectos y la tabla, y añade una entrada con prioridad
   `(1 << 24) | velocidad`, insertada en orden (mayor primero) como `BattleEvent_AddItem`.

Comprobado con el volcado `combate2`: el Pikachu con Restos tenía registrada exactamente la entrada que genera el Lua (2 efectos,
tabla `0x021D87B0`, prioridad `0x01000024`). Un objeto sin efecto en combate (p. ej. Pepita) solo se escribe en `+0x12`.

### Combates forzados y clima del mapa (guiones propios)

**Cómo:** el mapa revisa cada frame, con el personaje libre, si hay un "guion reservado" (`FieldStatus.reservedScript`, u16 en
`+0x12`; `CheckReserveEventScriptCall` en `src/ov036/fieldmap_event.c`) y, si lo hay, lo ejecuta. El comando `S <hex>` del Lua:
1. Aviso en `FieldStatus_GetReserveScript` (`r0` = FieldStatus): escribe el guion 2000 (global) como reservado.
2. Aviso en `FieldScript_AttachOpcodeGuard` (`r0` = VM, recién cargado el guion): escribe nuestros bytes en `VM.pc` (`+0x20`),
   encima del guion cargado. Solo se usa su espacio; el guion 2000 original no se ejecuta.
3. El juego ejecuta nuestras órdenes con su propia lógica: transición, música, combate, derrota (`EventBattleLose`) y vuelta al mapa.

Formato de los guiones: u16 por orden y u16 por argumento (little-endian; < `0x4000` = constante). Órdenes (pokebw2):
`0x0174` combate salvaje (especie, nivel, opciones) · `0x0175` fin del combate salvaje · `0x0177` ¿ganó? (variable) · `0x0176`
derrota · `0x0085` combate contra entrenador (entrenador 1, entrenador 2, opciones) · `0x008D` ¿ganó? · `0x008C` derrota ·
`0x008E` fin del combate contra entrenador · `0x0019` comparar variable con valor · `0x001F` saltar si (condición u8, salto u32) ·
`0x0136` clima del mapa (clima, inmediato) · `0x028A` volar a una zona (zona, dirección) · `0x00C2` ir a una casilla (zona, x, z,
dirección) · `0x010E` añadir al equipo (resultado, especie, forma, nivel, habilidad, sexo, variocolor, objeto, ball) · `0x0123`
lo mismo a la primera caja con sitio · `0x010F` huevo al equipo (resultado, especie, forma) · `0x0002` fin. Se arman en `field_script.py`. Tras cada combate el guion pregunta si
ganó: si perdió, derrota; si no, vuelta al mapa (sin eso, perder cuelga el juego).

**Desplazamiento White 2 / Black 2:** los símbolos públicos son de Black 2. Para el código principal es `+0x2C` y para los
overlays del mapa (12, 36) y del combate (167), `+0x40`. Se comprobó contando cuántas funciones de los símbolos empiezan
por `push {…, lr}` en los volcados con cada desplazamiento (`tools/symbol_offset.py`): ~98 % con el elegido.

**Clima del mapa:** se pierde al volver de un combate (el mapa se recarga con el de la ruta). Con `persist` el puente lo
vuelve a poner cada vez que se regresa al mapa. Un combate que empieza con lluvia/nieve/arena la mantiene
(`ConvFieldWeatherToBtl`: 2, 6, 7 → lluvia; 3, 12 → arena; 4, 5 → granizo; validado con 3 y 4).

**Clima del combate:** `sField` (estático de `btl_field.c`) guarda el clima que usa la lógica; la pantalla lo recibe con
`WEATHER_START` (0x3F, clima y turnos) y `WEATHER_END` (0x40, clima). `battle_set_weather` escribe `sField` con guarda y manda
el comando por la cola del cliente, igual que hace `ServerControl_ChangeWeatherCore`. Los turnos los descuenta el juego.

### Encuentros salvajes del mapa (investigación, 28-oct)

Objetivo: cambiar qué Pokémon salen en una ruta (p. ej. "Ruta 2 solo iniciales, domingo de 0:00 a 23:59") sin salir de la
partida ni tocar la ROM.

- Al entrar en una zona, el juego copia su tabla de encuentros de la ROM (archivo `a/1/2/7`, 135 tablas; `EncData_Load`,
  overlay 12) a un bloque de **0xE8 bytes** en RAM. Cada encuentro salvaje se sortea **leyendo ese bloque en el momento**
  (`FieldEncount_GenWilds(system->encData, ...)`), así que si lo cambiamos, el siguiente encuentro ya sale de la tabla nueva.
- Dirección: `EventData = *(GameData + 0x158)` (getter `GameData_GetEventData`, arm9 `0x02017240`, igual en B2 y W2) y la tabla
  está en `EventData + 0x38` (`GetEncountData`, overlay 12 W2 `0x0215CF70`: `adds r0, #0x38`). `GameData = puntero + 0x3666C`
  (la misma base que la estación). En los volcados: `EventData = 0x0223B7C8`, tabla en `0x0223B800`.
- **Comprobado con los volcados:** en `combate1.bin`/`combate2.bin` (Ruta 19) la tabla es Patrat/Purrloin niveles 2-4 en la
  hierba y Basculin 5-15 en el agua, idéntica a la tabla 128 de `a/1/2/7` salvo el bit 7 del byte 7, que `EncData_Load` enciende
  al cargar (marca "tabla válida"; sin él `EncSys_IsActive` no hay encuentros). En los volcados de ciudad la tabla está a cero.
- **Validado en el juego (28-oct, Ruta 20):** se leyó la tabla en vivo (Sunkern, Sewaddle, Patrat... en la hierba; Audino en la
  que se mueve) en la misma dirección `0x0223B800`; se escribieron los 12 iniciales de Kanto a Sinnoh en la hierba con
  `debug_poke` y salieron Mudkip, Charmander y Chikorita seguidos. La tabla sigue cambiada después de los combates.
  Al ir a Floccesy Town (sin encuentros) la tabla quedó a cero y al volver a la Ruta 20 el juego repuso la original:
  **se recarga al cambiar de zona** (y al cargar un savestate vuelve la del savestate).
- **Zona actual:** `PlayerState = GameData + 0x114` (`GameData_GetPlayerState`, arm9 `0x020171F4`: `movs r1,#0x45; lsls r1,#2`)
  y la zona es su primer `u16` (`PlayerState_GetZoneID`). Ruta 20 = 446, Floccesy Town = 439, Ruta 19 = 437.
- **De la ROM** (`rom.py` → `gen5_data.json`: `zones`, `places`, `encounters`): cabeceras de zona en `a/0/1/2` (un archivo,
  48 bytes por zona, 615 zonas): `+0x14` u16 & 0x1FFF = tabla de encuentros (0x1FFF = ninguna), `+0x1A` u8 = nombre en el
  texto 109. Las tablas de `a/1/2/7` de 928 bytes son 4 (una por estación: primavera, verano, otoño, invierno).
  `encounters.rom_table(zona, estación)` da la tabla tal como la deja el juego en RAM (comprobado con el volcado de la Ruta 19).
- `/state` muestra `location` y `encounters` (validado en el juego: Route 20 con los iniciales escritos, Floccesy Town vacía).

Formato (`EncData`, nombres de swan):

| Offset | Tamaño | Qué |
| --- | --- | --- |
| `+0x00` | 7 × u8 | tasa de cada tipo de encuentro (0 = no hay): hierba, hierba oscura (dobles), hierba que se mueve, surf, surf con ondas, pesca, pesca con ondas |
| `+0x07` | u8 | bits 0-6 banderas; bit 7 = tabla cargada |
| `+0x08` | 12 × 4 | hierba |
| `+0x38` | 12 × 4 | hierba oscura (combates dobles salvajes) |
| `+0x68` | 12 × 4 | hierba que se mueve |
| `+0x98` | 5 × 4 | surf |
| `+0xAC` | 5 × 4 | surf con ondas |
| `+0xC0` | 5 × 4 | pesca |
| `+0xD4` | 5 × 4 | pesca con ondas |

Cada hueco: `u16` especie (bits 0-10) + forma (bits 11-15; 31 = forma al azar), `u8` nivel mínimo, `u8` nivel máximo. La
probabilidad depende del hueco (en la hierba los primeros salen más; para "solo iniciales" se llenan los 12).

Qué implica:
- Se puede hacer en tiempo real: el puente escribe la tabla cuando el jugador está en la zona del evento y durante la ventana
  de fecha/hora. Al cambiar de zona el juego carga la suya (vuelve sola a la normalidad); el Lua tendría que volver a
  escribirla cada vez que se entre a la zona mientras dure el evento.
- No sirve para zonas sin tabla (ciudades sin hierba): si la zona no tiene encuentros, `EncSys_IsActive` pone el bloque a cero
  en cada paso. Tampoco crea hierba: solo cambia qué sale donde ya hay encuentros.
- La hierba oscura usa su propia lista: también se pueden decidir los combates dobles salvajes de una ruta.
- Falta: (1) ~~zona del jugador~~ hecho (abajo); (2) ~~recarga al cambiar de zona~~ confirmado; (3) ~~firmas~~ hecho (`encounters`); (4) ~~tablas de la ROM en `rom.py`~~ hecho; (5) el evento que
  escribe la tabla con zona y ventana de fecha/hora, y la repone al acabar.

### Probabilidad de variocolor (investigación, 30-oct)

- En Gen 5 ser variocolor no se guarda: se calcula con el PID y el ID/ID secreto del entrenador
  (`PML_UtilPIDIsRare`: `(id alto ^ id bajo ^ PID alto ^ PID bajo) < 8`, 1 de cada 8192).
- `FieldEncount_CreateWildPkm` (pokebw2 `src/ov036/enc_pokeset.c`; W2 `0x021A0E00` en el overlay 36, mismo en Volt White
  2) tira el PID `rolls` veces y se queda con el primero variocolor: `rolls = 1`, `+2` con el Amuleto Iris (objeto 632),
  y luego `PassPower_ApplyLuckyShiny`. Solo la usan los encuentros salvajes (también los combates salvajes forzados);
  regalos, huevos (Guardería, con su propia lógica) y entrenadores no pasan por ahí.
- Código (desde `+0x18`): `movs r6,#1` · `bl GameData_GetBag` · `movs r1,#0x9e; lsls r1,#2` (632) · ... ·
  `adds r6,#2` · `mov r0,r6` · `bl PassPower_ApplyLuckyShiny` · `movs r6,#0` (`+0x36`, contador del bucle).
- Parche (`set_shiny_odds`): el byte de `movs r6,#N` = tiradas (hasta 255 ≈ 1/32). Para más, `movs r6,#0` pasa a
  `lsls r0,r0,#s` (tiradas × 2^s); el contador empieza entonces en N en vez de 0, así que hace N·(2^s − 1) tiradas.
  Tiradas para "1 de cada X": `ln(1 − 1/X) / ln(1 − 1/base)`, base = 65536 / umbral de la ROM (8192; 512 en Redux) (1/100 → 82; 1/2 → ~5700; máximo 40.000 ≈ 99 %).
- El overlay del mapa se recarga desde la ROM al salir de cada combate, y en combate esa memoria la ocupa el overlay
  del combate: el Lua mantiene el parche (`P`) y solo escribe si los 32 bytes son exactamente el original o el parche.
- Validado: con 1/2, variocolor al 4.º encuentro; el parche vuelve solo al salir del combate; al quitarlo la memoria
  queda igual que la ROM. Sin pausas al empezar los combates con ~5700 tiradas.

### Direcciones del tracker que aún no usamos (para la fase 5, combate)

Son de `MemoryAddresses.lua` del NDS Ironmon Tracker (W2). Todas son puntero + offset, salvo que se diga otra cosa. **Ninguna está probada por nosotros.**

| Nombre del tracker | Offset | Para qué |
| --- | --- | --- |
| `playerBattleBase` | `0x53610` | Copia del equipo propio durante el combate |
| `enemyBase` | `0x53B70` | Equipo del rival |
| `curHPBattlePlayer` / `HPBattlePlayer` | `0x56530` / `0x5652E` | HP actual / máximo en combate |
| `curBattleLevel` | `0x56538` | Nivel en combate |
| `statStagesStart` | `0x5661C` | Subidas y bajadas de estadísticas |
| `mainBattleDataPtr` | `0x526A8` | Puntero a los datos del combate |
| `itemStartNoBattle` | `0x194F8` | Mochila |
| `badges` | `0x21A24` | Medallas |

---

## 3. Formato de un Pokémon (PK5)

| Tamaño | Dónde |
| --- | --- |
| 136 bytes | Caja |
| 220 bytes | Equipo (136 + 84 de estadísticas de combate) |

**Cifrado** (implementado en `pk5.py`, con 500 pruebas en `test_pk5.py`):
- `0x00` PID (u32) y `0x06` checksum (u16) van sin cifrar.
- `0x08–0x87`: 4 bloques de 32 bytes, desordenados según el PID y cifrados con un generador pseudoaleatorio (PRNG) que usa el checksum como semilla.
- `0x88–0xDB` (solo equipo): cifrado con el mismo PRNG, pero usando el PID como semilla.
- El checksum es la suma de las palabras u16 de `0x08–0x87`. Si no cuadra, el juego lo trata como "huevo malo".

**Offsets ya descifrados** que usamos:

| Offset | Campo |
| --- | --- |
| `0x08` | Especie (nº de Pokédex) |
| `0x0A` | Objeto equipado |
| `0x28` | 4 movimientos (u16 cada uno) |
| `0x30` | 4 PP actuales (u8 cada uno) |
| `0x34` | 4 contadores de Más PP (u8, 0–3) |
| `0x88` | **Estado** (u32) |
| `0x8C` | Nivel |
| `0x8E` | HP actual |
| `0x90` | HP máximo |

**Campos de caja que rellena un regalo** (`gift.py`, offsets de PKHeX `PK5.cs`):

| Offset | Campo | Valor en un regalo |
| --- | --- | --- |
| `0x00` | PID | Aleatorio (decide género, habilidad y variocolor) |
| `0x0C` / `0x0E` | TID / SID | Los del jugador |
| `0x10` | Experiencia | La justa para el nivel, según la curva de la especie |
| `0x14` | Amistad | La base de la especie |
| `0x15` | Habilidad | Bit 16 del PID → habilidad 1 o 2 (u oculta si se pide, con bit 0 de `0x42`) |
| `0x17` | Idioma | El del jugador |
| `0x38` | IVs (5 bits × 6) + huevo + mote | IVs aleatorios, sin huevo, sin mote |
| `0x40` | Género (bits 1-2) y forma | Según el PID y la proporción de la especie |
| `0x41` | Naturaleza | Aleatoria (0–24) |
| `0x48` | Nombre (11 × u16, fin `0xFFFF`) | El de la especie en inglés; ♂/♀ como `0x246D`/`0x246E` |
| `0x5F` | Juego de origen | El del jugador (W2 = 22) |
| `0x68` | Nombre del entrenador | El del jugador |
| `0x7B` | Fecha de encuentro (AA MM DD) | Hoy |
| `0x80` | Lugar de encuentro | 30008 "Distant Land" (Tierra lejana) |
| `0x83` | Poké Ball | 4 (Poké Ball) |
| `0x84` | Nivel de encuentro + género del entrenador (bit 7) | Nivel del regalo |

**⚠ Estado en Gen 5 = número, no bits.** `0` ninguno, `1` parálisis, `2` sueño, `3` congelado, `4` quemado, `5` envenenado.
(Gen 3–4 usaban bits: quemado era `0x10`.) Si se escribe un valor fuera de 0–5, el juego muestra otro ícono (vimos Pokérus)
y la pantalla de datos se queda en negro. Fuente: PKHeX, enum `StatusType` "for Generation 5+".

---

## 4. Protocolo Lua ↔ Python

BizHawk 2.6.2+ antepone `"<longitud> "` a **todo** mensaje, en los dos sentidos.
Si el puente responde sin la longitud, BizHawk se queda esperando en cada consulta y el juego va a tirones.

| Dirección | Mensaje |
| --- | --- |
| Lua → Python | `POLL <modo> <dir. equipo 0x...> <hex equipo> <hex mochila> <cajas> <hex jugador> <código:crc> <combate> <hex misc> <compat> <zona:estación:dir. encuentros:hex encuentros> <bloques>` (`bloques` = bloques del turno que llegaron desde la consulta anterior, `<turno>:<hex>|...`, o `-`; en `combate` van además `Q<i>` (adaptadores), `H` (pausa) y `N` (turno); `cajas` = `<hex bloque 0>|<caja abierta>:<hex>|<otra caja>:<hex>`: la abierta en cada lectura y las demás por turnos, así todas se releen en ~1,3 s; equipo, mochila, cajas, jugador y misc van como `-` en combate; combate va como `-` fuera de él; `compat` = `faint=1,inject=?,...`, ver sección 6; la zona va como `-` en combate y la tabla de encuentros como `-` si no hay) |
| Python → Lua | comandos separados por `;` (vacío = nada que hacer) |
| | `W <dir> <hex>` escribe bytes |
| | `G <dir> <hex_esperado> <hex_nuevo>` escribe solo si la memoria coincide |
| | `J <hex>` inyecta comandos de pantalla en el siguiente turno del combate |
| | `F <dir>` debilita a ese combatiente cuando el juego lo revise (vida 0) |
| | `I <dir> <objeto>` objeto de un combatiente (copia real), con sus efectos registrados en el juego |
| | `R <dir> <n>` lee bytes (herramienta de investigación) |
| | `S <hex>` ejecuta un guion propio en cuanto el personaje quede libre (combates forzados, clima del mapa) |
| | `P <dir> <hex original> <hex nuevo>` parche de código que se mantiene: se reaplica en cada consulta si la memoria vuelve al original (overlay recargado); solo escribe si coincide exactamente con el original o el parche; con nuevo = original se quita. Al cerrar el Lua se restauran todos |
| | `SAVE` / `LOAD` savestate de seguridad (ranura 9) |
| Lua → Python | `RES <ok\|fail> <detalle>` tras cada lote |

**Rendimiento (29-oct).** En cada consulta (cada 10 frames) el juego se detiene hasta que el Lua lee la memoria y el
puente responde; si eso pasa de un frame (16 ms a 100 %, 8 ms a 200 %) se oyen cortes en la música y no se nota la
velocidad 200 %. Medido con una consulta real (~25 KB):
- Puente: 11 ms → 0,4 ms. Casi todo era descifrar los 60 Pokémon de las dos cajas en cada consulta (dos veces: `/state`
  y avisos). Ahora `pk5.decrypt_ro`, `boxes._slot_info` y `happenings._box_mon` guardan el resultado por bytes cifrados
  (`lru_cache`): solo se recalcula lo que cambió. `decrypt_ro` devuelve `bytes` (inmutable) para que nadie modifique la
  copia guardada; para editar se sigue usando `decrypt`.
- Lua: hex con tabla precalculada (sin `string.format` por byte) y, si existe, `memory.read_bytes_as_binary_string` +
  `gsub` con tabla. Al arrancar compara los dos métodos en tres zonas de la RAM (exige bytes ≥ 0x80, por si el juego no
  está cargado) y usa el rápido solo si coinciden; la consola dice cuál usa ("lectura de memoria: ..."). En BizHawk 2.11.1 sale "rápida (binary_string)": los bytes
  altos llegan bien.
- Resultado en el juego: la música suena bien y se nota la velocidad 200 %.
- Si hiciera falta más: mandar mochila y cajas con menos frecuencia (cambian poco); cambia el protocolo.

---

## 5. Scripts

### Lua (en BizHawk: Tools > Lua Console; pueden correr varios a la vez)

| Script | Para qué | Cuándo usarlo |
| --- | --- | --- |
| `lua/connector.lua` | Conecta el juego con el puente: lee el equipo y el modo, y ejecuta las escrituras | Siempre que uses el puente |
| `lua/dump_ram.lua` | Ventanita con un botón **Volcar**: guarda la Main RAM (4 MB) en `dumps/<nombre>.bin` (la ruta se calcula sola desde la carpeta del script) | Para buscar direcciones nuevas |
| `lua/trace_adapter.lua` | Registra frame a frame la comunicación lógica ↔ pantalla del combate en `dumps/trace_adapter.txt` | Investigación del combate |
| `lua/trace_faint.lua` | Registra cada llamada a `CheckFainted` (con `r1` y la vida) en `dumps/trace_faint.txt` | Comprobar avisos de ejecución |
| `lua/watch_ram.lua` | Muestra en pantalla el valor de las direcciones de la lista `WATCH`. Cada entrada puede ser fija o relativa al puntero | Para comprobar una dirección candidata en vivo |

### Python

| Comando | Para qué |
| --- | --- |
| `python bridge.py` | Arranca el puente (API en `:8000`, BizHawk en `:43884`) |
| `python tests/run_all.py` | Ejecuta todas las pruebas (debe terminar en `TODO OK`) |
| `python tests/test_pk5.py` | Prueba el cifrado (debe decir `ok 500`) |
| `python tools/ram_tool.py info dumps\x.bin` | Muestra el puntero, el equipo y sus Pokémon en un volcado |
| `python tools/ram_tool.py boxes dumps\x.bin` | Busca Pokémon de caja válidos fuera del equipo |
| `python tools/ram_tool.py diff --a <volcados A> --b <volcados B>` | Bytes que son iguales dentro de cada grupo y distintos entre grupos |
| `python gift.py <especie> <nivel> --dump dumps\x.bin --out x.pk5` | Genera un `.pk5` para abrirlo en PKHeX (copia el entrenador del volcado) |
| `python tests/test_gift.py` | Pruebas del generador de regalos |
| `python rom.py "ruta.nds"` | Genera `gen5_data.json` desde la ROM (`--info`: solo dice qué juego es) |
| `python tests/test_battle.py` | Pruebas de la lectura y escritura de combate (usa `dumps/combate1.bin` si existe) |
| `python tests/test_rom.py` | Pruebas de la lectura de la ROM (incluye una ROM aleatorizada simulada) |
| `python tests/test_field_script.py` | Pruebas de los guiones propios (combates forzados y clima) |
| `python tools/symbol_offset.py dumps\x.bin symbols.txt` | Desplazamiento de los símbolos de Black 2 (pokebw2) en un volcado |
| `python tools/rom_compare.py original.nds hack.nds` | Si un romhack cambia el código que usa el puente (overlays y arm9) |
| `python tools/merge_redux.py --original W2.nds --redux Redux.nds --base Gen6.nds --salida Mezcla.nds` | Lleva los datos y parches de Redux encima de White2Upgrade (ver "Redux sobre White2Upgrade") |
| `python tools/follower_models.py --rom Mezcla.nds` | Baja los modelos de Pokémon que caminan (-4) para que pisen su sombra; va al final de la cadena (ver "Pokémon que te sigue") |
| `python tools/follower_new.py --rom Mezcla.nds [--hojas carpeta]` | Crea modelos para caminar de las especies que no tienen (códigos `0x1300`+) con las hojas de PokeAvatars; va antes de `follower_models.py` (ver "Pokémon que te sigue") |
| `python tools/follower_shiny.py --rom Mezcla.nds [--hojas carpeta]` | Añade una copia variocolor de cada modelo de Pokémon que camina (códigos `0x3000`+); va después de `follower_models.py` (ver "Pokémon que te sigue") |
| `python tools/sprites_gen5.py descargar sylveon` | Baja a `sprites_showdown/` los sprites de Showdown de una especie (GIF animados y PNG fijos) |
| `docker build -t w2u-build tools/w2u_build` y `docker run ... w2u-build` | Compila White2Upgrade (ver "White2Upgrade compilado") |
| `python tools/sprites_gen5.py lote --rom White2Upgrade.nds --salida Gen6.nds --desde 650 --hasta 721` | Todas las especies del rango con su nombre de la ROM: baja de Showdown lo que falte y escribe la ROM una vez |
| `python tools/sprites_gen5.py convertir --rom W2.nds --salida x.nds --especie 25 --nombre sylveon` | Pone ese sprite en lugar del de la especie 25, en una copia de la ROM: animado, o fijo con `--fijo` (necesita `pip install pillow`) |

### Cómo buscar una dirección nueva (método que usamos para el menú)

1. Con `dump_ram.lua`, haz varios volcados en el estado A (ej. `mapa1..3`) y en el estado B (ej. `menu1..3`), alternando y cambiando algo entre uno y otro (caminar, mover el cursor).
2. Ejecuta `python tools/ram_tool.py diff`. Cuantos más volcados, menos candidatos.
3. Descarta los que vienen en bloques repetidos (suelen ser gráficos) y quédate con los bytes aislados.
4. Ponlos en `watch_ram.lua` y comprueba en vivo en todas las situaciones.
5. Reinicia el juego y comprueba si la dirección es fija o se mueve con el puntero.

---

## 6. Datos del juego y uso por otras personas

### Datos leídos de la ROM (`rom.py`)

Especies, movimientos y nombres **no están fijos en el código**: se leen de la ROM de cada persona
y se guardan en `gen5_data.json`. Así funciona con ROM aleatorizadas y en el idioma de cada juego.

| Dato | Dónde está en la ROM | Para qué |
| --- | --- | --- |
| Datos de cada especie (0x4C bytes) | NARC `a/0/1/6` | Habilidades, curva de exp, género, amistad base, estadísticas |
| Movimientos por nivel | NARC `a/0/1/8` (u16 mov, u16 nivel, fin `0xFFFF`) | Movimientos por defecto de los regalos |
| Datos de movimientos | NARC `a/0/2/1` (byte 5 = PP) | PP al curar y en `set_move` |
| Textos | NARC `a/0/0/2`, archivos 90 (especies), 374 (habilidades), 403 (movimientos), 64 (objetos) | Nombre de los regalos, `/state` |
| Curvas de experiencia | Fórmulas oficiales (no cambian) | Experiencia según nivel |
| Cuántas especies, movimientos, habilidades y objetos | Largo de las tablas de nombres; la última especie va justo antes de "Huevo" / "Huevo Malo" | Límites de `give_pokemon`, `set_move`, ruleta (649 / 559 en el original, más en ROM ampliadas) |
| Umbral de variocolor | arm9 (descomprimido), `PML_UtilPIDIsRare`: `cmp r0, #umbral` | `shiny` en `/state`, regalos variocolor, `set_shiny_odds` (8 = 1/8192 en el original; Redux 128 = 1/512) |

- Con `ROM_PATH` en `config_local.py`, el puente genera `gen5_data.json` al arrancar, y lo rehace si cambias de ROM.
  A mano: `python rom.py "ruta.nds"`.
- El Lua envía el código del cartucho y el CRC de la cabecera. Si `gen5_data.json` es de otra ROM,
  `/state` muestra `data_ok: false` y se rechazan `heal`, `set_move` y `give_pokemon` (los que dependen de esos datos).
- Comprobado con tu ROM sin aleatorizar: da lo mismo que PKHeX. Y con una ROM "aleatorizada" simulada en memoria
  (Bulbasaur con Potencia y curva lenta), el regalo sale con Potencia (`test_rom.py`).

### Juegos soportados

`connector.lua` tiene una tabla `GAMES` por código de cartucho. **Solo escribe en los juegos de la tabla**;
con cualquier otro juego el modo es `unknown`, y en pantalla aparece "juego no soportado".

| Código | Juego | Estado |
| --- | --- | --- |
| `IRDO` | White 2 (USA/Europa, inglés) | ✅ completo |
| `IREO` | Black 2 (USA/Europa, inglés) | ⚪ estado de combate según el tracker (`0x021B5138`); falta la bandera de menú |
| Otros idiomas (`IRDS`, `IRDF`, `IRDD`, `IRDI`, `IRDJ`, `IRDK`...) | White 2 en otros idiomas | ⚪ sin direcciones de combate ni de menú |

Para añadir un juego: buscar su bandera de menú con el método de la sección 5 (volcados + `ram_tool.py diff` + `watch_ram.lua`),
confirmar el estado de combate con `watch_ram.lua`, y añadir la entrada a `GAMES`.
Lo que cuelga del puntero (equipo, mochila, cajas, jugador) es igual en B2 y W2.

### Qué se lee en vivo y qué está fijo

| Se lee del juego de cada persona | Fijo en el código |
| --- | --- |
| Puntero, equipo, mochila, caja 1, datos del jugador (RAM) | Offsets respecto al puntero (iguales en B2/W2) |
| Código del cartucho (RAM) | Tabla `GAMES` con las direcciones de combate y de menú |
| Especies, movimientos, PP y nombres (ROM) | Qué objeto va en qué bolsillo (`bag.py`, no lo cambia el randomizer) |

### Pendiente antes de compartir el proyecto
- [ ] Añadir Black 2 (`IREO`) y, si hace falta, otros idiomas a `GAMES`.
- [x] Configuración personal (tokens, puertos, ruta de la ROM) en `config_local.py`, que no se sube (plantilla: `config_local.example.py`).
- [ ] Guía de instalación paso a paso (Python, `pip install -r requirements.txt`, BizHawk, primer arranque).
- [ ] Regalos en otras cajas, no solo en la caja 1 (ya se leen todas y `move_pokemon` puede moverlos).

### Romhacks y randomizers (pendiente, retomar)

Estado (28-oct): los **datos** se leen de la ROM de cada persona (especies, estadísticas, experiencia, movimientos y PP,
habilidades, objetos, entrenadores) y se comprueba que sean de la ROM que se juega (código + CRC de la cabecera). Las
**direcciones** de memoria y de código (equipo, mochila, combate, `check_fainted`, `reserve_get`, `script_vm`, `item_table`,
`event_list`, `battle_field`...) están fijas en `GAMES` de `connector.lua`.

| Tipo de ROM | Previsión |
| --- | --- |
| Randomizer (Universal Pokemon Randomizer ZX) | Funciona: cambia datos y algo de código que no usamos. **Validado el 28-oct** (UPR ZX 4.6.1), ver abajo. |
| Romhack que solo cambia datos | Igual que el randomizer. **Volt White 2 (Drayano) validado el 28-oct**, ver abajo. |
| Romhack que cambia código (p. ej. Blaze Black 2 / Volt White 2 Redux, más objetos o especies) | Las direcciones pueden moverse (lo dicen las firmas y `rom_compare.py`). Especies, movimientos y umbral de variocolor ya salen de la ROM; los objetos siguen fijos (638 en `pk5.MAX_ITEM`, `battle.MAX_ITEM`, listas de `bag.py`). **Volt White 2 Redux v1.4.1 revisado el 06-nov**, ver abajo. |

**Firmas de código (28-oct):** antes de usar una dirección de código, el Lua comprueba que ahí estén los bytes del juego
original (`sigs` en `GAMES` de `connector.lua`, sacados de la ROM). Así un hack que mueva el código no hace que se escriba a
ciegas (cuelgue o partida corrupta): solo se desactiva esa función.

| Función (`compat`) | Qué comprueba | Cuándo (overlay cargado) | Si no coincide |
| --- | --- | --- | --- |
| `faint` | inicio de `ServerControl_CheckFainted` | en combate (overlay 167) | `battle_set_hp` con vida 0 falla |
| `inject` | inicio de la función del cliente + puntero a `sAdapters` | en combate | se cambia el dato sin actualizar la pantalla (`show` se ignora) |
| `item` | punteros a `sItemEventAddTable` y a la lista de efectos | en combate | `battle_set_item` falla |
| `weather` | puntero a `sField` | en combate | `battle_set_weather` falla |
| `script` | `FieldStatus_GetReserveScript` (arm9) + `FieldScript_AttachOpcodeGuard` (overlay 12) | en el mapa; y otra vez justo al ejecutarse | combates forzados, clima del mapa, teletransporte, regalo al equipo y huevos fallan |
| `encounters` | `GameData_GetEventData` (arm9) + `GetEncountData` (overlay 12) | en el mapa | no se lee (ni se escribirá) la tabla de encuentros |
| `shiny` | inicio de `FieldEncount_CreateWildPkm` (overlay 36; `rom_compare` busca la firma en cualquier overlay que cubra la dirección) | en el mapa | `set_shiny_odds` falla |

- Cada función queda `true` (código esperado), `false` (distinto) o `null` (aún no comprobada: su overlay no ha estado en
  memoria, p. ej. las de combate hasta el primer combate). Un acierto se queda para toda la sesión.
- Se ve en `/state` (`"compat"`), en pantalla ("desactivado (código distinto): ...") y en el error del evento.
- Lo que no es código (equipo, mochila, caja, dinero, estación, estructura de combate) va por el puntero base y los offsets del
  save; las variables de modo (`battle`, `menu`) no se pueden firmar.
- `python tools/rom_compare.py original.nds hack.nds` revisa las mismas firmas en el archivo del hack sin jugar.

Plan:
- [x] **1. Firmas antes de usar cada dirección:** hecho (arriba). Validado con la ROM original y con Volt White 2 (todas
  coinciden, también en la RAM del juego en el mapa).
- [ ] **2. Buscar las direcciones si se movieron:** mismo método que `tools/symbol_offset.py` (buscar la firma en la RAM o en la
  ROM); también sirve para Black 2.
- [x] **3. Probar con un randomizer:** hecho el 28-oct (abajo).
- [x] **5. Redux** (Volt White 2 Redux v1.4.1): revisado sin jugar el 06-nov (abajo); falta probarlo en el juego.

**Herramienta:** `python tools/rom_compare.py <original.nds> <hack.nds>` compara overlays y el arm9 descomprimidos (BLZ), avisa
si alguna zona cambiada toca una dirección que usa `connector.lua` y revisa las firmas en el hack. Si un overlay se carga en otra
dirección o con otro tamaño, lo compara por dirección de memoria en la parte común (antes lo marcaba entero como "revisar").

**Randomizer (28-oct, UPR ZX 4.6.1, cartucho `IRDO`, CRC de cabecera `0b43`):**
- Código: cambia 6 overlays (36, 162, 166, 284, 294, 316) y 8 zonas del arm9, ninguna en el código que usamos; las firmas
  coinciden (en la ROM y en el juego).
- Datos (`rom.py`) comparados con el log del randomizer: las 649 especies (estadísticas, habilidades, nombres), los 22 cambios
  de PP y los movimientos por nivel de las 649 especies, sin diferencias.
- Validado en el juego (partida nueva): `/state` (Mudkip con movimientos aleatorios), regalo al equipo (Pikachu con los
  movimientos y la habilidad del log), combate salvaje forzado, combate contra el entrenador 161 (Bulbasaur con el equipo del
  log), `battle_set_item` y `battle_set_hp` aplicados, huevo con eclosión rápida (eclosionó bien).
- El número de entrenador del log (`#161`) es el mismo que usa `start_trainer_battle`.

**Volt White 2 (28-oct, ROM "Complete", cartucho `IRDO`, CRC de cabecera `0a06`):**
- Código: las 344 overlays idénticas (combate 167, mapa 12 y 36 incluidos); en el arm9, 7 zonas pequeñas (277 bytes), ninguna en
  las direcciones que usamos.
- Datos (`rom.py`): 579 de 649 especies cambiadas (p. ej. Pikachu 65 Atq / 100 Vel, habilidad Pararrayos), 844 entrenadores
  (814 en el original; 384 cambiados), PP de un movimiento, 3 objetos, 11 clases.
- Validado en el juego (partida nueva): `/state` con los datos del hack, combate salvaje forzado + `battle_set_item` (Restos),
  combate contra el entrenador 838 (Vito/Tate, Reuniclus nivel 58; solo existe en el hack), regalo al equipo (Eevee) y huevo con
  eclosión rápida (Larvesta), los dos enviados seguidos.
- Arreglos que salieron: dos guiones seguidos (el Lua rechazaba el segundo; ahora van en cola), el huevo rápido se busca por especie
  y no por hueco, y los símbolos PK/MN del texto (`PKMN Trainer`).
- [x] **4. Límites desde la ROM** (06-nov): especies, movimientos, habilidades y umbral de variocolor. Falta el nº de objetos
  (638 fijo en `pk5.MAX_ITEM`, `battle.MAX_ITEM` y `bag.py`; Redux y White2Upgrade tienen los mismos 639 nombres).

**Volt White 2 Redux (06-nov, v1.4.1 "Complete", cartucho `IRDO`), revisado sin jugar:**
- Código: el overlay 167 (combate) se carga `0x180` bytes antes y crece lo mismo; por dirección solo cambian 101 bytes, todos del
  tipo Hada (`GetTypeEffectiveness`, `GetTypeWeaknesses`, `splitTypeCore`, Conversión 2, Cambio Color). No toca el servidor, los
  adaptadores ni la estructura del combatiente. Otros cambios: overlays 36 (Grutas Ocultas, Neblina), 166 (Recogida), 168, 207/255/265
  (iconos de tipo en estado, cajas y Salón de la Fama); arm9: lista de MT, clases de entrenador, fuente y `PML_UtilPIDIsRare`.
  **Las 13 firmas coinciden** y el indicador de combate (`0x021B5178`, bytes del overlay 167) no cambia.
- Datos (`rom.py`): tipo Hada = 17 en 43 especies (Clefairy Hada, Gardevoir Psíquico/Hada...) y 9 movimientos. Los movimientos
  nuevos **reemplazan** a otros en su número (4 Puño Cometa → Power-Up Punch, 66 Sumisión → Play
  Rough, 296 Bola Neblina → Moonblast...): siguen 560 movimientos y 649 especies. 891 entrenadores.
- Variocolor 1/512 (umbral 128): ya se lee de la ROM (`shiny_threshold`), así que `shiny`, los regalos variocolor y
  `set_shiny_odds` (que ahora va de 2 a 512) lo tienen en cuenta.

### Sprites de especies nuevas (estilo Gen 5, 06-nov, experimental)

Objetivo: sprites para las especies de Gen 6-9 con el aspecto de Gen 5, **animados**, sin código nuevo en el juego.

**Fuente de los dibujos:** Pokémon Showdown (`play.pokemonshowdown.com/sprites/`: `gen5ani*` animados, `gen5*` fijos).
- Son de la comunidad (proyecto de sprites de Smogon): uso no comercial y con crédito, sin licencia libre.
- PokéRogue usa los mismos en las especies que anima, pero Showdown tiene muchos más animados.

| Gen | Frente animado | Fijos (4 vistas) |
| --- | --- | --- |
| 6 | 54 de 72 | todos |
| 7 | 74 de 88 | todos |
| 8 | 64 de 96 | todos |
| 9 | 25 de 120 | todos |

- Los GIF tienen 8-180 fotogramas (mediana ~78) y casi siempre <= 16 colores.
- El variocolor es el mismo dibujo con otra paleta, salvo excepciones (p. ej. Zeraora).

**Cómo dibuja el juego un Pokémon** (MCSS, `src/system/mcss.c` de la decomp). Cada especie tiene 20 archivos en `a/0/0/4`:

| Archivo (frente / espalda) | Qué es |
| --- | --- |
| 0 / 9 | Imagen de 96×96 para pantallas 2D: cuadros de 8×8 en el orden de 4 piezas OAM (64×64, 32×64, 64×32, 32×32) |
| 1, 3 / 10, 12 | Versión hembra (vacío si no hay) |
| 2 / 11 | **Textura del combate**, 256×128 a 4 bits (MCSS reserva `0x4000` bytes por sprite): las piezas del Pokémon |
| 4 / 13 | Celdas (NCER) |
| 5 / 14 | Animación de celdas (NANR, LZ): qué celda muestra cada nodo y cómo se mueve |
| 6 / 15 | Multi-celda (NMCR): los nodos, con su posición y su animación |
| 7 / 16 | Animación de la multi-celda (NMAR) |
| 8 / 17 | `bin` de MCSS (sin comprimir): tamaño y desplazamiento del dibujo, y por celda uno o dos rectángulos de la textura |
| 18, 19 | Paletas normal y variocolor (frente y espalda comparten paleta, 15 colores + transparente) |

- En NCGR los píxeles empiezan en `0x18 + u32@0x2C`.
- Un píxel son `0x100` unidades.
- El punto de apoyo del sprite está en los pies. Si la posición se calcula desde el centro del lienzo, el Pokémon queda en el aire.

**Método** (`tools/sprites_gen5.py`):
- Cada fotograma del GIF se corta en piezas de 8×8 o de 16×16; las distintas van a la textura (caben 512 de 8×8 o 128
  de 16×16).
- Cada posición de la rejilla es un nodo: con 8×8 son 50-70 por sprite, con 16×16 unos 20, como los originales.
- La animación de cada nodo elige qué cuadrito se ve en cada fotograma (elemento de tipo 0, solo índice).
- Si las piezas no caben, se usa uno de cada 2, 3... fotogramas.
- **Tamaño de pieza:** el juego dibuja cada pieza 1 píxel más al fondo que la anterior (`*z -= 0x100` en `mcss.c`).
  Con 50-70 piezas, cuando la cámara se acerca (captura, algunos ataques) las del fondo se desplazan y se ven cortes.
  Con 16×16 son ~20 piezas y se nota menos (probado con Greninja), pero caben menos fotogramas.
- `--bloque auto` (por defecto) usa 16×16 si así conserva al menos la mitad de los fotogramas y 8×8 con todos si no:
  Greninja sale con 16 (10 de 20 fotogramas) y Sylveon con 8 (64 fotogramas; con 16 se quedaría en 16).
- **Los cortes se arreglan de raíz con el parche de profundidad de White2Upgrade** (`patches/mcss_depth.cpp`, ver
  "White2Upgrade compilado"): Yveltal (120 piezas) y Talonflame (112) se ven sin cortes al capturar y con ataques.
  Para que el parche las reconozca, cada pieza lleva `x` = 1/4096 de píxel (`PIECE_MARK`, invisible; en los 649 originales
  el byte bajo de `x` e `y` siempre es 0, comprobado en los 15 828 rectángulos). En ROMs sin el parche siguen los cortes.
- **Modo lote:** `lote --desde 650 --hasta 721` toma los nombres de la ROM (`Flabébé` → `flabebe`), baja lo que falte y
  escribe la ROM una sola vez. Las especies sin GIF quedan fijas; las que no tienen los 4 PNG se saltan.
- Si el GIF no se parece al PNG fijo (otra pose, como Greninja), se centra y se apoya por los pies.
- Si la ROM está recortada (las de `ndstool` miden ~290 MB), se rellena hasta el tamaño de cartucho de la cabecera antes
  de escribir al final.
- La animación de la multi-celda tiene que durar el ciclo entero. Con 4 fotogramas, al repetirse reiniciaba los nodos y el
  sprite se quedaba quieto.

**Espacio en la ROM:**
- El archivo de sprites crece unos 50 KB por especie animada, casi todo por el `bin` sin comprimir.
- En las ROM "NDSi Enhanced" (como W2 USA), en modo DS solo se puede leer hasta el inicio de la zona DSi: `0x92` de la
  cabecera, `0x11800000`. Dentro de ese límite quedan ~5,6 MB.
- melonDS (BizHawk) lo imita a propósito (`src/NDSCart/CartCommon.cpp`: *in DS mode: block the entire DSi area*). Con datos
  detrás, la pantalla se queda en blanco.
- **Solución validada:** el archivo va al final de la ROM, y la cabecera lleva `0x90` y `0x92` hasta el final (512 MB), con
  el `crc16` de cabecera recalculado. Quedan unos 230 MB libres.
- La ROM así ya no sirve en modo DSi; BizHawk usa el modo DS.
- No sirvió quitar la marca DSi (`0x12` = 0) ni mover solo `0x90`.

**Validado en el juego (06-nov, W2 USA en BizHawk):**
- Sylveon de Showdown en lugar de Pikachu: primero fijo y después **animado de frente y de espalda**, en combate y en el resumen.
- Apoyado en el suelo, sin cuelgues, y con los datos al final de la ROM.
- La herramienta produce los mismos bytes que esa prueba.

Pendiente:
- Especies con más de 512 cuadritos (Incineroar, Necrozma), que pierden fotogramas.
- El variocolor en el juego.
- Combates dobles.

**Animaciones largas sin pausas (07-nov, probado en el juego):** si los cuadritos distintos no caben en la textura (512
de 8×8), antes se usaba uno de cada N fotogramas, y cada uno duraba N veces más (Volcanion 1 de 12, Klefki 1 de 9). Se veía
a saltos. Acelerar no sirve, porque faltan los fotogramas intermedios. Ahora `side_files` tiene modos (`--modo` en
`convertir`; `--mitad`, `--tramo`, `--normal` con especies separadas por comas en `lote`):

| Modo | Qué hace | Resultado |
|---|---|---|
| `auto` (por defecto) | `normal`; si saltaría más de `LONG_STEP` = 3 fotogramas, `tramo` | El que se usa |
| `normal` | Todos los fotogramas que quepan (1 de cada N) | Fluido si N ≤ 3 |
| `tramo` | `best_segment`: el tramo seguido más largo que cabe, con paso 1-3 (uno mayor solo si cubre ≥1,5× más tiempo). Si el final enlaza con el inicio (diferencia ≤ la peor entre fotogramas seguidos), bucle normal; si no, ida y vuelta | Fluido; no se ve la animación entera |
| `mitad` | Cada 2×2 → 1 píxel (el color más repetido) y se dibuja al doble con elementos SRT (tipo 1) en la animación | Descartado: se ve pixelado |

Ayudas comunes:
- **Margen del 10 %** (`MERGE_SLACK`, `soft_capacity`): si se pasa un poco, `shrink_tiles` junta los cuadritos más parecidos
  (distancia de Hamming) en vez de quitar fotogramas.
- **Bloque en `auto`:** 16×16 si salta igual o menos fotogramas que con 8×8; si no, 8×8.

Resultado: ninguna especie empeora y ninguna fuera de `tramo` salta más de 2 de cada 3. Klefki hace sus 3 oscilaciones
seguidas en bucle (11,1 s; la parte de las llaves no cabe). Volcanion: 9,3 s de 11,9. Catorce especies pasan a todos sus
fotogramas (Greninja, Froakie, Braixen...).

Probado y descartado: desplazar el fotograma para reutilizar cuadritos (ahorra ~5 %).

### White2Upgrade compilado (06-nov, probado en el juego)

[White2Upgrade](https://github.com/ds-pokemon-hacking/White2Upgrade) (ds-pokemon-hacking, sin licencia: se compila, no se
copia código) amplía W2 USA hasta la especie 721 (Gen 6), con 622 movimientos, 192 habilidades y el tipo Hada. Inyecta
código con PMC/CTRMap: un overlay nuevo (344) y parches que se aplican al cargar cada overlay.

**Compilarlo** (`tools/w2u_build/`): necesita Linux, así que se usa Docker.
- `Dockerfile`: Ubuntu 24.04 con arm-none-eabi-gcc 13.2, Java, PyYAML, libpng y `ndstool` compilado desde su repositorio.
- `build.sh`:
  - vuelve a clonar White2Upgrade desde la copia local, porque en Windows queda con CRLF y `make` falla;
  - usa la ROM como `IRDO.nds`;
  - ejecuta `make tools`, `make base` y `make`;
  - por último pasa `fix_arm9.py`.
- Antes hay que bajar los submódulos con HTTPS (`git -c url."https://github.com/".insteadOf="git@github.com:" submodule
  update --init`) y poner `tools/CTRMap/CTRMap.jar`. Se usó la versión del 2025-05-07, de la época del último commit de
  White2Upgrade.

```
docker build -t w2u-build tools/w2u_build
docker run --rm -v <White2Upgrade>:/src:ro -v <carpeta de la ROM>:/rom:ro \n    -v <repo>/tools/w2u_build/patches:/patches:ro -v <salida>:/out w2u-build
```

La ROM tiene que ser W2 USA (`IRDO`, SHA-256 `3e50aec3…`). Con otro nombre de archivo: `-e ROM_NAME=archivo.nds`.

**El ARM9 queda marcado como comprimido (pantalla en blanco al arrancar).**
- PMC sustituye el ARM9 por uno ya descomprimido (`0x9AC40` bytes), pero conserva `compressed_end = 0x020776CC` en los
  parámetros del módulo.
- Al arrancar, el juego "descomprime" código que no lo está y se queda en blanco.
- `fix_arm9.py` pone ese campo a 0. Volt White 2 lo evita de otra forma: parchea `MIi_UncompressBackward`.
- `rom_compare.py` también acepta ya ARM9 y overlays descomprimidos aunque la cabecera diga lo contrario.

**Puente con White2Upgrade:**
- `rom.py` lee 721 especies, 622 movimientos y 192 habilidades. Ejemplos: Chespin 650, Sylveon 700 (Hada), Volcanion 721;
  Clefairy pasa a Hada.
- Las 13 firmas del Lua coinciden (también en el juego), así que el combate, los guiones, los encuentros y el variocolor
  funcionan igual.
- **Indicador de menú:**
  - PMC sube el inicio de la memoria dinámica (`OS_GetInitArenaLo`: `0x021FD0C0` → `0x022000C0`), y el puntero base pasa de
    `0x02204D04` a `0x02207DE4`.
  - El indicador se mueve lo mismo (`+0x30E0`) y queda en `0x0223E3D5`.
  - El Lua ya no usa una dirección fija, sino puntero base + `0x365F1` (`menu_ptr_off`). En la ROM original da lo mismo que
    antes (comprobado en los 9 volcados) y en White2Upgrade da la dirección correcta (validado con el menú abierto y cerrado).
- Probado en el juego:
  - combate salvaje forzado contra Greninja (658);
  - lectura del combate (tipos Agua/Siniestro);
  - captura y registro en la Pokédex.

**Pokédex del guardado (protección, `tools/w2u_build/patches/dex_limit.cpp`):**
- El bloque de la Pokédex (`0x36`, en el save `0x21400`, `0x4DC` bytes) tiene listas de `0x54` bytes, que dan para 672
  especies. Sin protección, ver o capturar una especie de la 673 a la 721 escribe en la lista de al lado.
- No se puede agrandar el bloque. Los bloques se colocan seguidos, alineados a `0x100` (`gfl/savedata.c`), y a este le sobran
  20 bytes: agrandarlo movería todos los demás.
- **Arreglo:** `PokeDex_RegistPkm`, `addPkmToDex`, `PokeDex_IsSeen` e `IsCaught` empiezan comprobando la especie con
  `PML_PkmIsBadMonsNo`. El parche desvía solo esa llamada (`THUMB_BRANCH_LINK_<función>_<desplazamiento>`, en `+0x6C`,
  `+0x76`, `+0x8` y `+0x8`) para que, ahí, las especies de la 673 en adelante cuenten como no válidas: no se apuntan, y las
  lecturas dicen "no".
- No copia código de la decomp (GPL-3.0). `build.sh` añade los `.cpp` de `patches/` al compilar (`-v .../patches:/patches:ro`).
- Validado en el juego: en RAM la Pokédex está en puntero + `0x920` + `0x21400`, con la marca `0xBEEFCAFE`. Tras ver a
  Sylveon (700), huir, volver a verlo y capturarlo con la pantalla de "registrado", el bloque tiene **0 bytes distintos**.
  Sin el parche, la captura habría escrito en `0x05F` (lista de vistos).
- Efecto: las especies 673-721 se ven, se capturan y se usan, pero la Pokédex no las cuenta.
- Pendiente (opcional): guardarlas de verdad en `ExtraBlock20`, un bloque extra de 200 bytes que el juego nunca usa (llega
  hasta Gen 7). Habría que desviar también la carga y el guardado.

**Profundidad de las piezas (parche, `tools/w2u_build/patches/mcss_depth.cpp`, 07-nov):**
- `MCSS_DrawQuad` deja cada pieza 1 píxel más al fondo que la anterior (`*z -= 0x100`). En los originales (máx. 29 piezas
  que se solapan) eso ordena las partes; en una rejilla de 120 piezas la última queda 120 píxeles atrás y, al acercarse la
  cámara, la perspectiva separa las filas en franjas.
- El parche desvía las 3 llamadas de `MCSSSys_Draw` a `MCSS_DrawQuad` (`+0x7A4`, `+0x7DA`, `+0x836`): llama a la original
  y, si la pieza lleva la marca de `sprites_gen5.py` (byte bajo de `x` = `0x01`), deja la profundidad como estaba.
- White2Upgrade no nombra esas funciones: `patches/mcss.esdb.yml` las añade a `pmc/ESDB.yml` al compilar (direcciones del
  archivo de símbolos de la decomp para W2 USA; el código es idéntico en el ARM9 de PMC). El ARM9 empieza en `0x02004000`.
- Los enganches se aplican al arrancar (el ARM9 del archivo no cambia); el registro de compilación muestra
  `Created automated hook ... THUMB_BRANCH_LINK_MCSSSys_Draw_0x7a4 to ARM9:201a3dc`.
- Validado en el juego: Yveltal y Talonflame sin cortes al capturar y con ataques; Snivy y los salvajes de Gen 5, iguales.

**Límites de White2Upgrade:**
- Las habilidades de Gen 6 solo tienen el nombre.
- Unos 19 movimientos de Gen 6 necesitan código que no tienen.
- Las especies nuevas no tienen grito.
- Sus sprites de Gen 6 son fijos (piezas genéricas) y quedan algo elevados. `sprites_gen5.py lote --desde 650 --hasta 721`
  los sustituye por los de Showdown: 52 animados y 20 fijos (los que no tienen GIF), todos apoyados en el suelo.

### Redux sobre White2Upgrade (08-nov, probado en el juego)

`tools/merge_redux.py` compara Redux v1.4.1 con la W2 USA original y lleva lo que cambió a una ROM de White2Upgrade
(la de los sprites de Gen 6). Resultado: `ModRom/White2Upgrade Redux.nds`. Decisiones del usuario: **Redux manda** en
las especies 1-649, y **sus movimientos de Gen 7-9 se quedan** encima de los viejos (Triple Axel en Triple Kick...).

| Qué | De dónde |
| --- | --- |
| Especies 1-649 (estadísticas, tipos, habilidades, MT, movimientos por nivel) y sus formas | Redux; los campos de formas (`0x1C`-`0x20`), de White2Upgrade (megas). Las formas de la original (685-708) están en 722+ |
| Especies 650-721, megas y formas nuevas, movimientos 560-621 | White2Upgrade |
| Evoluciones | Las de Redux en el formato de 8 huecos de White2Upgrade, más las que van a especies nuevas (Eevee → Sylveon) |
| Movimientos 0-559 | Redux donde cambia (también nombres, descripciones y mensajes, línea por línea); el resto, White2Upgrade |
| Objetos, entrenadores (891), encuentros, guiones, textos de la historia y 21 archivos más | Redux |
| Iconos (`a/0/0/7`) | White2Upgrade, **paletas incluidas** (entradas 0 y 1): con las de Redux los iconos salían con los colores cambiados (visto en el juego el 08-nov) |
| Tipo Hada (overlays 167, 168, 207, 255, 265) | White2Upgrade: Redux lo parchea en las mismas direcciones (los dos vienen del parche de MeroMero) |
| arm9 | Redux desde `0x02005000`: variocolor 1/512, lista de MT, MO que se pueden olvidar, `PML_GenPID`, gráficos de objetos, clases de entrenador. No: el arranque (cada uno lo arregla a su manera) ni su código de iconos Hada (`0x02093BF0`, solo lo llama su overlay 255) |
| Overlays 36 y 166 | Redux: Grutas Ocultas, fenómenos, polvaredas, entrenadores del entorno, Recogida |
| Overlay 167 fuera del tipo Hada | Redux: `0x021C7FF2` (`movs r1, #10` → `#20`) y `0x021DA2F4` (quita una entrada de una tabla de manejadores); sin identificar |

- White2Upgrade guarda el arm9 y los overlays **sin comprimir**, y sus parches se aplican al arrancar: los de Redux se
  escriben en su sitio comprobando que la base tenga ahí lo mismo que la original.
- Moonblast (y otros 9) quedan dos veces: en el número de Redux (296) y en el de White2Upgrade (585).
- Textos: se copian las líneas cifradas tal cual (cada una se cifra sola), sin descifrar.
- El puente reconoce la ROM también por una huella de la ROM entera (`file_crc`): las herramientas no cambian el CRC
  de la cabecera y antes no regeneraba `gen5_data.json`.
- Validado en el juego: partida nueva (Oshawott con Caparazón de Redux), combate contra la Chica 181 de Redux (Azurill
  Normal/Hada), registro, `battle_set_hp`, control del rival con ataques y cambio tras debilitarse.

### Pokémon que te sigue (08-nov, prototipo probado en el juego)

Viabilidad: el juego ya trae casi todo (nombres y argumentos leídos de la decomp pokebw2, sin copiar código):
- **Acompañante de la historia** (`pair_sys`, overlay 12): un personaje que pisa la casilla de detrás del jugador y, si es
  persistente, reaparece al cambiar de mapa. Órdenes de guion `ActorPairSet` (`0x250`: id, índice 0-7, persistente,
  entrenador aliado, guion), `ActorPairEnd` (`0x251`) y `ActorPairSetMoveEnable` (`0x253`, u8).
- **Modelos de Pokémon para caminar** (`OBJ_CODE_POKEMON_*`, desde `0x1000`; Eevee `0x1086`): 620 con sexos y formas.
  Gen 1-4 completas (los de HeartGold, que usan las Grutas Ocultas); de Gen 5 unas 50 de 156; de Gen 6 ninguno.
  `GetPokemonFieldOBJCODE(especie, sexo, forma)` (tabla `ARCID_TPOKE`) da el modelo de cada uno.

Prototipo: evento `set_follower` (`obj_code`; `mode: "off"` lo quita). Guion: `PlayerGetGPos` (`0x68`), z + 1,
`ActorNew` (`0x69`) con el modelo, `ActorPairSet` persistente con índice 7, sin entrenador ni guion, y movimiento activado.
- Con acompañante, `CreateEncountManager` (overlay 36) hace los salvajes **dobles con él de aliado**; sin entrenador aliado
  el juego sacaba un compañero vacío con el aspecto del jugador y se trababa. Parche mantenido por el Lua (`P`) mientras
  hay acompañante: `bl GameData_CheckPairFlag` en `0x021A0B5E` (`c9f7a9fb`) → `movs r0, #0; nop` (`0020c046`).
- Validado: te sigue, sigue tras combates, al cambiar de ruta y al entrar en edificios; hablar con gente, bien; en una
  escena un personaje lo atraviesa sin problemas. Se ve un poco "flotando" (el modelo se dibuja algo más arriba).
- El prototipo sigue disponible con `obj_code` para ROMs sin el parche de abajo.

**Dentro de la ROM (08-nov, validado en el juego): `tools/w2u_build/patches/follower.cpp`.** El primero del
equipo te sigue solo, como en HeartGold, sin depender del puente:
- Al entrar en un mapa (`EventWarpSequence_CreateIn`, overlay 36, justo antes de `TryRespawnFollowActor`) pone el
  modelo del primero del equipo (`GetPokemonFieldOBJCODE`); si es un huevo, no tiene modelo o es enorme, lo quita.
  Si cambias el primero, el modelo cambia al cruzar la siguiente puerta o cambiar de ruta.
- Con un aliado de la historia, el juego cura el equipo tras cada combate, hace dobles los salvajes, no deja usar bici,
  Surf, Cascada, Buceo ni Cuerda Huida, y 16 guiones (Monte Tuerca, Alcantarillas, Ciudad Engobe...) leen la bandera
  `0x966`. Por eso `GameData_CheckPairFlag` (sustituida) y las órdenes `VMStackPushFlag`/`FlagGet` (`0x10`/`0x25`)
  dicen "nadie te sigue" si el que te sigue es el nuestro. Solo lo que lo mueve ve la bandera real
  (`CheckPerStepEvents`, `EventWarpSequence_StartWalkTask`). Ya no hace falta el parche de encuentros del Lua.
- Vuelo, Cuerda Huida, Teletransporte y caer debilitado cambian de mapa sin `EventWarpSequence_CreateIn`: en cada paso
  (`CheckPerStepEvents`), si el nuestro falta en el mapa se crea y `updateFollowerModel` lo pone a tu lado.
- Si la historia pone a un aliado (`ActorPairSet`), el nuestro se quita antes y vuelve en el siguiente mapa;
  `ActorPairEnd` no lo toca.
- Banderas del guardado: `0xA90` lo apaga y `0xA91` dice "es el nuestro". Ningún guion de W2, White2Upgrade ni Redux
  usa `0xA80-0xA9F`; desde `0xAA0` son las diarias. Un Pokémon que te sigue para siempre y sin entrenador se adopta
  como nuestro (partidas guardadas con el prototipo).
- Puente: `set_follower` con `mode: "on"` / `"off"` (sin `obj_code`). Al apagarlo se va enseguida; al encenderlo
  aparece en el siguiente mapa.
- Los modelos de Pokémon se dibujan por encima de su sombra y parecen flotar. `tools/follower_models.py` pone
  `wPosOffsetY` = -4 (tabla `a/0/4/7`, s8 en +14 de cada registro de 28 bytes) en los de tamaño normal: baja el dibujo
  y también la sombra, porque `FldeffShadow_Draw` la coloca con el mismo desplazamiento (`CopyActorPosOffset`). Por eso
  `follower.cpp` engancha esa llamada (`0x21A3D90`, overlay 36) y, en los modelos de Pokémon, deja la sombra a la altura
  de la del entrenador. Probado con Eevee (-4, bien), Pidove (-8, algo bajo) y Pikachu (0, flota). Con el gancho
  (09-nov), Eevee y Pidove pisan su sombra y esta queda al nivel de la del entrenador.
- La cadena se regenera igual que antes (compilar → `sprites_gen5.py lote` → `merge_redux.py` → `follower_new.py` →
  `follower_models.py` → `follower_shiny.py`). Frente a la ROM
  anterior solo cambia `patches/White2Upgrade.dll`.
- Validado (08-nov): sale al cruzar una puerta; salvajes individuales y entrenadores normales, sin curar al terminar;
  bici (se queda algo atrás) y Surf (te sigue por el agua); cambia o desaparece con el primero del equipo al cruzar una
  puerta (Eevee, Pidove; Patrat no tiene modelo); guardar y reiniciar; Vuelo (aparece al primer paso); hablarle no hace
  nada; `set_follower` off (se va al momento) y on.
- Ojo: cada ROM nueva cambia la huella (CRC de cabecera): hay que reiniciar el puente para que regenere sus datos.
- **Variocolor (10-nov):** B2/W2 solo traen la paleta normal de cada modelo (NSBTX de 16 colores en `a/0/4/8`).
  `tools/follower_shiny.py` añade 620 copias con la paleta variocolor, con códigos `0x3000`-`0x326B`, al final de la tabla
  (posiciones `0x3F0`+). Los colores salen de las hojas para caminar de PokeAvatars (`NNN.png`/`NNNs.png`, estilo HGSS,
  1-721 con formas), que tienen los mismos píxeles en normal y variocolor: el 95 % de los colores de los modelos están
  tal cual en la hoja. El resto (algunos de Gen 5, dibujados distinto) salen de las paletas normal y variocolor del
  sprite de combate (`a/0/0/4`, 18 y 19). El juego solo conoce tres rangos de códigos (`GetIndexOfObjID`: personas,
  `0x1000`-`0x126B` y `0x2000`-`0x200A`), así que `follower.cpp` la sustituye añadiendo el de las copias, y usa la copia
  si `PokeParty_IsRare` dice que el primero es variocolor (y la tabla la tiene). Validado (10-nov): Eevee variocolor te sigue en gris.
- **Especies sin modelo (10-nov):** 175 de 1-721 no tienen (TPOKE solo llega a 632 y le faltan muchas de Gen 5).
  `tools/follower_new.py` crea 99 con las hojas de PokeAvatars: cada cuadro de 64x64 es el dibujo HGSS ampliado al doble
  (al reducirlo, los quietos coinciden píxel a píxel con los modelos del juego). Cada modelo es una copia del de Eevee
  (8 texturas de 32x32 de 4 bits: espalda, frente, izquierda y derecha, 2 pasos; el segundo paso de la hoja es el mismo
  dibujo 1 píxel más abajo), con hasta 15 colores de la hoja. Códigos `0x1300`-`0x13FF` en la tabla desde `0x3F0` (256
  sitios), una entrada nueva en TPOKE por especie (cualquier sexo, forma 0). Las copias variocolor (código + `0x2000`)
  van desde `0x4F0`: primero las de los 620 del juego y luego las de los 256 sitios nuevos.
  Validado en el juego (10-nov) con Oshawott y Sylveon.
  Quedan 76 sin modelo: su hoja no está ampliada al doble (dibujos de Gen 5 más grandes, como Patrat o Snivy) o es de
  128x128 por cuadro (legendarios). Necesitan un modelo de 64x64, como los grandes del juego.
- Pendiente: Monte Tuerca con Bianca (aliado de la historia), cambiar el modelo sin esperar a la puerta, modelos de las
  especies que faltan y revisar los modelos grandes (billboardSize 2).

## 7. API

Todas las peticiones llevan la cabecera `x-token: dev-token-cambiame`.

**Postman:** importa `postman/postman_collection.json` (*Import* > archivo). Trae las pruebas en carpetas.
Al crear un evento se guarda su `id` en la variable `eventId`, así que "Ver último evento" y "Cancelar" funcionan sin copiarlo.

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `GET` | `/state` | Modo, juego (`game`), si los datos son de esta ROM (`data_ok`), equipo, mochila (`bag`), caja 1 (`box1`), todas las cajas leídas (`boxes`: número, nombre y Pokémon) y la abierta (`box_current`), combate (`battle`: copia real de cada lado, con `hp_visual`, `conditions` y `stages`) `compat` (qué funciones tienen el código esperado; sección 6), `location` (zona, nombre del lugar y estación) y `encounters` (tabla de encuentros de la zona en RAM: tasa y huecos de cada tipo; `null` en zonas sin encuentros) |
| `POST` | `/events` | Encola un evento. Devuelve su `id` |
| `GET` | `/events` | Lista todos los eventos |
| `GET` | `/events/{id}` | Estado de un evento: `pendiente`, `enviado`, `aplicado`, `fallo` o `cancelado` |
| `DELETE` | `/events/{id}` | Cancela un evento `pendiente` |
| `POST` | `/rollback` | Carga el savestate de la ranura 9 (estado anterior al último evento) |
| `GET` | `/battle/log` | Registro de turnos del combate actual (`current`) y de los 2 anteriores (`previous`). También llega por el WebSocket como `{"kind": "battle_log", "log": ...}` cuando cambia |
| `GET` | `/happenings?since=N` | Avisos de lo que pasó en el juego con `id` mayor que `N` (los últimos 500; ver abajo) |
| `GET` | `/overlay/` | Página de configuración del overlay de OBS (sin token; ver sección 7b) |
| `GET` | `/roulette` | Ruleta: catálogo de efectos, premios guardados, tirada en curso (`spinning`), cola (`queued`) y últimas 10 tiradas (`last`) |
| `PUT` | `/roulette` | Guarda los premios (`{"prizes": [{"effect", "label", "weight" 0-10, "enabled"}]}`) o vuelve a los de fábrica (`{"reset": true}`); 400 si no queda ninguno activo |
| `POST` | `/roulette/spin` | Encola una tirada (`{"source": "quién"}`, opcional; máx. 50 en cola) |
| `GET` | `/overlay-token` | Devuelve el token, solo si la petición viene de esta computadora (127.0.0.1); lo usa el overlay |
| `WS` | `/ws?token=...` | Avisos en vivo del estado (`kind: state`), de los eventos (`kind: event`) de lo que pasa en el juego (`kind: happening`) y de la ruleta (`kind: roulette`, `phase: spin` / `done`) |

**Avisos (`happenings.py`):** el puente compara cada lectura con la anterior y sigue a cada Pokémon por su PID (equipo y
todas las cajas). Cada aviso trae `id`, `time`, `type` y sus datos (`pid`, `species`, `name`, `level`, `where`, `slot`...):

| `type` | Cuándo |
| --- | --- |
| `caught` | Pokémon nuevo cuyo lugar de encuentro es el de la zona actual (captura); trae `ball`, `met_location`, `met_place` |
| `obtained` | Pokémon nuevo que no es una captura aquí: regalo (lugar 30000+), huevo, intercambio, o capturado en otra zona |
| `fainted` / `revived` | Vida de un Pokémon del equipo pasa a 0 / vuelve de 0 (se ve al salir del combate) |
| `level_up`, `evolved`, `hatched` | Sube de nivel (`from_level`), cambia de especie (`from_species`), el huevo eclosiona |
| `moved` | Cambia de sitio: equipo ↔ caja, de una caja a otra o de hueco en una caja (`where` = `party` o `box1`-`box24`; `from`, `from_slot`) |
| `left` | Desaparece del equipo y de todas las cajas: liberado o intercambiado (se espera una vuelta de cajas antes de avisar, por si solo cambió de caja) |
| `badge` | Medalla nueva (`badge` 1-8, `count`) |
| `zone` | Cambio de zona (`zone`, `zone_name`, `from`, `from_name`) |
| `battle_start` / `battle_end` | Empieza / acaba un combate |

Al conectar (o reconectar) el Lua no se avisa de lo que ya había. Si un Pokémon está a medio escribir (checksum mal) esa
lectura no se compara. Cargar un savestate puede dar avisos (lo que cambia respecto a lo anterior).

En combate, cada combatiente de `battle` muestra sus cambios de estadísticas así
(en el juego solo se ven como mensajes en el momento):
```json
"stages": {"atk": 0, "def": -1, "spa": 0, "spd": 0, "spe": 2, "acc": 0, "eva": 0}
```
`0` = sin cambios; `-1` = un nivel menos (ej. tras Malicioso); `+2` = dos niveles más. Van de −6 a +6.

Eventos disponibles:
```json
{"type": "set_status", "target": {"slot": 0}, "status": "burn"}
{"type": "set_hp",     "target": {"slot": 0}, "hp": 5}
{"type": "heal"}                                            // todo el equipo
{"type": "heal",       "target": {"slot": 0}}               // un Pokémon
{"type": "set_item",   "target": {"slot": 0}, "item": 234}  // 0 = quitar
{"type": "set_move",   "target": {"slot": 0}, "move_slot": 2, "move": 55}
{"type": "give_item",  "item": 17, "qty": 5}                // a la mochila
{"type": "take_item",  "item": 4,  "qty": 2}                // sin qty = todas
{"type": "give_pokemon", "species": 1, "level": 5}          // a la caja 1
{"type": "move_pokemon", "target": {"slot": 1}, "destination": "box2"}              // del equipo a la caja 2
{"type": "move_pokemon", "target": {"box": 1, "slot": 0}, "destination": "party"}   // de la caja 1 al equipo
{"type": "move_pokemon", "target": {"box": 1, "slot": 0}, "destination": "box3", "to_slot": 5}
{"type": "remove_pokemon", "target": {"box": 2, "slot": 0}}                          // liberar (también del equipo)
{"type": "battle_set_hp", "target": {"side": "enemy", "slot": 0}, "hp": 1}   // en combate (experimental)
{"type": "battle_set_status", "target": {"side": "enemy", "slot": 0}, "status": "burn"}
{"type": "battle_set_stage", "target": {"side": "player", "slot": 0}, "stat": "atk", "delta": 2}   // o "stage": valor final
{"type": "battle_set_pp", "target": {"side": "enemy", "slot": 0}, "move_slot": 0, "pp": 0}       // sin pp = al máximo
{"type": "battle_set_item", "target": {"side": "enemy", "slot": 0}, "item": 234}                  // 0 = quitar
{"type": "give_pokemon", "species": 495, "level": 10, "shiny": true, "gender": "hembra",
 "item": 234, "moves": [33, 43, 22], "nature": 3, "hidden_ability": false}
```
- `heal`: HP al máximo, sin estado y PP al máximo (respetando los Más PP).
- `set_item`: objetos 0–638 (Gen 5). Ej.: 17 Poción, 155 Baya Aranja, 234 Restos.
- `set_move`: el movimiento entra con sus PP al máximo y sin Más PP. No se permite repetir un movimiento,
  dejar un hueco vacío antes de uno lleno, ni quedarse sin movimientos. Los PP base salen de la ROM (`gen5_data.json`).
- `give_item` / `take_item`: el puente elige el bolsillo según el objeto. Respeta los máximos (999, o 1 en MT).
  Los objetos clave y los no distribuidos en B2/W2 se rechazan. Al quitar, los de detrás suben un puesto.
- `give_pokemon`: crea un Pokémon nuevo en el primer hueco libre de la caja 1 (si está llena, falla).
- `move_pokemon` / `remove_pokemon` (`pc.py`): escriben en la copia del save en RAM con guardas (si algo cambió, no se escribe
  nada), solo en el mapa con los menús cerrados. Del equipo a una caja se copian los 136 primeros bytes cifrados (ya son un
  Pokémon de caja válido); de una caja al equipo se calculan nivel, estadísticas y vida como el juego (comprobado con los 6 del
  equipo; `hp` opcional, p. ej. 0 = debilitado). El equipo se compacta y nunca se queda sin un Pokémon que pueda luchar.
  Destino `box1`-`box24` en el primer hueco libre o en `to_slot`.
  Por defecto: nivel 5, los últimos 4 movimientos que aprende hasta su nivel, IVs/naturaleza/género aleatorios, sin variocolor.
  El entrenador es el jugador (leído de su bloque de datos), así que le obedece.
  Datos de especies, experiencia y movimientos en `gen5_data.json`, generado desde la ROM (sección 6).
- `battle_set_hp` (experimental, fase 5): cambia la vida de un combatiente en las dos copias. `side`: `enemy` o `player`;
  `slot`: posición en la tabla (0 = el activo). Siempre espera a que haya combate. La barra se anima con los gráficos del juego
  cuando se reproduce el turno (si se envía con el menú abierto, al empezar el turno siguiente). `"show": false` para no animarla.
  Vida 0: se debilita como en el juego (mensaje, animación, experiencia, cambio de Pokémon o derrota) en cuanto el juego lo
  revisa (tras el primer golpe en que participe o al final del turno). Detalle en "Debilitar con vida 0" (sección 2).
- `battle_set_status` (experimental): deja solo esa condición principal (`none`, `paralysis`, `sleep`, `freeze`, `burn`,
  `poison`, `toxic`) en las dos copias, con sus contadores a 0. El ícono y el color se actualizan igual que la barra (al reproducirse
  el turno). `sleep` acepta `turns` (1-6, por defecto 3): turnos sin atacar; despierta y ataca en el siguiente. `toxic` = envenenamiento grave
  (daño 1/16, 2/16, 3/16… del máximo). `/state` los muestra como `sleep (quedan n turnos)` y `toxic (turno n)`.
- `battle_set_stage` (experimental): cambia una estadística en combate (`atk`, `def`, `spa`, `spd`, `spe`, `acc`, `eva`).
  `stage` fija el valor final (−6..+6); `delta` suma o resta niveles. En pantalla no se ve (Gen 5 no lo muestra).
- `battle_set_item` (experimental): objeto del combatiente (`item`, 0 = quitar). Sus efectos funcionan desde ese momento, como si
  lo hubiera cambiado un movimiento. `/state` muestra `item` de cada combatiente. Si llega justo al empezar el combate, espera a
  que estén los combatientes.
- `battle_set_pp` (experimental): PP de un movimiento (`move_slot` 0–3); sin `pp`, al máximo. Escribe también la copia de respaldo.
  Los PP sí se ven al momento en el menú de Luchar. Si el rival ya había elegido ese movimiento para el turno, lo intenta
  igual y sale el mensaje de que no le quedan PP (sin efecto), como en el juego normal.
- `rival_control` (experimental): `"mode": "pause"` hace que, en cada elección del rival (acción o cambio), el turno espere
  hasta que llegue un `rival_action` o pasen `seconds` (por defecto 30; 0 = 10 minutos); luego sigue con lo que eligió la IA.
  `"mode": "off"` la quita. Sirve en cualquier modo y se mantiene entre combates (también en los salvajes: hay que quitarla).
- `rival_action` (experimental): cambia lo que eligió el rival antes de que se ejecute. `"action": "switch"` con `to_slot` (hueco
  de su equipo en el orden del combate: el 0 es el que está en el campo) o `"action": "move"` con `move_slot` (0-3).
  `target.slot` = qué rival (0; en dobles 1; 6 = segundo entrenador). Espera a que la IA haya elegido; un cambio pedido cuando le
  toca sacar a alguien tras debilitarse se aplica ahí, y el ataque espera a la próxima vez que elija acción. Falla con el motivo si
  no se puede (atrapado, encadenado, sin PP, Otra vez, Mofa...). Con la pausa activa la suelta al aplicarse (salvo
  `"keep_paused": true`). `/state` muestra en `battle.rival` qué pide el servidor, si el jugador y el rival ya eligieron, qué eligió
  el rival y si está en pausa (¡no lo enseñes en el overlay del jugador!).
- `battle_set_weather` (experimental): clima del combate (`none`, `sun`, `rain`, `sandstorm`, `hail`), con `turns` opcional
  (sin `turns` no se acaba). Se anima con el mensaje del juego al reproducirse el turno; con `none` sale el de fin del clima.
  `/state` lo muestra en `battle.weather`.
- `give_item` / `take_item` funcionan también **en combate** (con `"when": "cualquiera"` o `"en_combate"`): la mochila del
  combate es la misma que la del mapa. Validado: Master Ball dada en pleno combate y usada para capturar.
- `/state`: cada Pokémon (equipo y combate) muestra también `shiny`, `gender`, `form`, `ability` y `hidden_ability`.
- `give_money` / `take_money` / `set_money`: dinero (`qty`). No baja de 0 ni pasa de 9.999.999. Con el personaje libre.
  `/state` muestra `money` y `badges` (número de medallas).
- `set_shiny_odds`: probabilidad de variocolor en los encuentros salvajes (`odds`: 1 de cada N, de 2 a 8192, o a 512 en Redux; sin `odds`
  = normal). Sale del todo con 1/8192 de serie; queda puesto hasta quitarlo (o cerrar el Lua). Si el Lua se reconecta,
  el puente lo vuelve a mandar. Solo White 2 (`IRDO`) por ahora.
- `give_wonder_card`: mete una Tarjeta Misteriosa en el álbum; el regalo lo entrega el **repartidor** del Centro Pokémon
  (hay que salir y volver a entrar: el guion `global_10395` lo pone o lo quita al cargar el mapa, según haya tarjetas sin
  entregar). Tres formas: `pgf` = tarjeta oficial de la carpeta `wondercards/` (nombre sin ruta, ej. `"genesect"`; las
  de la galería de Project Pokémon, que no se suben a git); `species` (+ `level`, `moves`, `shiny`, `item` = objeto que
  lleva, `ot`, `title`) = tarjeta de Pokémon hecha aquí con los valores de las oficiales (Gloria Ball, naturaleza, género
  e IV al azar, "Un lugar encantador"); solo `item` (+ `title`) = tarjeta de objeto. Las propias reciben un ID libre de
  1500-2045 (o `card_id`) y se marca como recibido, como hace el juego. Va al primer hueco vacío o al de una tarjeta ya
  entregada; falla si las 12 están sin recoger o la misma tarjeta ya está. Por dentro: primero lee el álbum (`R`) y
  luego escribe con guardas (`G`), así que si el juego lo tocó entre medias no se escribe nada. El juego no comprueba el
  checksum al leerlo y lo recalcula al marcar la tarjeta como entregada. `tools/wonder_card.py` hace lo mismo desde la
  consola (y `list` muestra el álbum).
- `set_season`: estación del mapa (`season`: `spring`/`summer`/`autumn`/`winter`, en español, o 0-3; `real` vuelve a la
  del reloj). Se ve al cambiar de mapa (salir de un edificio). Al cambiar de mapa el juego pone la estación del mes
  (`GameData_GetSeasons`) salvo con la sincronización forzada activa (la de jugar conectado), que el evento enciende.
  La marca no se guarda: al cargar la partida vuelve la estación del reloj.
- `teleport`: `zone` = ciudad (`aspertia`, `virbank`, `castelia`, `nimbasa`, `driftveil`, `mistralton`, `icirrus`, `opelucid`,
  `lacunosa`, `undella`, `humilau`, `nacrene`, `striaton`, `accumula`, `nuvema`, `pokemon_league`, `victory_road`, `black_city`,
  `white_forest`) o número de zona: al punto de aterrizaje de Vuelo (zonas de `RESPAWN_ZONE_INFO`, `src/ov012/respawn_zone.c`).
  Con `x` y `z`, a esa casilla (cuidado con las paredes). Ir a una ciudad aún no visitada puede saltarse eventos de la historia.
- `give_pokemon` con `"destination": "party"`: lo crea el juego (entrenador, lugar de captura actual, Pokédex) y lo mete en el
  equipo; si está lleno, en la primera caja con sitio (de cualquier caja). Opciones: `level`, `form`, `gender`, `hidden_ability`,
  `item`, `ball`, `shiny`. Movimientos y naturaleza los decide el juego (para elegirlos, el método de la caja 1).
- `give_egg`: huevo de `species` (y `form`) al equipo, con la orden del juego (`s010F_PokePartyAddEgg`): tu nombre de entrenador,
  los ciclos normales para eclosionar y el origen de un huevo. Solo al equipo: con 6 Pokémon da error. `/state` muestra `egg` y
  `egg_cycles` (ciclos que faltan, 256 pasos cada uno). Con `hatch_cycles` (0-255) el puente le pone esos ciclos en cuanto aparece
  en el equipo (0 = eclosiona en menos de 256 pasos). La orden del juego para la amistad (`0x00FD`) se salta los huevos, por eso se
  escribe desde fuera (amistad, `0x14` del PK5).
- `set_egg_cycles`: lo mismo para un huevo que ya está en el equipo (`target.slot`, `hatch_cycles`).
- `start_wild_battle`: combate salvaje contra `species` de nivel `level` (por defecto 5), en cualquier sitio del mapa (no hace falta
  hierba). Espera a que el personaje esté libre. Opciones (orden `0x0297` y sus flags, `EventWildBattleCall_CreateStatic`):
  `form`, `shiny` (flag `0x02`), `gender` (`0x20` macho / `0x40` hembra), `hidden_ability` (`0x08`), `no_flee` (`0x01`).
  El objeto que lleva no se puede elegir así.
- `start_trainer_battle`: combate contra el entrenador `trainer` (1-813 en W2; la lista sale de la ROM: `a/0/9/1`), aunque ya lo
  hayas vencido. Si pierdes, el juego hace lo de siempre (volver al Centro Pokémon). El tipo de combate lo decide el estilo del
  entrenador (uno doble lucha en doble, como el 21). Con `trainer2` (y `trainer` individual) es un **combate doble contra los
  dos a la vez**, como cuando te ven dos juntos; sus Pokémon salen en `/state` como `enemy` 0-5 (el primero) y 6-11 (el
  segundo; el 6 es el que está en el campo), y las órdenes de combate usan esos `slot`. Falla si el equipo no tiene bastantes
  Pokémon en condiciones (2 para un doble, 3 para un triple o rotatorio). No hay combate salvaje doble por guion.
- `set_weather`: clima del mapa, por nombre o número: `none` 0, `snow` 1, `rain` 2, `sandstorm` 3 (arena en combate), `hail` 4
  (granizo en combate), `blizzard` 5 (granizo), `heavy_rain` 6 (lluvia), `rain_streaks` 7 (lluvia), `diamond_dust` 8, `fog` 9,
  `overcast` 10, `light_fog` 11, `heavy_sandstorm` 12 (arena), `overcast2` 13, `zone` = el de la ruta. Los que no dicen nada
  no dan clima en combate. `"persist": true` lo repone al volver de cada combate; `zone` lo quita.
- Si un evento escribe en varios slots, el Lua revisa todos antes de escribir: o se aplican todos o ninguno.
`when`: `"en_mapa"` (por defecto), `"en_combate"` (hoy siempre falla: fase 5) o `"cualquiera"`.

Protecciones: no se escribe si el modo es `unknown`, si el checksum del slot no es válido en ese momento,
o si la memoria cambió entre la lectura y la escritura.

## 7b. Overlay de OBS (`overlay/`)

Pensado para quien no programa: no hay que instalar nada más ni editar archivos.

1. Abrir el puente (`python bridge.py`). Al arrancar muestra la dirección del overlay.
2. Abrir `http://localhost:8000/overlay/` en el navegador. Si falta el token o no sirve, la página lo pide a
   `/overlay-token` (solo responde a esta misma computadora) y lo pone en la dirección.
3. Elegir qué mostrar (atajos: todo junto, solo el equipo, solo avisos, lugar y medallas), cómo (fila, columna o 3×2;
   mote o especie; tema oscuro, claro o sin fondo; tamaño; segundos de cada aviso) y mirar la vista previa. Con "datos de
   ejemplo" se configura sin el juego abierto. Las opciones se recuerdan en el navegador.
4. Copiar la dirección y en OBS: *Fuentes* > *+* > *Navegador* > pegar, con el ancho y alto que sugiere la página.

Archivos:
- `index.html`: página de configuración; muestra si el puente y el juego están conectados.
- `view.html` + `view.css`: lo que va en OBS (fondo transparente). Opciones por la URL: `show=place,badges,team,feed`,
  `layout=row|column|grid`, `names=nickname|species`, `theme=dark|light|clear`, `animated`, `empty`, `size`, `feedtime`,
  `demo=1`.
- `common.js`: conexión por WebSocket (se reconecta sola), datos de ejemplo, textos de los avisos en español y sprites.

Notas:
- Los sprites (Gen 5 animados, variocolor incluido) se cargan de PokeAPI/sprites en GitHub: hace falta internet.
- En combate el equipo no se vuelve a pintar (se queda el último), porque el puente no relee el equipo en combate.
- Necesita la librería `websockets` (está en `requirements.txt`); sin ella uvicorn rechaza el WebSocket.
- El puente corta el WebSocket al cerrarse (`timeout_graceful_shutdown=1`); si no, Ctrl+C se quedaba en "Shutting down".
- Cada cliente del WebSocket tiene su propia cola y tarea de envío (`WsClient` en `bridge.py`): `broadcast` solo encola y
  vuelve. Antes se esperaba a cada navegador antes de contestar al Lua, y una pestaña que dejaba de leer (DevTools en pausa,
  pestaña congelada) trababa BizHawk (`socketServerResponse` espera la respuesta). Del estado solo se manda el último;
  avisos y eventos van todos y en orden. Un cliente que tarda más de 10 s en recibir o acumula 200 avisos se desconecta (la
  página se reconecta sola). Prueba: con un cliente que no lee, la versión anterior se trababa en el 8.º POLL; la nueva
  responde todos.
- CSS: `[hidden] { display: none !important; }`, porque un `display` propio gana al atributo `hidden` (el aviso "esperando
  al puente" no se ocultaba).
- Mejoras visuales pendientes (no urgentes): pulir el diseño de las tarjetas y avisos.

### Ruleta (`ruleta.html`, `ruleta-view.html`, `effects.py`, `roulette.py`)

- **Configurar:** pestaña *Ruleta* de la página del overlay. Cada premio tiene casilla, nombre editable y barra de peso
  (0-10) con el % real; se guarda solo en `roulette.json` (no se sube a git). "Volver a los de fábrica" lo restablece.
  Botón "Girar ahora", historial de tiradas, vista previa (gira sola cada 12 s sin aplicar nada) y dirección para OBS
  (tamaño de la rueda `size` y segundos del resultado `hold`; también `always=1` para no esconderla).
- **Girar:** `POST /roulette/spin` (botón, Postman y luego Twitch). El puente elige el premio por peso, manda
  `kind: roulette, phase: spin` (segmentos, ganador, segundos) para que la rueda gire, espera `SPIN_SECONDS` (7 s), aplica
  el efecto (encola eventos normales con origen "ruleta (quién)") y manda `phase: done` con el texto del resultado.
  Las tiradas van de una en una, con 4 s entre ellas.
- **Rueda:** invisible en OBS hasta que alguien gira; cada segmento mide según su probabilidad.
- **Efectos (`effects.py`):** cada uno da un texto y una lista de eventos según el estado del juego al aplicarse
  (objetivos al azar: nunca huevos ni debilitados; "Debilitar a uno" nunca deja el equipo sin nadie en pie). De fábrica:
  nada, curar, Poké/Ultra/Master Ball, caramelo raro, revivir, ±dinero, Pokémon al azar (o variocolor) a la caja 1 del
  nivel medio, parálisis/sueño a uno, veneno a todos, debilitar a uno, combate salvaje (+2 niveles), lluvia, nieve y
  viaje a una ciudad y "Hora variocolor" (1/50 durante 10 min). "Regalo misterioso" (03-nov): Pokémon al azar del
  nivel medio como Tarjeta Misteriosa, que entrega el repartidor; si ya tienes `roulette.json`, actívalo en la página. Desactivados de fábrica: Master Ball, variocolor,
  debilitar y viaje. Un efecto puede devolver eventos con `after` (segundos): se aplican después y otro del mismo tipo
  reinicia la espera (`schedule_event`), así dos horas variocolor seguidas no se cortan antes.
- Pendiente: acomodar opciones y diseño (MVP validado).
- La carpeta no depende de Python: se puede mover a otro proyecto cambiando solo de dónde se sirve.

---

## 8. Bitácora

| Fecha | Qué pasó |
| --- | --- |
| 25-oct | Direcciones del equipo y del combate sacadas del NDS Ironmon Tracker. Se descubre que en W2 dependen de un puntero. |
| 25-oct | **Error:** las respuestas a BizHawk no llevaban la longitud, y el juego iba a tirones. Corregido. |
| 25-oct | **Error:** `from_hex` en Lua numeraba desde 0, así que BizHawk habría escrito los bytes desordenados. Corregido antes de usarlo. |
| 25-oct | Lectura del equipo validada (Oshawott y Patrat, `valid: true`). |
| 25-oct | **Error:** el estado se escribía con bits de Gen 4 (quemado = `0x10`). El juego mostró Pokérus y la pantalla de datos se quedó en negro. Se pasó al enum de Gen 5 (quemado = `4`) y se recuperó la partida con rollback. |
| 25-oct | `set_status` y `set_hp` validados en el juego, también en combate (la quemadura hace daño). |
| 25-oct | Añadidos `DELETE /events/{id}` y `GET /events`. |
| 25-oct | Caja 1 encontrada en puntero + `0xD20`. |
| 26-oct | Bandera de control libre encontrada en `0x0223B2F5` y conectada al modo `menu`. |
| 26-oct | Colección de Postman (`postman_collection.json`). |
| 26-oct | Fase B: eventos `heal`, `set_item` y `set_move`; tabla de PP de Gen 5 en `move_pp.py`. Probados con BizHawk simulado. |
| 26-oct | Fase B validada en el juego: curar, objetos y movimientos. Guardado en el juego + reinicio: los cambios se conservan. |
| 26-oct | Mochila ubicada con los volcados de ayer (el `itemStartNoBattle` del tracker es el bolsillo de medicinas). Eventos `give_item` / `take_item`. El puente ahora lee cada mensaje de BizHawk por su longitud. Probado con BizHawk simulado sobre la RAM real. |
| 27-oct | Mochila validada en el juego: dar y quitar objetos, compactación al quitar el primero, lanzar una Poké Ball dada (17 → 16), y guardar + reiniciar. |
| 27-oct | Regalos: `gift.py` + evento `give_pokemon`. Datos de PKHeX en `gen5_data.json`. Descubierto que la RAM es el save desplazado `0x920`; bloque del jugador en puntero + `0x19D20`. Probado con BizHawk simulado. |
| 27-oct | Regalos validados en el juego: niveles, variocolor, género, objetos, movimientos, habilidad oculta, combate, obediencia y guardar + reiniciar. Los 2 fallos esperados, correctos. |
| 27-oct | Datos del juego leídos de la ROM (`rom.py`): especies, movimientos por nivel, PP y nombres; iguales a PKHeX con la ROM original. Detección del juego por código de cartucho (tabla `GAMES`) y comprobación de que los datos son de esa ROM. `requirements.txt`. |
| 27-oct | Fase 5: lectura del combate validada (vida, PP, cambios de estadísticas). Escribir solo la copia visual dejó un combate incoherente (Patrat con barra vacía pero vivo). Con un volcado se encontró la copia real (tabla en puntero + `0x52790`). Escribiendo las dos, el Patrat con 1 de vida se debilitó con un Placaje y el combate terminó bien. |
| 27-oct | Estado en combate descifrado: no es un número en `+0x20`, sino una lista de condiciones desde `+0x1C` (la parálisis es la entrada 1). Quemadura escrita al rival: hace su daño al final del turno. El ícono y el color de pantalla no cambian (parte visual). |
| 27-oct | Repositorio git: archivos ordenados en carpetas (`lua/`, `tools/`, `tests/`, `docs/`, `postman/`), configuración personal en `config_local.py`, `.gitignore`, `tests/run_all.py`. |
| 27-oct | `/state` muestra los cambios de estadísticas en combate de forma legible (`stages`: −6..+6, 0 = sin cambios). Nuevo `tests/test_battle.py`. |
| 27-oct | Opción B de la fase 5: eventos `battle_set_stage` y `battle_set_pp` (dos copias; los PP también en la copia de respaldo del movimiento). Carpeta 9 de Postman. |
| 27-oct | Opción B validada en el juego: estadísticas (Ataque +2 y Defensa del rival −2 → lo debilita de un golpe) y PP (al máximo se ve al instante; a 0 el rival cambia de movimiento y, sin ninguno, usa Forcejeo). |
| 27-oct | Opción A: herramientas `debug_peek`/`debug_poke` (solo con `DEBUG_WRITES`). Encontrados los indicadores de vida de la pantalla de arriba; la barra solo se redibuja durante la animación de daño del combate, no al cambiar los datos ni al volver de otras pantallas. |
| 27-oct | Investigación opción 3: gracias a showdown-bw2 y la decompilación pokebw2 se ubicaron en White 2 el adaptador, el cliente, el servidor y la cola de comandos del cliente (+0x40 respecto a Black 2). Formato de comandos confirmado con bloques reales. Veredicto: viable insertando en la cola del cliente durante la reproducción de un turno. |
| 27-oct | **Opción 3 funcionando:** comandos de pantalla inyectados en la cola del cliente. `battle_set_hp` y `battle_set_status` ahora animan la barra y ponen el ícono con los gráficos del juego. Validado: barra + ícono de quemado + quemadura que lo debilita, con experiencia y subida de nivel normales. |
| 27-oct | Pruebas en tu propio Pokémon: vida a 5, veneno y curar funcionan con su animación. **Vida 0 directa deja el combate en bucle** (el rival ataca y falla): primero se puso mínimo 1, luego se resolvió con `F` (sección 2, "Debilitar con vida 0"). El puente rechaza campos desconocidos (un `side` fuera de `target` se aplicaba al rival sin avisar). |
| 27-oct | Causa del bucle con vida 0 encontrada en la decompilación (`CheckFainted` salta a los que ya tienen 0). BizHawk sí avisa al ejecutarse una dirección (`trace_faint.lua`: 10 llamadas en un turno). Nuevo comando `F`: el Lua pone la vida a 0 justo cuando el juego revisa a ese Pokémon. |
| 27-oct | Pruebas visuales completas: congelado, quitar estado y evento durante las animaciones (la barra bajó a mitad de Leer). Sueño y envenenamiento grave implementados con el formato de `battle_condition.c` (pokebw2), pendientes de validar en el juego. |
| 27-oct | Sueño y envenenamiento grave validados en el juego (combate contra entrenadora). El contador del sueño incluye el turno en que despierta: `turns` ahora significa turnos sin atacar. |
| 27-oct | Fase 5 validada completa: entrenador con varios Pokémon (banco incluido) y combate doble. |
| 27-oct | **Combates forzados:** guion reservado (`FieldStatus` + `0x12`) + nuestros bytes encima del guion cargado (avisos de ejecución). Combate salvaje fuera de la hierba y contra entrenador validados. Clima del mapa (se pierde al volver del combate; opción `persist`) y clima del combate (`sField` + `WEATHER_START`) validados. Desplazamientos W2/B2: `+0x2C` código principal, `+0x40` overlays. |
| 27-oct | Dinero en el bloque Misc (puntero + `0x21A20`, no en MyStatus). `give_money`/`take_money`/`set_money` validados; persiste al guardar. La variable del buzón queda descartada: los guiones propios la sustituyen. |
| 27-oct | Climas del mapa 1-13 identificados; en combate 3 = granizo y 4 = arena (corregido). Perder un combate forzado colgaba el juego: el guion ahora comprueba la victoria y llama a la derrota como los del juego. Validado con un entrenador doble. |
| 27-oct | Teletransporte (`0x028A` volar a una zona; tabla de destinos de Vuelo) y regalo al equipo con la orden del juego (`0x010E`, con caída a la caja `0x0123`) validados. El parámetro sin nombre de `BoxPkmCreateParams` (`param1C`) es el variocolor. |
| 27-oct | Combate salvaje con opciones (forma, variocolor `0x02`, sexo, oculta, sin huida) validado. Objetos en combate: la mochila es la misma, el Lua la manda también en combate. `/state` muestra variocolor, sexo, forma y habilidad. |
| 28-oct | Derrota en combate salvaje forzado validada (al Centro Pokémon, sin error). Objetos en combate validados con el Lua recargado. |
| 28-oct | Objeto en combate (`battle_set_item`, orden `I` del Lua): además de `+0x12`, registra sus efectos en la lista del combate como hace Truco. Validado (quitar Restos, dar Baya Zidra). Los eventos de combate esperan a que existan los combatientes y los datos del combate anterior se borran al salir. |
| 28-oct | Huevos (`give_egg`, orden `0x010F` del juego) validados: eclosión normal caminando. `/state` marca los huevos. |
| 28-oct | Eclosión rápida (`hatch_cycles`, `set_egg_cycles`) validada. |
| 28-oct | Análisis de compatibilidad con romhacks y randomizers; plan anotado en la sección 6 (firmas de código, búsqueda de direcciones, prueba con UPR ZX, límites desde la ROM). |
| 28-oct | **Volt White 2 validado:** mismo código que White 2 (`tools/rom_compare.py`), datos leídos con `rom.py`. Guiones en cola en el Lua; huevo rápido por especie; texto PK/MN. |
| 28-oct | Estación (`set_season`) validada: escribir solo el byte no basta (al cambiar de mapa vuelve la del reloj); con la sincronización forzada encendida se vio nieve en octubre. |
| 28-oct | Firmas de código: el Lua comprueba los bytes de cada función antes de usarla y desactiva solo la que no coincida (`compat` en `/state`); `rom_compare.py` descomprime los overlays y revisa las firmas en el hack. |
| 28-oct | Combate doble contra dos entrenadores (`trainer2`): el segundo rival está en el cliente 3 de la tabla de combate (`+0x54`), que el Lua ahora envía (también el compañero, cliente 2); salen como `enemy` 6-11. Validado (quemadura al Mudkip del segundo rival). |
| 28-oct | **Randomizer (UPR ZX) validado:** datos idénticos al log del randomizer y pruebas en el juego (regalo, combates forzados, objeto en combate, huevo). `rom_compare.py` ahora mira las zonas cambiadas dentro de cada overlay (antes avisaba por cualquier cambio en el overlay 36). |
| 28-oct | Investigación de encuentros por fecha: la tabla de encuentros de la zona está en RAM (`*(GameData + 0x158) + 0x38`, 0xE8 bytes) y se lee en cada encuentro; comprobada con los volcados de la Ruta 19 contra `a/1/2/7` y **validada en el juego** (Ruta 20 solo iniciales: salieron Mudkip, Charmander y Chikorita; dura tras los combates). Ideas futuras documentadas (sección 10). |
| 29-oct | Zona actual (`GameData + 0x114`) y tabla de encuentros en `/state` (`location`, `encounters`), firma `encounters`; zonas, nombres y tablas de la ROM en `rom.py`. Validado: la tabla escrita vuelve a la original al salir y entrar de la zona. |
| 29-oct | Avisos de lo que pasa en el juego (`happenings.py`, `GET /happenings`, `kind: happening` en el WebSocket). Validado en la Ruta 20: inicio y fin del combate, Purrloin del equipo debilitado, Purrloin capturado (`caught`, a la caja 1, lugar Route 20) y los dos cambios de zona. El lugar de encuentro del PK5 (`0x80`) usa la misma lista que los nombres de zona (texto 109). |
| 29-oct | Cajas 2-24 (`boxes.py`: bloque 0 con nombres, caja abierta y nº de cajas; el Lua manda la abierta y otra por turnos) y `move_pokemon` / `remove_pokemon` (`pc.py`). Validado: equipo → caja 2 (Patrat; el equipo se ve bien con 5), caja 1 → equipo (Eevee nivel 20, 53/53 PS, ficha correcta), liberar de la caja 2; avisos `moved` y `left`. Guardar en el juego y reiniciar: carga sin error, Eevee sigue en el equipo y las cajas vacías. |
| 29-oct | Overlay de OBS (`overlay/`, servido por el puente en `/overlay/`): página de configuración con atajos y vista previa, vista con lugar, medallas, equipo (sprites, PS, estado) y avisos animados. El token se rellena solo desde esta computadora (`/overlay-token`). Arreglos: faltaba `websockets` (WebSocket rechazado), Ctrl+C no cerraba el puente con el overlay abierto, un overlay que dejaba de leer trababa BizHawk (ahora cada cliente tiene su cola) y el aviso de conexión no se ocultaba. Validado con el juego: cambios de ruta, ciudad y equipo en vivo, sin trabas. |
| 29-oct | Ruleta (MVP): `effects.py` (catálogo de efectos reutilizable), `roulette.py` (premios en `roulette.json`, elección por peso), `GET/PUT /roulette`, `POST /roulette/spin`, páginas `ruleta.html` (configurar y girar) y `ruleta-view.html` (rueda para OBS). Validado en el juego: gira en el overlay y aplica el premio. Pendiente: acomodar opciones y diseño. |
| 29-oct | Rendimiento: el puente tardaba ~11 ms por consulta (descifraba las cajas cada vez) y el juego esperaba; ahora 0,4 ms con memoria de lo ya descifrado. Lua: hex con tabla y lectura en bloque (`read_bytes_as_binary_string`, comprobada al arrancar). Validado: sin cortes en la música y se nota la velocidad 200 %. |
| 30-oct | Probabilidad de variocolor en vivo (`set_shiny_odds`): parche de las tiradas de PID de `FieldEncount_CreateWildPkm` (overlay 36), comando `P` del Lua (parche que se mantiene), firma `shiny`. Validado: con 1/2 salió variocolor al 4.º encuentro; se reaplica tras los combates y se quita limpio. Premio de ruleta "Hora variocolor" (eventos con `after`). |
| 08-nov | **Redux sobre White2Upgrade** (`tools/merge_redux.py`): especies, movimientos, entrenadores, guiones y parches de Redux encima de White2Upgrade con los sprites de Gen 6; Redux manda en 1-649. El puente regenera los datos aunque el CRC de la cabecera no cambie (`file_crc`). Probado: combate contra entrenador de Redux con control del rival. Paso 3 también probado (Gen 6: regalos, registro, rival). |
| 07-nov | **Sprites de Gen 6 completos y sin cortes**: `sprites_gen5.py lote` convierte 650-721 de una vez (52 animados, 20 fijos). Parche `mcss_depth.cpp` (+ `mcss.esdb.yml`, símbolos que White2Upgrade no nombra): las piezas marcadas no se van al fondo, así que Yveltal y Talonflame ya no se cortan con la cámara cerca; los originales no cambian. **Sin pausas en animaciones largas**: modos `auto`/`tramo`/`mitad`, tramo seguido en bucle o ida y vuelta, cuadritos parecidos juntados con un margen del 10 %; Klefki y Volcanion fluidos. |
| 06-nov | **Pokédex de White2Upgrade protegida** (`tools/w2u_build/patches/dex_limit.cpp`): las especies 673-721 ya no pisan el guardado (desvío de `PML_PkmIsBadMonsNo` en 4 funciones). Validado con Sylveon: 0 bytes distintos en el bloque tras verlo y capturarlo. `build.sh` aplica los parches de `patches/` y saca el volcado del módulo. |
| 06-nov | **White2Upgrade compilado y probado** (`tools/w2u_build/`, Docker): arreglado el ARM9 marcado como comprimido (pantalla en blanco). Indicador de menú relativo al puntero base (`0x0223E3D5` en White2Upgrade). Greninja (658) en combate forzado, capturado y con su GIF de Showdown animado. `sprites_gen5.py`: piezas de 16×16 y `--bloque auto` (menos cortes al acercarse la cámara). |
| 06-nov | **Sprites animados de Showdown en la ROM** (`tools/sprites_gen5.py`): cuadritos de 8×8 en la textura del combate y un nodo por posición. Validado en el juego con Sylveon: fijo, animado y apoyado en el suelo. Espacio: datos al final de la ROM, con la zona DSi de la cabecera (`0x90`/`0x92`) llevada al final, porque melonDS bloquea esa zona en modo DS. |
| 06-nov | Límites desde la ROM: especies (hasta la que va antes de "Huevo"), movimientos, habilidades, objetos (nombres) y umbral de variocolor (`PML_UtilPIDIsRare`, arm9 descomprimido en `rom.py`). Lo usan `pk5`, `gift`, `effects`, `field_script`, `move_pp`, `set_shiny_odds` y `ram_tool`. `rom_compare.py` compara por dirección los overlays que se cargan en otro sitio. Volt White 2 Redux revisado: el puente es compatible (falta probarlo en el juego). |
| 04-nov | Probado en vivo: registro correcto en dos combates (daño, PP, Restos, Tóxico, cambios, experiencia) y cambio del rival. Arreglos: `DAMAGE_PLURAL` lleva detrás los pokeID golpeados (el lector se perdía), bloques repetidos (se copiaban con el adaptador libre), Tóxico = "envenenamiento grave". Nuevo: eficacia, críticos, "no afecta", causa de cada cambio de vida y la vida tras cada golpe. |
| 04-nov | Control del rival (`rival.py`, `rival_action`), pausa del turno sin parches de código (estado 2 del adaptador, órdenes `H`/`HR` del Lua, `rival_control`) y registro de turnos (`battle_log.py`, `battle_cmd.decode`, `GET /battle/log`). Todo sale de la decomp y se comprobó con los volcados y pruebas; falta probarlo en el juego. `rom.py` añade tipo, categoría y potencia de los movimientos (`move_info`; el puente regenera `gen5_data.json`). |
| 03-nov | Regalo Misterioso: álbum en puntero + `0x1D120`, cifrado en RAM; `wondercard.py` (formato PGF y cifrado), `tools/wonder_card.py`, evento `give_wonder_card` (lee y luego escribe con guardas) y premio de ruleta "Regalo misterioso". El repartidor aparece al cargar el mapa del Centro si hay tarjetas sin entregar (guion `global_10395`, comando `MysteryGifts`). Validado: Genesect oficial, Pikachu variocolor propio y Caramelo Raro entregados por el repartidor; se conservan al guardar y reiniciar. |

---

## 9. Pruebas pendientes

### Confirmar lo ya hecho
- [x] **Evento retenido en el menú:** con el menú abierto, enviar `set_hp`; debe quedarse `pendiente` y aplicarse al cerrarlo.
- [X] **Reinicio:** *Emulation > Reboot Core*, cargar partida y anotar el puntero. Con `watch_ram.lua`, ver si la bandera de menú es fija o se mueve con el puntero. siguio mostrandose bien
- [x] **Guardar en el juego:** cambiar estado o HP, guardar con el menú del juego (SAVE), reiniciar y cargar. El cambio debe seguir ahí y el Pokémon no debe salir como huevo malo.
- [X] **Todos los estados:** `paralysis`, `sleep`, `freeze`, `poison`, `none`. Comprobar el ícono en el menú, que la pantalla de datos abre, y el efecto en combate.
- [X] **Slot 1** (segundo Pokémon) y un slot vacío (debe dar `fallo: no hay Pokémon en el slot`).
- [X] **Límites de HP:** `hp: 0` (¿aparece debilitado?) y `hp: 999` (debe quedar en el máximo).
- [X] **Cancelar:** abrir el menú, enviar un evento, cancelarlo con `DELETE` y cerrar el menú; no debe aplicarse.
- [X] **Rollback:** después de un cambio, `POST /rollback` y comprobar que se deshace.

### Casos difíciles (buscan fallos)
- [ ] Enviar un evento justo al **entrar** en un combate y otro justo al **salir**.
- [ ] Enviar un evento mientras cruzas una **puerta** o cambias de mapa.
- [ ] **Reordenar** el equipo o sacar un Pokémon del PC con un evento pendiente; la protección `G` debería evitar escribir sobre el Pokémon equivocado.
- [ ] Encolar **varios eventos** seguidos (5 o más) y ver que se aplican todos en orden.
- [ ] Token incorrecto: debe responder 401.

### Fase B (en el juego)
- [x] `heal` a todo el equipo: HP, estado y PP restaurados (ver pantalla de datos).
- [x] `set_item`: el objeto aparece en la pantalla de datos; en combate funciona (Restos cura al final del turno).
- [x] `set_move`: el movimiento aparece con sus PP, y se puede usar en combate.
- [x] Guardar en el juego tras estos cambios, reiniciar y cargar.

### Mochila (en el juego)
- [x] Dar Pociones, Bayas y Poké Balls: aparecen en el bolsillo correcto con la cantidad correcta.
- [x] Dar un objeto nuevo (Superball, MT01): aparece al final del bolsillo.
- [x] Quitar unidades y quitar todas: el bolsillo queda sin huecos.
- [x] Usar en el juego un objeto dado (beber una Poción, lanzar una Poké Ball).
- [x] Guardar, reiniciar y cargar.

### Regalos (en el juego)
- [ ] (Opcional) Abrir los `.pk5` de `pk5_export\` en PKHeX y revisar si los marca como válidos.
- [x] Regalar un Pokémon: aparece en la caja 1 con su nombre, nivel, movimientos y entrenador "Diego".
- [x] Retirarlo al equipo: las estadísticas se calculan bien y puede combatir.
- [x] Variocolor, hembra, objeto y movimientos elegidos se ven como se pidieron.
- [x] Le obedece en combate y gana experiencia normalmente.
- [x] Guardar, reiniciar y cargar.

### Fase 5: combate (en el juego)
- [x] Leer ambos lados: vida, nivel, movimientos, PP, cambios de estadísticas (combate salvaje).
- [x] `battle_set_hp` al rival en las dos copias: se debilita al siguiente golpe y el combate termina bien.
- [x] `battle_set_hp` a tu Pokémon: bajar a 5 (barra a rojo y 5/25) y curar de 5 a 25 (la barra sube animada).
- [x] Vida 0 a tu Pokémon (primera versión): **no se debilita** y el rival ataca y falla en bucle.
- [x] Vida 0 con `F`: Oshawott se debilitó con su animación, pidió el cambio y quedó debilitado en el equipo. Patrat salvaje:
  se debilitó, Bulbasaur ganó experiencia y el combate terminó. En los dos casos el Pokémon atacó antes de caer (límite conocido).
- [x] Estado en combate: descifrado (lista de condiciones desde `+0x1C`) y quemadura escrita al rival: hace daño al final del turno.
- [x] `battle_set_stage`: con Ataque +2 y Defensa del rival −2, el mismo golpe (desde el mismo savestate) pasó de quitar menos de media vida a debilitarlo.
- [x] `battle_set_pp`: PP al máximo se ve al instante en el menú de Luchar (33/35 → 35/35). Con un movimiento del rival a 0 PP no lo usó; sin PP en ninguno, usó Forcejeo.
- [x] `battle_set_item`: quitar los Restos a un Snorlax salvaje (los traía de serie): ya no se curó al final del turno. Darle una
  Baya Zidra con la vida justo encima de la mitad: tras el golpe se la comió y se curó.
- [x] Barra de vida e ícono de estado actualizados con los gráficos del juego (inyección en la cola del cliente).
- [x] Evento enviado **durante** las animaciones de un turno: con Leer en marcha, la barra del rival bajó a mitad del ataque, sin esperar al turno siguiente.
- [x] Subir la vida (curar en combate): la barra sube animada.
- [x] Envenenado a tu Pokémon: ícono PSN, tinte morado y daño al final del turno.
- [x] Congelado al rival: ícono y no atacó. Quitar el estado (`none`): desaparece el ícono, ataca de nuevo y no sale "se descongeló".
- [x] Sueño (`sleep`, `turns`) y envenenamiento grave (`toxic`), con el formato de la decompilación (condición = tipo en bits 0-2 +
  turnos en bits 3-8; contadores u8 desde +0xAC). Validado contra una entrenadora (Sewaddle): sueño con ícono SLP y ojos cerrados;
  con el contador a 3 durmió 2 turnos y atacó en el tercero (por eso `turns` = turnos sin atacar y se guarda turns + 1).
  Grave: daño 1, 2, 3, 4 con 21 de vida máxima. El ícono del grave es PSN con letras moradas (el normal, blancas): valor 6
  en `SET_GAUGE_STATUS` (corregido y validado con un Psyduck; antes mandábamos 5 y salía el normal).
  Contraprueba: Oshawott con Tóxico puesto por `set_move` envenenó a un Lillipup y `/state` lo leyó como `toxic (turno 1)`:
  el juego escribe el mismo valor que nosotros.
- [x] Probar parálisis, congelado y envenenado escritos, y quitar un estado (`none`).
- [x] Combate contra entrenador con varios Pokémon: `slot` 0 es siempre el que está en el campo (la tabla se reordena al cambiar).
  Vida y parálisis a un Pokémon del banco (`"show": false`): se ven en la lista, entra con ellos, la parálisis actúa y al
  terminar el combate el cambio queda en el equipo.
- [x] Combate doble (salvaje): `slot` 0 y 1 son los dos en el campo. Vida, parálisis y envenenamiento grave salen en la barra
  correcta; vida 0 a un rival: se debilita solo él y el combate sigue con el otro.


### Huevos (en el juego)
- [x] `give_egg` Charmander: llegó al equipo como Huevo (20 ciclos), eclosionó caminando con su animación y salió Charmander.
- [x] `give_egg` Pichu con `hatch_cycles: 0`: el puente le puso 0 ciclos al llegar (`set_egg_cycles` automático) y eclosionó tras pocos pasos.

### Dinero (en el juego)
- [x] `give_money` 1000: ₽7188 → ₽8188 en la Tarjeta de Entrenador; guardar y reiniciar lo conserva.

### Estación (en el juego)
- [x] `set_season` invierno en octubre: al salir de un edificio, nieve.
- [x] `set_season` `real`: al salir de un edificio vuelve el verano.
- [x] `set_season` otoño y primavera: cambian el paisaje y las condiciones del mapa. No sale el cartel de cambio de
  estación (normal: con la sincronización forzada el juego no compara con el reloj, que es quien muestra el cartel).

### Firmas de código (en el juego)
- [x] En el mapa: bytes de `reserve_get` y `script_vm` iguales en la RAM.
- [x] Con el Lua recargado, en un combate salvaje: `compat` con las cinco funciones en `true`; quemadura al rival (con ícono)
  y lluvia siguen funcionando.

### Variocolor (en el juego)
- [x] `set_shiny_odds` 1/2 en la Ruta 20: variocolor al 4.º encuentro, sin pausas al empezar el combate.
- [x] El parche vuelve solo tras cada combate (memoria leída en el mapa) y no se toca en combate.
- [x] Quitarlo (sin `odds`): la memoria vuelve a ser la de la ROM.
- [ ] "Hora variocolor" de la ruleta: vuelve a lo normal a los 10 minutos.

### Regalo Misterioso (en el juego)
- [x] Tarjeta oficial (Genesect) escrita en vivo: el repartidor aparece al volver a entrar al Centro y la entrega.
- [x] Tarjeta propia (Pikachu variocolor, Nv. 10) y tarjeta de objeto (Caramelo Raro).
- [x] Guardar y reiniciar: se conserva lo recibido y las tarjetas quedan entregadas.
- [ ] `give_wonder_card` por el puente y el premio de la ruleta (probado solo con un Lua simulado).
- [ ] Álbum lleno: la 13.ª tarjeta reemplaza a una ya entregada.

### Sprites Gen 5 (en el juego)
- [x] Sprite fijo de Showdown en lugar del de otra especie (Sylveon en Pikachu): el combate va normal.
- [x] Animado de frente y de espalda (combate y resumen), apoyado en el suelo.
- [x] Datos al final de la ROM con `0x90`/`0x92` al final (en BizHawk).
- [ ] Variocolor (un salvaje variocolor de la especie sustituida).
- [x] En White2Upgrade, sobre su propia especie (Greninja, 658): frente animado y espalda fija, apoyados.
- [x] Con 8×8 hay cortes breves al capturar; con 16×16 se notan menos.
- [x] Las 72 de Gen 6 en lote (07-nov): Fennekin y Sylveon fluidos; las que pierden fotogramas se ven con pausas.
- [x] Con el parche de profundidad: Yveltal y Talonflame sin cortes; los sprites originales, iguales.
- [x] Modo `tramo` (Volcanion, Klefki, Zygarde, Tyrantrum): fluido, "prácticamente no se nota"; `mitad` se ve pixelado.
- [ ] Especie con más de 512 cuadritos (p. ej. Incineroar): se ve bien con menos fotogramas.
- [ ] Combate doble con dos sprites animados.

### White2Upgrade (en el juego)
- [x] Arranca con el ARM9 arreglado; carga el save de W2 y el combate funciona.
- [x] Puente: 721 especies, `data_ok`, modo `map`/`menu` correcto y las 13 firmas en `true`.
- [x] Combate salvaje forzado contra Greninja; captura y registro en la Pokédex.
- [x] Regalo (`give_pokemon`) de una especie de Gen 6 al equipo y a la caja (07-nov: Sylveon y Greninja).
- [x] Registro de turnos y control del rival con una especie de Gen 6 (Klefki: Beso Drenaje "no es muy eficaz" contra
  Acero, Púas con prioridad de Bromista).

### Redux sobre White2Upgrade (en el juego)
- [x] Arranca, partida nueva, el puente regenera los datos (variocolor 128, 891 entrenadores) y las firmas coinciden.
- [x] Combate contra entrenador de Redux, registro y control del rival (ataque y cambio tras debilitarse).
- [ ] Lista de MT, Grutas Ocultas y Recogida como en Redux.
- [ ] Un salvaje variocolor (1/512) y una especie de Gen 6 salvaje o regalada.
- [x] Protección de la Pokédex (673-721): Sylveon visto y capturado sin tocar ningún byte del bloque.
- [ ] Pokédex completa para 673-721 (bloque extra), si hace falta.

### Volt White 2 Redux (en el juego)
- [ ] Con `ROM_PATH` a Redux: el puente regenera `gen5_data.json` (`shiny_threshold` 128, Clefairy tipo 17).
- [ ] Combate: registro, `battle_set_hp`, `rival_action` y la pausa funcionan igual (firmas `true` en `/state`).
- [ ] Un variocolor salvaje sale con `shiny: true` en `/state`; `set_shiny_odds` con 50 sube la frecuencia.
- [ ] Regalo variocolor (`give_pokemon` con `shiny`) se ve variocolor en el juego.

### Control del rival y registro (en el juego)
- [x] `GET /battle/log` en un combate contra entrenador: turnos, daño, cambios y la foto de cada turno coinciden con lo visto.
- [x] `rival_action` switch durante el turno: el rival cambió de Lillipup a Patrat en el turno 1.
- [ ] Causas en vivo: veneno, Restos, retroceso, clima (arena/granizo), habilidad (Piel Tosca), golpe crítico, muy eficaz.
- [ ] `rival_action` move: el rival usa el movimiento pedido (en un turno normal, con el jugador aún en el menú).
- [ ] Cambio tras debilitarse: sale el Pokémon pedido (también con el estilo "Cambio", que avisa de quién sale).
- [ ] `rival_control` pause: tras elegir, el turno espera; con `rival_action` sigue enseguida; sin él, a los `seconds`.
- [ ] Pausa con tu Pokémon debilitado (el rival no elige nada): se suelta sola.
- [ ] Combate doble: `target.slot` 1 y el cambio de cada posición.
- [ ] Atrapado (Mal de Ojo, Sombra Trampa) y encadenado (Enfado, Hiperrayo): `rival_action` falla con el motivo.
- [ ] Cerrar el script de Lua con la pausa activa: el combate sigue.

### Combates forzados y clima (en el juego)
- [x] `start_wild_battle` fuera de la hierba (dentro de un pueblo): transición, Pikachu salvaje nivel 10 y vuelta normal al mapa.
- [x] `start_trainer_battle` 165 (Chica): transición de entrenador, sacó un Purrloin, vuelta normal al mapa. Esperó a que se
  cerrara un menú abierto.
- [x] `set_weather` lluvia: llueve en el mapa y el siguiente combate empezó con lluvia; al volver al mapa, volvió el clima de la ruta.
- [x] `set_weather` con `persist`: la lluvia volvió sola tras huir de un combate.
- [x] Climas del mapa 1-13 vistos uno a uno (nombres en la sección 7). El 3 dio arena y el 4/5 granizo con daño en combate:
  así se vio que en combate 3 = granizo y 4 = arena (estaban al revés en `battle_set_weather`; corregido).
- [x] `battle_set_weather` sol 3 turnos (contra una entrenadora): animación y mensaje al empezar el turno, y se acabó al tercero.
- [x] Entrenador doble (21, Backers: dos Darumaka nivel 31): combate doble correcto.
- [x] Dos entrenadores a la vez (`trainer` 162 + `trainer2` 163 del randomizer): combate doble contra Sewaddle y Mudkip;
  `/state` muestra al segundo como `enemy` 6 y `battle_set_status` quemado en el slot 6 funcionó (ícono y daño).
- [ ] Combate multi con compañero (cliente 2, `player` 6-11): sin probar; no hay orden para lanzarlo todavía.
- [x] Perder un combate forzado: la primera versión **se colgó** ("An error has occurred"). En combates lanzados por guion el
  juego no hace la derrota solo (`EventBattleCall`, `unk14`): el guion debe preguntar si ganó y llamar a la derrota, como los
  del juego. Corregido (`0x8D`/`0x177` ¿ganó?, `0x19` comparar, `0x1F` saltar, `0x8C`/`0x176` derrota): al perder, fundido a
  negro, Centro Pokémon con el equipo curado y ₽240 menos.
- [x] Perder un combate salvaje forzado: Gyarados nivel 40 sin huida contra el equipo a 1 de vida; tras caer el último, al Centro Pokémon sin error.
- [x] `teleport` a `aspertia`: fundido a negro y apareció frente a la casa del protagonista; todo normal.
- [x] `teleport` con `x`/`z`: zona 435, casilla 7,12 (Centro Pokémon de Engobe, de `RESPAWN_ZONE_INFO`): frente al mostrador.
- [x] `start_wild_battle` con opciones: Eevee variocolor, hembra, Anticipación (oculta) y sin poder huir. Con `0x10` no salió
  variocolor: el variocolor es `0x02`. Tras debilitarse tu Pokémon sí se puede huir desde la pregunta de cambio (normal).
- [x] Master Ball dada durante el combate (escrita en la mochila) y captura correcta; el Eevee llegó a la caja con sus datos.
- [x] `give_item` con `"when": "en_combate"` tras recargar el Lua (sin herramientas de depuración): 3 Pociones visibles en la mochila del combate.
- [x] `give_pokemon` al equipo: Pikachu nivel 10 variocolor (el `param1C` sin nombre es el variocolor: 1 = sí) y hembra, entrenador
  Diego, conocido en Pueblo Floccesy. Con el equipo lleno, un Eevee fue al hueco 3 de la caja 1.

### Por buscar
- [ ] Fase 5: validar las direcciones de combate del tracker.

---

## 10. Ideas futuras (28-oct)

El puente es la base: todas estas ideas son formas distintas de **mandar eventos** al puente y de **mostrar lo que pasa** en el
juego. Orden propuesto al final.

```
Twitch / ruleta / tienda de cartas / admin "en las sombras"
              │  eventos
     Servidor central (cuentas, monedas, cartas, torneo, página web)
              │  cada jugador se conecta hacia el servidor (no se abren puertos)
     Puente local de cada jugador ──► BizHawk/Lua ──► juego
              │  avisos: capturó, se debilitó, ganó medalla, cambió de zona...
     Overlay de OBS / reglas automáticas (nuzlocke)
```

| Idea | Qué es | Qué falta en el puente |
| --- | --- | --- |
| **Twitch** | Recompensas de canal, bits y subs activan eventos (paralizar, dar huevo, forzar combate...). Un archivo dice "recompensa X → evento Y". Twitch EventSub por websocket: no hace falta servidor propio. | Nada para los eventos que ya existen; tiempos de espera y "no en mal momento". |
| **Ruleta** | Página (fuente de navegador en OBS) que gira y aplica el efecto que cae. | Nada. |
| **Overlay en tiempo real** | Equipo, medallas, progreso, en OBS. | Leer medallas y zona actual; avisos de cambios. |
| **Página pública** | Ver el equipo y la caja de cada jugador desde cualquier navegador. | Servidor central; cajas 2 en adelante. |
| **Torneo** | Varias personas con ROMs randomizadas distintas; luego torneo con los Pokémon que pasen la liga (p. ej. exportados a Showdown). | Detectar la liga; exportar Pokémon (ya hay `pk5_export`). |
| **Monedas y cartas** | Puntos por retos → comprar cartas: objetos, Pokémon, Poké Balls, curar, subir estadísticas, quemar al rival o a su equipo cuando esté en un gimnasio, robar / borrar / revivir Pokémon. | Saber contra qué entrenador pelea (gimnasio); quitar, mover y copiar Pokémon entre jugadores. |
| **Nuzlocke automático** | Pokémon debilitado → caja de muertos; auditoría de capturas por ruta (si ya capturó ahí, se anuncia / libera salvo carta). | Avisos de "capturó" y "se debilitó"; quitar del equipo; cajas 2+. El Pokémon guarda dónde se capturó (lugar de encuentro del PK5), así la auditoría es fiable. |
| **Entrenadores ocultos** | Alguien "en las sombras" lanza un combate contra un entrenador. | Ya funciona con entrenadores existentes (`start_trainer_battle`); con equipo inventado, por investigar. |
| **Encuentros por fecha** | P. ej. Ruta 2 solo iniciales, Ruta 8 solo pseudolegendarios, en una fecha y hora; luego vuelve a la normalidad. | Investigado y probado en el juego (sección 2, "Encuentros salvajes del mapa"): escribir la tabla en RAM funciona; falta la zona actual y el evento con fecha/hora. |

Requisitos comunes:
- Todo en tiempo real y sin salir de la partida.
- Seguridad: el puente local nunca se expone a internet; el servidor decide qué se permite (límites, tiempos de espera) y el
  puente solo acepta lo que llega por su conexión.
- Eventos en cola que esperan el momento correcto (como ya hacen los de combate y los guiones).

Orden propuesto:
1. **Base del puente:** avisos de sucesos (captura, debilitado, medalla, cambio de zona), leer medallas y zona, quitar/mover
   Pokémon, cajas 2+.
2. Overlay de OBS y ruleta.
3. Twitch.
4. Nuzlocke automático.
5. Servidor con monedas, cartas, torneo y página pública.
6. Encuentros por fecha (tras la zona actual del paso 1) y entrenadores con equipo inventado.
