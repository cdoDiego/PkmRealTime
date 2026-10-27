-- trace_faint.lua — investigación (fase 5): ¿puede BizHawk (melonDS) avisar cuando el juego ejecuta una función?
-- Registra cada llamada a ServerControl_CheckFainted, la función de la lógica del combate que decide si un Pokémon
-- se debilita. Se abre en la Lua Console junto a connector.lua, durante un combate. Guarda dumps/trace_faint.txt.
-- Dirección: símbolos de pokebw2 para Black 2 (0x021A8A24) + 0x40, comprobada en los volcados de combate.

local CHECK_FAINTED = 0x021A8A64   -- BOOL ServerControl_CheckFainted(BtlServerFlow *flow, BattleMon *mon)
local DOMAIN = "Main RAM"
local BASE = 0x02000000

local function script_dir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then src = src:sub(2) end
  return src:match("^(.*[/\\])") or ""
end
local OUT = script_dir() .. "../dumps/trace_faint.txt"
local f = io.open(OUT, "w")
local hits, first = 0, true

local function reg(regs, names)
  for _, n in ipairs(names) do
    if regs[n] ~= nil then return regs[n], n end
  end
  return nil
end

local function on_exec()
  hits = hits + 1
  local regs = emu.getregisters()
  if first then
    -- nombres de los registros que da este núcleo (para saber cómo leer r1)
    local names = {}
    for k, _ in pairs(regs) do names[#names + 1] = k end
    table.sort(names)
    f:write("registros: " .. table.concat(names, ", ") .. "\n")
    first = false
  end
  local mon, name = reg(regs, {"ARM9 r1", "ARM9 R1", "R1", "r1"})
  local line = string.format("frame %d: llamada %d", emu.framecount(), hits)
  if mon then
    line = line .. string.format(" | %s = %08X", name, mon)
    if mon >= BASE and mon < BASE + 0x400000 then
      local hp = memory.read_u16_le(mon - BASE + 0x10, DOMAIN)
      local species = memory.read_u16_le(mon - BASE + 0x0C, DOMAIN)
      line = line .. string.format(" | especie %d, HP %d", species, hp)
    end
  end
  f:write(line .. "\n"); f:flush()
end

local ok, err = pcall(function()
  event.on_bus_exec(on_exec, CHECK_FAINTED, "trace_faint")
end)
if ok then
  console.log("trace_faint.lua: escuchando CheckFainted; registro en " .. OUT)
else
  console.log("trace_faint.lua: este núcleo no admite avisos de ejecución: " .. tostring(err))
  f:write("sin soporte: " .. tostring(err) .. "\n"); f:close()
  return
end

event.onexit(function() event.unregisterbyname("trace_faint"); if f then f:close() end end)
while true do
  gui.text(10, 10, "trace_faint: " .. hits .. " llamadas")
  emu.frameadvance()
end
