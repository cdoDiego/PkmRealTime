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
├── battle.py              Estructura de combate (fase 5): lectura y escrituras
├── rom.py                 Lee datos de la ROM → gen5_data.json
├── gamedata.py            Carga gen5_data.json
├── move_pp.py             PP máximos (usa los de la ROM; tabla original de respaldo)
├── config.py              Direcciones de memoria y valores por defecto
├── config_local.example.py  Plantilla de configuración personal (copiar como config_local.py)
├── requirements.txt
├── lua/                   Scripts de BizHawk: connector.lua, dump_ram.lua, watch_ram.lua
├── tools/                 ram_tool.py (análisis de volcados)
├── tests/                 Pruebas (run_all.py las ejecuta todas)
├── postman/               Colección de Postman con todas las peticiones
├── docs/                  Esta documentación
├── dumps/                 Volcados de RAM (no se suben)
└── pk5_export/            .pk5 generados (no se suben)
```

No se suben a git (ver `.gitignore`): `config_local.py`, ROMs y partidas, `gen5_data.json` (sale de la ROM de cada persona),
`dumps/` y `pk5_export/`.

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
| Caja b | caja 1 + b × `0x1000` | `0x1000` | 30 huecos (`0xFF0`) + pie de 16 bytes con CRC16 de la caja | Volcados + PKHeX | 🟡 visto en volcados |
| Datos del jugador | puntero + `0x19D20` | `0x24` bytes | Nombre (`+0x04`), TID (`+0x14`), SID (`+0x16`), idioma (`+0x1E`), juego (`+0x1F`), género (`+0x21`) | Volcados + PKHeX (`MyStatus5`) | ✅ usado en regalos 27-oct |
| Mochila | puntero + `0x18D20` | `0x998` bytes | 5 bolsillos sin cifrar (ver abajo). En la prueba: `0x0221DA24` | Volcados + PKHeX (`PlayerBag5B2W2`) | ✅ leída y escrita 27-oct |
| Estado de combate | `0x021B5178` | u16 | `0x2100` o `0x2101` = en combate | Tracker (`battleStatus`, W2) | ✅ validado 25-oct |
| Bandera de control libre | `0x0223B2F5` | u8 | `0` = caminando libre; `1` = menú, diálogo, equipo, datos, mochila, combate | `ram_tool.py diff` + `watch_ram.lua` | ✅ validado 26-oct (también tras reiniciar el juego) |
| Dinero y medallas (bloque Misc) | puntero + `0x21A20` | u32 + u8 | Dinero (tope 9.999.999) y medallas (un bit cada una, en `+4`). Bloque Misc del save (`0x21100`) | PKHeX (`Misc5`) + tracker (`badges` = `0x21A24`) | ✅ leído y escrito 27-oct (₽7188 → ₽8188, se conserva al guardar) |
| Variable del buzón | — | — | Idea inicial para pasar mensajes al juego | — | ➖ ya no hace falta: los guiones propios (`S`) cubren ese uso |
| `FieldStatus_GetReserveScript` | `0x0201936C` | código | Lee el guion reservado (`FieldStatus` + `0x12`, u16) | pokebw2 (B2 `0x02019340` + `0x2C`) | ✅ usado 27-oct (combates forzados) |
| `FieldScript_AttachOpcodeGuard` | `0x02153DC8` | código | Se llama al crear la máquina de un guion (`r0` = VM, `pc` en `+0x20`) | pokebw2 (B2 + `0x40`) | ✅ usado 27-oct |
| Clima del combate (`sField`) | `0x021DD928` | 2 × u32 | Clima (0 nada, 1 sol, 2 lluvia, 3 granizo, 4 arena) y turnos (`0xFF` = sin fin) | pokebw2 (B2 + `0x40`; confirmado en el volcado) | ✅ escrito 27-oct |
| `ServerControl_CheckFainted` | `0x021A8A64` | código | Decide si un combatiente se debilita (`r1` = copia real) | pokebw2 (B2 + `0x40`) | ✅ usado 27-oct |
| `sItemEventAddTable` | `0x021D8F68` | 171 × {u32 objeto, función} | Objetos con efecto en combate; cada función es `movs r1,#n; str r1,[r0]; ldr r0,=tabla; bx lr` (nº de efectos y su tabla) | pokebw2 (B2 + `0x40`; confirmado en el volcado) | ✅ usado 28-oct |
| Lista de efectos del combate | `0x021DB1D4` (+ huecos libres en `0x021DB1E0`) | u32 profundidad, primera entrada, nº en uso | Efectos registrados (habilidades, objetos...), por prioridad. Entradas de `0x3C` bytes | pokebw2 `battle_event.c` (B2 + `0x40`; confirmado en el volcado) | ✅ escrito 28-oct |

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
si u8  en 0x0223B2F5 ≠ 0                          → "menu"
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
| Lua → Python | `POLL <modo> <dir. equipo 0x...> <hex equipo> <hex mochila> <hex caja 1> <hex jugador> <código:crc> <combate> <hex misc>` (equipo, mochila, caja, jugador y misc van como `-` en combate; combate va como `-` fuera de él) |
| Python → Lua | comandos separados por `;` (vacío = nada que hacer) |
| | `W <dir> <hex>` escribe bytes |
| | `G <dir> <hex_esperado> <hex_nuevo>` escribe solo si la memoria coincide |
| | `J <hex>` inyecta comandos de pantalla en el siguiente turno del combate |
| | `F <dir>` debilita a ese combatiente cuando el juego lo revise (vida 0) |
| | `I <dir> <objeto>` objeto de un combatiente (copia real), con sus efectos registrados en el juego |
| | `R <dir> <n>` lee bytes (herramienta de investigación) |
| | `S <hex>` ejecuta un guion propio en cuanto el personaje quede libre (combates forzados, clima del mapa) |
| | `SAVE` / `LOAD` savestate de seguridad (ranura 9) |
| Lua → Python | `RES <ok\|fail> <detalle>` tras cada lote |

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
- [ ] Regalos en otras cajas, no solo en la caja 1.

### Romhacks y randomizers (pendiente, retomar)

Estado (28-oct): los **datos** se leen de la ROM de cada persona (especies, estadísticas, experiencia, movimientos y PP,
habilidades, objetos, entrenadores) y se comprueba que sean de la ROM que se juega (código + CRC de la cabecera). Las
**direcciones** de memoria y de código (equipo, mochila, combate, `check_fainted`, `reserve_get`, `script_vm`, `item_table`,
`event_list`, `battle_field`...) están fijas en `GAMES` de `connector.lua`.

| Tipo de ROM | Previsión |
| --- | --- |
| Randomizer (Universal Pokemon Randomizer ZX) | Debería funcionar: cambia datos, no código. **Sin probar.** |
| Romhack que solo cambia datos | Igual que el randomizer. |
| Romhack que cambia código (p. ej. Blaze Black 2 / Volt White 2 Redux, más objetos o especies) | Las direcciones pueden moverse; además hay límites fijos (649 especies de reserva, 638 objetos en `pk5.MAX_ITEM`, `battle.MAX_ITEM`, `field_script`, listas de `bag.py`). |

**Riesgo actual:** el Lua no comprueba que en cada dirección siga el código esperado; con un hack que lo mueva escribiría a ciegas
(cuelgue o partida corrupta).

Plan:
- [ ] **1. Firmas antes de usar cada dirección (prioritario):** guardar en `GAMES` los primeros bytes esperados de cada función o
  tabla (sacarlos de un volcado del juego original) y compararlos al arrancar el Lua. Si no coinciden, desactivar solo esa función
  (F, S, I, comandos de pantalla...) y avisar en pantalla y en `/state` (p. ej. `"compat": {"forced_battles": false}`), y que el
  puente rechace esos eventos con un mensaje claro.
- [ ] **2. Buscar las direcciones si se movieron:** mismo método que `tools/symbol_offset.py` (buscar la firma en la RAM o en la
  ROM); también sirve para Black 2.
- [ ] **3. Probar con un randomizer:** ROM de White 2 randomizada con UPR ZX; revisar `/state` (nombres, PP), regalos, combate
  forzado salvaje y contra entrenador, `battle_set_item`, huevos.
- [ ] **4. Límites desde la ROM:** nº de objetos y especies leídos de la ROM en vez de 638/649 fijos.

## 7. API

Todas las peticiones llevan la cabecera `x-token: dev-token-cambiame`.

**Postman:** importa `postman/postman_collection.json` (*Import* > archivo). Trae las pruebas en carpetas.
Al crear un evento se guarda su `id` en la variable `eventId`, así que "Ver último evento" y "Cancelar" funcionan sin copiarlo.

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `GET` | `/state` | Modo, juego (`game`), si los datos son de esta ROM (`data_ok`), equipo, mochila (`bag`), caja 1 (`box1`) y combate (`battle`: copia real de cada lado, con `hp_visual`, `conditions` y `stages`) |
| `POST` | `/events` | Encola un evento. Devuelve su `id` |
| `GET` | `/events` | Lista todos los eventos |
| `GET` | `/events/{id}` | Estado de un evento: `pendiente`, `enviado`, `aplicado`, `fallo` o `cancelado` |
| `DELETE` | `/events/{id}` | Cancela un evento `pendiente` |
| `POST` | `/rollback` | Carga el savestate de la ranura 9 (estado anterior al último evento) |
| `WS` | `/ws?token=...` | Avisos en vivo del estado y de los eventos |

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
- `battle_set_weather` (experimental): clima del combate (`none`, `sun`, `rain`, `sandstorm`, `hail`), con `turns` opcional
  (sin `turns` no se acaba). Se anima con el mensaje del juego al reproducirse el turno; con `none` sale el de fin del clima.
  `/state` lo muestra en `battle.weather`.
- `give_item` / `take_item` funcionan también **en combate** (con `"when": "cualquiera"` o `"en_combate"`): la mochila del
  combate es la misma que la del mapa. Validado: Master Ball dada en pleno combate y usada para capturar.
- `/state`: cada Pokémon (equipo y combate) muestra también `shiny`, `gender`, `form`, `ability` y `hidden_ability`.
- `give_money` / `take_money` / `set_money`: dinero (`qty`). No baja de 0 ni pasa de 9.999.999. Con el personaje libre.
  `/state` muestra `money` y `badges` (número de medallas).
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
  hayas vencido. Si pierdes, el juego hace lo de siempre (volver al Centro Pokémon).
- `set_weather`: clima del mapa, por nombre o número: `none` 0, `snow` 1, `rain` 2, `sandstorm` 3 (arena en combate), `hail` 4
  (granizo en combate), `blizzard` 5 (granizo), `heavy_rain` 6 (lluvia), `rain_streaks` 7 (lluvia), `diamond_dust` 8, `fog` 9,
  `overcast` 10, `light_fog` 11, `heavy_sandstorm` 12 (arena), `overcast2` 13, `zone` = el de la ruta. Los que no dicen nada
  no dan clima en combate. `"persist": true` lo repone al volver de cada combate; `zone` lo quita.
- Si un evento escribe en varios slots, el Lua revisa todos antes de escribir: o se aplican todos o ninguno.
`when`: `"en_mapa"` (por defecto), `"en_combate"` (hoy siempre falla: fase 5) o `"cualquiera"`.

Protecciones: no se escribe si el modo es `unknown`, si el checksum del slot no es válido en ese momento,
o si la memoria cambió entre la lectura y la escritura.

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
