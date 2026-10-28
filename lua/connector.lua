-- connector.lua — script para BizHawk (núcleo melonDS), Pokémon Black 2 / White 2.
-- Lanzar BizHawk con:  EmuHawk.exe --socket_ip=127.0.0.1 --socket_port=43884
-- Abrir en Tools > Lua Console. Primero arrancar bridge.py.
-- Lua no descifra nada: solo lee/escribe bytes y dice en qué modo está el juego.

local DOMAIN = "Main RAM"
local BASE = 0x02000000

-- Direcciones comunes a B2/W2 (fuente: NDS Ironmon Tracker + volcados; ver DOCUMENTACION.md).
-- El equipo no está fijo: se lee un puntero en 0x02000024 y se le suman offsets.
local MAIN_POINTER_OFF = 0x24         -- offset dentro de Main RAM
local PARTY_PTR_OFF = 0x19728
local PARTY_COUNT_PTR_OFF = 0x19724
local PARTY_SLOT_SIZE = 220
local BAG_PTR_OFF = 0x18D20           -- mochila (sin cifrar)
local BAG_SIZE = 0x998
local BOX1_PTR_OFF = 0xD20            -- caja 1 (30 huecos de 136 bytes)
local BOX1_SIZE = 0xFF0
local TRAINER_PTR_OFF = 0x19D20       -- datos del jugador
local TRAINER_SIZE = 0x24
local MISC_PTR_OFF = 0x21A20          -- dinero (u32) y medallas (u8 en +4): bloque Misc del save (0x21100)
local MISC_SIZE = 8
local HEADER_OFF = 0x3FFE00           -- copia de la cabecera del cartucho en Main RAM
local BATTLE_TABLE_PTR_OFF = 0x526A8  -- tabla de la copia "visual" de los combatientes (tracker: mainBattleDataPtr)
local BATTLE_SERVER_PTR_OFF = 0x52790 -- tabla de la copia "real", la que decide el combate (volcado combate1)
local BATTLER_SIZE = 0x140            -- bytes que se envían de cada combatiente (movimientos en +0x104)

-- Direcciones que cambian según el juego (código del cartucho). Solo se escribe en juegos de esta lista.
--   battle: u16, 0x2100/0x2101 = en combate
--   menu:   u8, 0 = caminando libre; 1 = menú, diálogo, equipo, mochila, combate
local GAMES = {
  IRDO = { name = "White 2 (USA/Europa)", battle = 0x021B5178, menu = 0x0223B2F5,
           adapters = 0x021DD8AC, client_proc = 0x021B1A15,     -- combate: sAdapters y función del cliente (B2 + 0x40)
           check_fainted = 0x021A8A64,                          -- ServerControl_CheckFainted (B2 + 0x40)
           reserve_get = 0x0201936C,                            -- FieldStatus_GetReserveScript (B2 + 0x2C)
           script_vm = 0x02153DC8,                              -- FieldScript_AttachOpcodeGuard (B2 + 0x40)
           battle_field = 0x021DD928 },                         -- sField: clima del combate (B2 + 0x40)
  -- IREO (Black 2 USA/Europa): battle = 0x021B5138 según el tracker; falta encontrar "menu" (ver DOCUMENTACION.md)
}

local POLL_EVERY = 10          -- frames entre consultas (~6 por segundo)
local SAFETY_SLOT = 9          -- ranura de savestate de seguridad

local function off(addr) return addr - BASE end

local function to_hex(bytes)
  local t = {}
  for i = 0, #bytes do
    if bytes[i] ~= nil then t[#t + 1] = string.format("%02x", bytes[i]) end
  end
  return table.concat(t)
end

local function from_hex(hex)
  local t = {}
  for byte in hex:gmatch("%x%x") do t[#t + 1] = tonumber(byte, 16) end
  return t
end

local function read_hex(addr, len)
  return to_hex(memory.read_bytes_as_array(off(addr), len, DOMAIN))
end

-- Devuelve la dirección absoluta del equipo y cuántos hay, o nil si no es válida
local function party_location()
  local ptr = memory.read_u32_le(MAIN_POINTER_OFF, DOMAIN) % 0x1000000  -- quita el byte alto
  local size = memory.getmemorydomainsize(DOMAIN)
  if ptr == 0 or ptr + PARTY_PTR_OFF + 6 * PARTY_SLOT_SIZE > size then return nil end
  local n = memory.read_u8(ptr + PARTY_COUNT_PTR_OFF, DOMAIN)
  if n < 1 or n > 6 then return nil end
  return BASE + ptr + PARTY_PTR_OFF, n
end

-- Código del cartucho (ej. "IRDO") y CRC de su cabecera, para que el puente compruebe los datos
local function game_id()
  local code = ""
  for i = 0, 3 do code = code .. string.char(memory.read_u8(HEADER_OFF + 0x0C + i, DOMAIN)) end
  return code, memory.read_u16_le(HEADER_OFF + 0x15E, DOMAIN)
end

local function game_mode(game, party_addr)
  if game == nil or party_addr == nil then return "unknown" end
  local bs = memory.read_u16_le(off(game.battle), DOMAIN)
  if bs == 0x2100 or bs == 0x2101 then return "battle" end
  if memory.read_u8(off(game.menu), DOMAIN) ~= 0 then return "menu" end
  return "map"
end

-- En combate: cada combatiente en sus dos copias (estructura de batalla y su Pokémon cifrado).
-- Formato: "T:<tabla>,p0:<dir>:<estructura>:<pk5>,e0:...". p/e = copia visual; P/E = copia real.
local function battle_hex(ptr_abs, game)
  local size = memory.getmemorydomainsize(DOMAIN)
  local tbl = ptr_abs + BATTLE_TABLE_PTR_OFF
  local srv = ptr_abs + BATTLE_SERVER_PTR_OFF
  local parts = { "T:" .. read_hex(tbl, 0x38) }
  for side, base in pairs({ p = tbl, e = tbl + 0x1C, P = srv, E = srv + 0x1C }) do
    for i = 0, 5 do
      local a = memory.read_u32_le(off(base + 4 * i), DOMAIN) % 0x1000000
      if a ~= 0 and a + BATTLER_SIZE < size then
        local pk = memory.read_u32_le(a, DOMAIN) % 0x1000000
        local pk5 = (pk ~= 0 and pk + 220 < size) and read_hex(BASE + pk, 220) or "-"
        parts[#parts + 1] = string.format("%s%d:%08x:%s:%s", side, i, BASE + a, read_hex(BASE + a, BATTLER_SIZE), pk5)
      end
    end
  end
  if game.battle_field then parts[#parts + 1] = "W:" .. read_hex(game.battle_field, 8) end   -- clima, turnos
  return table.concat(parts, ",")
end

-- Inyección de comandos de combate (fase 5, opción 3, experimental): el bloque pendiente se inserta en la
-- cola del cliente del jugador mientras reproduce un turno, en la posición de lectura, para que se vea enseguida.
-- Cliente: +0x28 función, +0x50 adaptador, +0x13C cola, +0x1AF tipo, +0x1B0 estado (1 = ejecutando).
-- Cola: u32 escritura, u32 lectura, búfer de 3000 bytes. Adaptador: +0x10 comando (8 = bloque del servidor).
local pending_inject = nil
local inject_status = ""
local cached_adapter, cached_client = nil, nil

local function battle_client(game)
  local a = memory.read_u32_le(off(game.adapters), DOMAIN)
  if a < BASE or a >= BASE + 0x400000 then return nil end
  if a ~= cached_adapter then
    cached_adapter, cached_client = a, nil
    for delta = -0x2000, 0x2000, 4 do
      local c = a + delta
      if c >= BASE and memory.read_u32_le(off(c + 0x50), DOMAIN) == a
         and memory.read_u32_le(off(c + 0x28), DOMAIN) == game.client_proc
         and memory.read_u8(off(c + 0x1AF), DOMAIN) == 0 then
        cached_client = c
        break
      end
    end
  end
  return a, cached_client
end

local function try_inject(game)
  local a, c = battle_client(game)
  if c == nil then return end
  if memory.read_u8(off(c + 0x1B0), DOMAIN) ~= 1 or memory.read_u16_le(off(a + 0x10), DOMAIN) ~= 8 then return end
  local q = memory.read_u32_le(off(c + 0x13C), DOMAIN)
  local wp = memory.read_u32_le(off(q), DOMAIN)
  local rp = memory.read_u32_le(off(q + 4), DOMAIN)
  if rp >= wp then return end                                   -- ya leyó todo el bloque: esperar al siguiente
  if wp + #pending_inject > 3000 then
    inject_status = "cola llena, descartado"; pending_inject = nil; return
  end
  local new = {}
  for i = 1, #pending_inject do new[#new + 1] = pending_inject[i] end
  local rest = memory.read_bytes_as_array(off(q + 8 + rp), wp - rp, DOMAIN)
  local first = (rest[0] ~= nil) and 0 or 1
  for i = first, first + wp - rp - 1 do new[#new + 1] = rest[i] end
  memory.write_bytes_as_array(off(q + 8 + rp), new, DOMAIN)
  memory.write_u32_le(off(q), wp + #pending_inject, DOMAIN)
  inject_status = string.format("inyectados %d bytes (lectura %d de %d)", #pending_inject, rp, wp)
  console.log("connector.lua: " .. inject_status)
  pending_inject = nil
end

-- Debilitar (vida 0): el juego solo debilita a un Pokémon en ServerControl_CheckFainted(flow, mon), y no revisa a los
-- que ya tienen 0. El puente deja la copia real a 1 y manda "F <dir>"; BizHawk avisa cada vez que el juego ejecuta
-- esa función y, si r1 (mon) es uno pendiente y sigue a 1 de vida, se pone a 0 justo antes de que lo compruebe.
-- El aviso solo se registra mientras hay algo pendiente (cada instrucción ejecutada se compara con la dirección).
local pending_faint = {}          -- dirección de la copia real -> true
local faint_hook = false
local faint_status = ""

local function faint_count()
  local n = 0
  for _ in pairs(pending_faint) do n = n + 1 end
  return n
end

local function on_check_fainted()
  local mon = emu.getregisters()["ARM9 r1"]
  if mon == nil or not pending_faint[mon] then return end
  pending_faint[mon] = nil
  if memory.read_u16_le(off(mon + 0x10), DOMAIN) == 1 then
    memory.write_u16_le(off(mon + 0x10), 0, DOMAIN)
    faint_status = string.format("debilitado %08X", mon)
  else
    faint_status = string.format("cancelado %08X (su vida cambió)", mon)
  end
end

local function faint_unhook()
  if faint_hook then event.unregisterbyname("connector_faint"); faint_hook = false end
end

-- Guion propio (combate salvaje, contra entrenador, clima...): el juego ejecuta el "guion reservado" de FieldStatus
-- (+0x12) en cuanto el personaje queda libre en el mapa. Al leerlo (FieldStatus_GetReserveScript, r0 = FieldStatus)
-- se pone RESERVE_ID; al crear su máquina de guiones (FieldScript_AttachOpcodeGuard, r0 = VM, pc en +0x20) se escriben
-- nuestros bytes encima del guion cargado. El juego hace el resto (transición, música, vuelta al mapa).
local RESERVE_ID = 2000           -- guion global 2000 (archivo SCRIPTS_GLOBAL_2000); solo se usa su espacio
local pending_script = nil        -- bytes del guion
local script_stage = ""           -- "armado" -> "reservado" -> "" (hecho)
local script_status = ""
local script_hooks = false

local function on_reserve_get()
  if script_stage ~= "armado" then return end
  local status = emu.getregisters()["ARM9 r0"]
  if status == nil or status < BASE or status >= BASE + 0x400000 then return end
  memory.write_u16_le(off(status + 0x12), RESERVE_ID, DOMAIN)
  script_stage = "reservado"
end

local function on_script_vm()
  if script_stage ~= "reservado" then return end
  local vm = emu.getregisters()["ARM9 r0"]
  local pc = vm and memory.read_u32_le(off(vm + 0x20), DOMAIN)
  if pc == nil or pc < BASE or pc >= BASE + 0x400000 then return end
  memory.write_bytes_as_array(off(pc), pending_script, DOMAIN)
  pending_script, script_stage = nil, ""
  script_status = string.format("ejecutado (%08X)", pc)
end

local function script_unhook()
  if script_hooks then
    event.unregisterbyname("connector_reserve"); event.unregisterbyname("connector_script")
    script_hooks = false
  end
end

local function run(cmd)
  local op, a, b, c = cmd:match("^(%S+)%s*(%S*)%s*(%S*)%s*(%S*)")
  if op == "W" then
    local bytes = from_hex(b)
    memory.write_bytes_as_array(off(tonumber(a)), bytes, DOMAIN)
    return true, "W " .. a
  elseif op == "G" then
    local expected = b
    local len = #expected / 2
    if read_hex(tonumber(a), len) ~= expected then
      return false, "guarda no coincide en " .. a .. " (los datos cambiaron)"
    end
    memory.write_bytes_as_array(off(tonumber(a)), from_hex(c), DOMAIN)
    return true, "G " .. a
  elseif op == "J" then                         -- inyectar comandos de combate en el siguiente turno
    local extra = from_hex(a)
    pending_inject = pending_inject or {}         -- si ya había algo pendiente, se acumula
    for i = 1, #extra do pending_inject[#pending_inject + 1] = extra[i] end
    inject_status = string.format("pendiente (%d bytes): se verá al reproducirse el turno", #pending_inject)
    return true, "J pendiente"
  elseif op == "F" then                         -- debilitar cuando el juego revise a este combatiente
    local game = GAMES[game_id()]
    if game == nil or game.check_fainted == nil then return false, "F: falta check_fainted para este juego" end
    if not faint_hook then
      local ok, err = pcall(event.on_bus_exec, on_check_fainted, game.check_fainted, "connector_faint")
      if not ok then return false, "F: este núcleo no admite avisos de ejecución: " .. tostring(err) end
      faint_hook = true
    end
    pending_faint[tonumber(a)] = true
    faint_status = string.format("pendiente %s: se debilita al revisarlo el juego", a)
    return true, "F pendiente"
  elseif op == "S" then                         -- ejecutar un guion propio en cuanto el personaje quede libre
    local game = GAMES[game_id()]
    if game == nil or game.reserve_get == nil then return false, "S: falta reserve_get para este juego" end
    if pending_script ~= nil then return false, "S: ya hay un guion esperando" end
    if not script_hooks then
      local ok1, e1 = pcall(event.on_bus_exec, on_reserve_get, game.reserve_get, "connector_reserve")
      local ok2, e2 = pcall(event.on_bus_exec, on_script_vm, game.script_vm, "connector_script")
      if not (ok1 and ok2) then
        script_hooks = true; script_unhook()
        return false, "S: este núcleo no admite avisos de ejecución: " .. tostring(e1 or e2)
      end
      script_hooks = true
    end
    pending_script, script_stage = from_hex(a), "armado"
    script_status = string.format("esperando (%d bytes): se ejecuta con el personaje libre", #pending_script)
    return true, "S pendiente"
  elseif op == "R" then                         -- leer (herramienta de investigación)
    local len = tonumber(b)
    if len == nil or len < 1 or len > 0x400 then return false, "R: longitud inválida" end
    return true, "R:" .. read_hex(tonumber(a), len)
  elseif op == "SAVE" then
    savestate.saveslot(SAFETY_SLOT)
    return true, "SAVE"
  elseif op == "LOAD" then
    savestate.loadslot(SAFETY_SLOT)
    return true, "LOAD"
  end
  return false, "comando desconocido: " .. tostring(op)
end

local function handle(reply)
  if reply == nil then return end
  reply = reply:gsub("%s+$", "")
  if reply == "" then return end
  local cmds = {}
  for cmd in reply:gmatch("[^;]+") do cmds[#cmds + 1] = cmd end
  -- Primero se revisan todas las guardas: si una no coincide, no se escribe nada
  for _, cmd in ipairs(cmds) do
    local op, a, b = cmd:match("^(%S+)%s*(%S*)%s*(%S*)")
    if op == "G" and read_hex(tonumber(a), #b / 2) ~= b then
      comm.socketServerSend("RES fail guarda no coincide en " .. a .. " (los datos cambiaron); no se escribió nada")
      return
    end
  end
  local ok_all, details = true, {}
  for _, cmd in ipairs(cmds) do
    local ok, detail = run(cmd)
    details[#details + 1] = detail
    if not ok then ok_all = false; break end
  end
  comm.socketServerSend("RES " .. (ok_all and "ok" or "fail") .. " " .. table.concat(details, ","))
end

event.onexit(function() faint_unhook(); script_unhook() end)
comm.socketServerSetTimeout(50)
console.log("connector.lua listo; conectado: " .. tostring(comm.socketServerIsConnected()))

local frame = 0
while true do
  frame = frame + 1
  if frame % POLL_EVERY == 0 then
    local code, crc = game_id()
    local game = GAMES[code]
    local addr, n = party_location()
    local mode = game_mode(game, addr)
    local party, bag, box, trainer, battle, misc = "-", "-", "-", "-", "-", "-"
    if addr ~= nil and mode ~= "battle" then
      local ptr = addr - PARTY_PTR_OFF
      party = read_hex(addr, n * PARTY_SLOT_SIZE)
      bag = read_hex(ptr + BAG_PTR_OFF, BAG_SIZE)
      box = read_hex(ptr + BOX1_PTR_OFF, BOX1_SIZE)
      trainer = read_hex(ptr + TRAINER_PTR_OFF, TRAINER_SIZE)
      misc = read_hex(ptr + MISC_PTR_OFF, MISC_SIZE)
    elseif addr ~= nil and mode == "battle" then
      battle = battle_hex(addr - PARTY_PTR_OFF, game)
    end
    if mode ~= "battle" and pending_inject ~= nil then   -- el combate terminó: lo pendiente ya no aplica
      pending_inject = nil
      inject_status = "descartado (terminó el combate)"
    end
    if mode ~= "battle" and faint_count() > 0 then
      pending_faint = {}
      faint_status = "descartado (terminó el combate)"
    end
    if faint_hook and faint_count() == 0 then faint_unhook() end   -- fuera del aviso, no desde dentro
    if script_hooks and pending_script == nil then script_unhook() end
    comm.socketServerSend(string.format("POLL %s 0x%08x %s %s %s %s %s:%04x %s %s", mode, addr or 0, party, bag, box, trainer,
                                        code:gsub("[^%w]", "_"), crc, battle, misc))
    handle(comm.socketServerResponse())
    gui.text(4, 4, "puente: " .. mode)
    if game == nil then gui.text(4, 20, "juego no soportado: " .. code .. " (no se escribe nada)") end
  end
  if pending_inject ~= nil then
    local g = GAMES[game_id()]
    if g ~= nil then try_inject(g) end
  end
  if inject_status ~= "" then gui.text(4, 36, "inyección: " .. inject_status) end
  if faint_status ~= "" then gui.text(4, 52, "debilitar: " .. faint_status) end
  if script_status ~= "" then gui.text(4, 68, "guion: " .. script_status) end
  emu.frameadvance()
end
