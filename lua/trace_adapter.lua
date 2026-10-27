-- trace_adapter.lua — investigación (fase 5, opción A): registra frame a frame la comunicación entre
-- la lógica del combate (servidor) y la pantalla (cliente del jugador) en White 2 (IRDO).
-- Se abre en la Lua Console junto a connector.lua, durante un combate. Guarda dumps/trace_adapter.txt.
-- Direcciones: showdown-bw2 (Black 2) + 0x40, confirmadas con los volcados combate1/combate2.

local DOMAIN = "Main RAM"
local BASE = 0x02000000
local S_ADAPTERS = 0x021DD8AC        -- BtlAdapter *sAdapters[4]
local MAIN_PROC = 0x021B1A15         -- BattleClient_MainProcNormal (Thumb)
-- Adaptador: +0x04 returnData, +0x08 returnSize, +0x0C returned, +0x10 cmd (u16), +0x12 size (u16), +0x14 datos
-- Cliente:   +0x00 mainModule, +0x28 mainProc, +0x50 adaptador, +0x1AF tipo, +0x1B0 mainSeq

local function script_dir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then src = src:sub(2) end
  return src:match("^(.*[/\\])") or ""
end
local OUT = script_dir() .. "../dumps/trace_adapter.txt"

local function u8(a) return memory.read_u8(a - BASE, DOMAIN) end
local function u16(a) return memory.read_u16_le(a - BASE, DOMAIN) end
local function u32(a) return memory.read_u32_le(a - BASE, DOMAIN) end
local function is_ram(p) return p >= BASE and p < BASE + 0x400000 end

-- El cliente del jugador apunta a su adaptador en +0x50; se busca cerca del adaptador
local function find_client(adapter)
  for delta = -0x2000, 0x2000, 4 do
    local c = adapter + delta
    if is_ram(c) and u32(c + 0x50) == adapter and u32(c + 0x28) == MAIN_PROC and u8(c + 0x1AF) == 0 then return c end
  end
  return nil
end

local f = io.open(OUT, "w")
f:write("frame;adaptador;cmd;returned;size;mainSeq;datos(primeros 24 bytes)\n")
console.log("trace_adapter.lua: registrando en " .. OUT)

local last, client, adapter = "", nil, nil
event.onexit(function() if f then f:close() end end)

while true do
  local a = u32(S_ADAPTERS)
  if is_ram(a) then
    if a ~= adapter then adapter = a; client = find_client(a) end
    local data = {}
    for i = 0, 23 do data[#data + 1] = string.format("%02x", u8(a + 0x14 + i)) end
    local line = string.format("%08x;%d;%x;%d;%s;%s", a, u16(a + 0x10), u8(a + 0x0C), u16(a + 0x12),
      client and tostring(u8(client + 0x1B0)) or "?", table.concat(data))
    if line ~= last then
      f:write(emu.framecount() .. ";" .. line .. "\n"); f:flush()
      last = line
    end
  end
  emu.frameadvance()
end
