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
local HEADER_OFF = 0x3FFE00           -- copia de la cabecera del cartucho en Main RAM
local BATTLE_TABLE_PTR_OFF = 0x526A8  -- tabla de la copia "visual" de los combatientes (tracker: mainBattleDataPtr)
local BATTLE_SERVER_PTR_OFF = 0x52790 -- tabla de la copia "real", la que decide el combate (volcado combate1)
local BATTLER_SIZE = 0x140            -- bytes que se envían de cada combatiente (movimientos en +0x104)

-- Direcciones que cambian según el juego (código del cartucho). Solo se escribe en juegos de esta lista.
--   battle: u16, 0x2100/0x2101 = en combate
--   menu:   u8, 0 = caminando libre; 1 = menú, diálogo, equipo, mochila, combate
local GAMES = {
  IRDO = { name = "White 2 (USA/Europa)", battle = 0x021B5178, menu = 0x0223B2F5 },
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
local function battle_hex(ptr_abs)
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
  return table.concat(parts, ",")
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
    local party, bag, box, trainer, battle = "-", "-", "-", "-", "-"
    if addr ~= nil and mode ~= "battle" then
      local ptr = addr - PARTY_PTR_OFF
      party = read_hex(addr, n * PARTY_SLOT_SIZE)
      bag = read_hex(ptr + BAG_PTR_OFF, BAG_SIZE)
      box = read_hex(ptr + BOX1_PTR_OFF, BOX1_SIZE)
      trainer = read_hex(ptr + TRAINER_PTR_OFF, TRAINER_SIZE)
    elseif addr ~= nil and mode == "battle" then
      battle = battle_hex(addr - PARTY_PTR_OFF)
    end
    comm.socketServerSend(string.format("POLL %s 0x%08x %s %s %s %s %s:%04x %s", mode, addr or 0, party, bag, box, trainer,
                                        code:gsub("[^%w]", "_"), crc, battle))
    handle(comm.socketServerResponse())
    gui.text(4, 4, "puente: " .. mode)
    if game == nil then gui.text(4, 20, "juego no soportado: " .. code .. " (no se escribe nada)") end
  end
  emu.frameadvance()
end
