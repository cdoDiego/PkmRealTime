// Código común de las páginas del overlay: conexión con el puente, datos de ejemplo y textos.
"use strict";

const params = new URLSearchParams(location.search);
let TOKEN = params.get("token") || "";

// Si falta el token (o no sirve), lo pide al puente; solo funciona abriendo la página en la misma computadora.
async function ensureToken() {
  if (TOKEN) {
    const r = await fetch("/state", { headers: { "X-Token": TOKEN } });
    if (r.status !== 401) return true;
  }
  const r = await fetch("/overlay-token");
  if (!r.ok) return false;
  TOKEN = (await r.json()).token;
  params.set("token", TOKEN);
  history.replaceState(null, "", `${location.pathname}?${params}`);
  return true;
}

// Sprites de Gen 5 (proyecto PokeAPI/sprites). Si no hay internet, se ve el número.
const SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-v/black-white/";
function spriteUrl(mon, animated) {
  const shiny = mon.shiny ? "shiny/" : "";
  return animated ? `${SPRITE_BASE}animated/${shiny}${mon.species}.gif` : `${SPRITE_BASE}${shiny}${mon.species}.png`;
}

const STATUS = {
  paralysis: ["PAR", "#d8b023"], sleep: ["DOR", "#8c8c9c"], freeze: ["CON", "#5fb7d6"],
  burn: ["QUE", "#e0653a"], poison: ["ENV", "#9b59b6"], toxic: ["ENV", "#7d3c98"],
};

function monName(mon, mode) {
  if (mon.egg) return "Huevo";
  if (mode === "species") return mon.name || `#${mon.species}`;
  return mon.nickname || mon.name || `#${mon.species}`;
}

// Texto de cada aviso del puente (GET /happenings, "kind": "happening"); null = no se muestra
function happeningText(h) {
  const n = h.name || "";
  switch (h.type) {
    case "caught": return { icon: "●", text: `¡${n} capturado${h.met_place ? " en " + h.met_place : ""}!`, tone: "good" };
    case "obtained": return h.egg ? { icon: "◒", text: "¡Recibiste un huevo!", tone: "good" }
                                  : { icon: "★", text: `¡${n} se unió al equipo!`, tone: "good" };
    case "fainted": return { icon: "✖", text: `${n} se debilitó`, tone: "bad" };
    case "revived": return { icon: "✚", text: `${n} se recuperó`, tone: "good" };
    case "level_up": return { icon: "▲", text: `${n} subió al nivel ${h.level}`, tone: "info" };
    case "evolved": return { icon: "✦", text: `¡${h.from_name} evolucionó en ${n}!`, tone: "good" };
    case "hatched": return { icon: "◒", text: `¡Eclosionó ${n}!`, tone: "good" };
    case "badge": return { icon: "◆", text: `¡Medalla ${h.badge} obtenida! (${h.count}/8)`, tone: "good" };
    case "left": return { icon: "↗", text: `${n} dejó el equipo`, tone: "info" };
    default: return null;   // zone, moved, battle_start, battle_end: se ven en los otros bloques
  }
}

// Datos de ejemplo para configurar el overlay sin el juego abierto
const DEMO_STATE = {
  connected: true, mode: "map", badges: 3, money: 12840,
  location: { zone: 446, name: "Route 20", season: "summer" },
  party: [
    { species: 501, name: "Oshawott", nickname: "Oshawott", level: 18, hp: 52, max_hp: 52, status: "none" },
    { species: 25, name: "Pikachu", nickname: "Chispa", level: 16, hp: 18, max_hp: 41, status: "paralysis", shiny: true },
    { species: 509, name: "Purrloin", nickname: "Purrloin", level: 12, hp: 0, max_hp: 34, status: "none" },
    { species: 1, name: "Bulbasaur", nickname: "Bulbasaur", level: 14, hp: 9, max_hp: 39, status: "poison" },
    { species: 133, name: "Eevee", nickname: "Eevee", level: 20, hp: 53, max_hp: 53, status: "none" },
    { species: 0, egg: true, level: 1, hp: 0, max_hp: 0, status: "none" },
  ],
};
const DEMO_HAPPENINGS = [
  { type: "caught", name: "Sewaddle", met_place: "Route 20" },
  { type: "level_up", name: "Eevee", level: 21 },
  { type: "fainted", name: "Purrloin" },
  { type: "evolved", name: "Dewott", from_name: "Oshawott" },
  { type: "badge", badge: 4, count: 4 },
];

// Conecta con el puente y llama a onState(state) y onHappening(h). Se reconecta solo.
function connectBridge({ onState, onHappening, onStatus, onRoulette, demo }) {
  if (demo) {
    onStatus && onStatus("demo");
    onState && onState(DEMO_STATE);
    let i = 0;
    setInterval(() => onHappening && onHappening(DEMO_HAPPENINGS[i++ % DEMO_HAPPENINGS.length]), 4000);
    return;
  }
  let retry = 1000, fixed = false;
  async function open() {
    if (!fixed) { fixed = true; try { await ensureToken(); } catch (e) {} }
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?token=${encodeURIComponent(TOKEN)}`;
    const ws = new WebSocket(url);
    ws.onopen = () => { retry = 1000; onStatus && onStatus("ok"); };
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.kind === "state") onState(msg.state);
      else if (msg.kind === "happening") onHappening && onHappening(msg.happening);
      else if (msg.kind === "roulette") onRoulette && onRoulette(msg);
    };
    ws.onclose = (e) => {
      onStatus && onStatus(e.code === 4401 ? "token" : "off");
      if (e.code === 4401) fixed = false;
      setTimeout(open, retry);
      retry = Math.min(retry * 2, 10000);
    };
  }
  open();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
