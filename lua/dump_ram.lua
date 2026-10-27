-- dump_ram.lua — guarda la Main RAM en un archivo para analizarla con tools/ram_tool.py.
-- Se puede abrir en la Lua Console junto a connector.lua (corren los dos a la vez).
-- Escribe un nombre (ej. mapa1, menu1) y pulsa "Volcar". Se guarda en la carpeta dumps/ del proyecto.

local DOMAIN = "Main RAM"

-- Carpeta de este script (lua/) -> ../dumps/. Si no funcionara en tu BizHawk, pon aquí una ruta absoluta
-- terminada en "/", por ejemplo "C:/ruta/al/proyecto/dumps/".
local function script_dir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then src = src:sub(2) end
  return src:match("^(.*[/\\])") or ""
end
local OUT_DIR = script_dir() .. "../dumps/"
console.log("dump_ram.lua: los volcados se guardan en " .. OUT_DIR)
local CHUNK = 0x10000

local pending = nil
local form = forms.newform(260, 110, "Volcar RAM")
local box = forms.textbox(form, "mapa1", 140, 20, nil, 10, 10)
forms.button(form, "Volcar", function() pending = forms.gettext(box) end, 160, 8, 70, 24)
local status = forms.label(form, "listo", 10, 45, 230, 20)
event.onexit(function() forms.destroy(form) end)

local function dump(name)
  local size = memory.getmemorydomainsize(DOMAIN)
  local f, err = io.open(OUT_DIR .. name .. ".bin", "wb")
  if not f then forms.settext(status, "error: " .. tostring(err)); return end
  for addr = 0, size - 1, CHUNK do
    local t = memory.read_bytes_as_array(addr, CHUNK, DOMAIN)
    local first = (t[0] ~= nil) and 0 or 1      -- la tabla puede empezar en 0 o en 1
    local parts = {}
    for i = 0, CHUNK - 1, 4096 do                -- unpack por trozos (límite de argumentos)
      parts[#parts + 1] = string.char(table.unpack(t, first + i, first + i + 4095))
    end
    f:write(table.concat(parts))
  end
  f:close()
  forms.settext(status, "guardado " .. name .. ".bin (frame " .. emu.framecount() .. ")")
  console.log("RAM guardada en " .. OUT_DIR .. name .. ".bin")
end

while true do
  if pending then
    local name = pending:gsub("[^%w_%-]", "")
    pending = nil
    if name ~= "" then dump(name) end
  end
  emu.frameadvance()
end
