-- watch_ram.lua — muestra en pantalla el valor de varias direcciones mientras juegas.
-- Se abre en la Lua Console junto a connector.lua. Edita la lista para probar otras.
-- Cada entrada: {dirección o offset, etiqueta, relativa_al_puntero}

local DOMAIN = "Main RAM"
local BASE = 0x02000000

local WATCH = {
  {0x0223B2F5, "menu (direccion fija)", false},
  {0x365F1,    "menu (puntero+0x365F1)", true},
}

while true do
  local ptr = memory.read_u32_le(0x24, DOMAIN) % 0x1000000
  gui.text(4, 20, string.format("puntero %08X", BASE + ptr))
  for i, w in ipairs(WATCH) do
    local off = w[3] and (ptr + w[1]) or (w[1] - BASE)
    local v = memory.read_u8(off, DOMAIN)
    gui.text(4, 20 + i * 16, string.format("%08X = %3d  %s", BASE + off, v, w[2]))
  end
  emu.frameadvance()
end
