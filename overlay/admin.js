// Común a las páginas de configuración: pastillas de estado del puente y del juego.
"use strict";

function setPill(id, ok, text) {
  const p = document.getElementById(id);
  if (!p) return;
  p.className = "pill " + (ok ? "ok" : "bad");
  p.lastChild.textContent = text;
}

// Revisa el puente cada 3 s. onToken() se llama si el token se rellenó solo (para rehacer las direcciones).
function watchStatus(onToken) {
  async function poll(retried) {
    try {
      const r = await fetch("/state", { headers: { "X-Token": TOKEN } });
      if (r.status === 401) {
        if (!retried && await ensureToken().catch(() => false)) { fixNavLinks(); onToken && onToken(); return poll(true); }
        setPill("st-bridge", false, "Puente: token incorrecto (abre esta página en la computadora del puente)");
        setPill("st-game", false, "Juego: —");
        return;
      }
      const s = await r.json();
      setPill("st-bridge", true, "Puente conectado");
      setPill("st-game", s.connected, s.connected ? `Juego conectado${s.location ? " · " + s.location.name : ""}`
                                                  : "Juego sin conectar (abre connector.lua en BizHawk)");
    } catch (e) {
      setPill("st-bridge", false, "Puente apagado (ejecuta bridge.py)");
      setPill("st-game", false, "Juego: —");
    }
  }
  poll();
  setInterval(poll, 3000);
}

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
                                body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `error ${r.status}`);
  return data;
}

function copyButton(btnId, inputId, okId) {
  document.getElementById(btnId).addEventListener("click", async () => {
    const box = document.getElementById(inputId);
    try { await navigator.clipboard.writeText(box.value); } catch (e) { box.select(); document.execCommand("copy"); }
    const c = document.getElementById(okId); c.hidden = false; setTimeout(() => c.hidden = true, 2000);
  });
}

// Los enlaces entre páginas conservan el token de la dirección
function fixNavLinks() {
  document.querySelectorAll("nav a").forEach(a => {
    const u = new URL(a.href);
    u.searchParams.set("token", TOKEN);
    a.href = u;
  });
}
document.addEventListener("DOMContentLoaded", fixNavLinks);
