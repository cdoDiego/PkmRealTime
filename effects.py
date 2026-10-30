"""Catálogo de efectos con nombre: lo que puede pasar al ganar un premio (ruleta; luego Twitch y cartas).

Cada efecto tiene un texto en español y una función que, con el estado actual del juego, devuelve:
  (texto del resultado, [eventos para /events])
Los objetivos al azar (qué Pokémon, qué especie) se eligen al aplicarlo, no al configurarlo.
"""
import random

import field_script
import gamedata

MAX_SPECIES = 649
# Ciudades a las que se puede viajar (sin Ciudad Negra ni Bosque Blanco: dependen de la versión y del avance)
TELEPORT_CITIES = ["aspertia", "virbank", "castelia", "nimbasa", "driftveil", "mistralton", "icirrus", "opelucid",
                   "lacunosa", "undella", "humilau", "nacrene", "striaton", "accumula", "nuvema"]


def species_name(n: int) -> str:
    return gamedata.DATA.get("species", {}).get(str(n), {}).get("name") or f"#{n}"


def item_name(n: int) -> str:
    items = gamedata.DATA.get("items") or []
    return items[n] if 0 <= n < len(items) else f"objeto {n}"


def _party(game: dict) -> list:
    """(hueco, Pokémon) del equipo que existen y no son huevos."""
    return [(i, m) for i, m in enumerate(game.get("party") or []) if m.get("valid", True) and not m.get("egg")]


def _able(game: dict) -> list:
    return [(i, m) for i, m in _party(game) if m.get("hp", 0) > 0]


def _avg_level(game: dict) -> int:
    mons = _party(game)
    return max(1, round(sum(m.get("level", 5) for _, m in mons) / len(mons))) if mons else 5


def _who(m: dict) -> str:
    return m.get("nickname") or m.get("name") or f"#{m.get('species')}"


def _nothing(game, rng):
    return "Nada esta vez… ¡suerte la próxima!", []


def _heal(game, rng):
    return "¡Equipo curado por completo!", [{"type": "heal"}]


def _items(item: int, qty: int):
    def f(game, rng):
        return f"¡{qty} × {item_name(item)} a la mochila!", [{"type": "give_item", "item": item, "qty": qty}]
    return f


def _money(amount: int):
    def f(game, rng):
        if amount >= 0:
            return f"¡+{amount:,} ₽!".replace(",", "."), [{"type": "give_money", "qty": amount}]
        return f"¡-{-amount:,} ₽!".replace(",", "."), [{"type": "take_money", "qty": -amount}]
    return f


def _random_pokemon(shiny: bool):
    def f(game, rng):
        sp, lvl = rng.randint(1, MAX_SPECIES), _avg_level(game)
        txt = f"¡{species_name(sp)}{' variocolor' if shiny else ''} (Nv. {lvl}) a la caja 1!"
        return txt, [{"type": "give_pokemon", "species": sp, "level": lvl, "shiny": shiny}]
    return f


def _status_one(status: str, text: str):
    def f(game, rng):
        mons = [(i, m) for i, m in _able(game) if m.get("status", "none") == "none"]
        if not mons:
            return "Nadie a quien afectar: ¡te salvaste!", []
        i, m = rng.choice(mons)
        return text.format(_who(m)), [{"type": "set_status", "status": status, "target": {"slot": i}}]
    return f


def _poison_all(game, rng):
    mons = [(i, m) for i, m in _able(game) if m.get("status", "none") == "none"]
    if not mons:
        return "Nadie a quien envenenar: ¡te salvaste!", []
    return "¡Todo el equipo envenenado!", [{"type": "set_status", "status": "poison", "target": {"slot": i}} for i, _ in mons]


def _faint_one(game, rng):
    mons = _able(game)
    if len(mons) < 2:   # nunca deja el equipo sin nadie que pueda luchar
        return "Solo te queda uno en pie: ¡se salvó!", []
    i, m = rng.choice(mons)
    return f"¡{_who(m)} se debilitó!", [{"type": "set_hp", "hp": 0, "target": {"slot": i}}]


def _wild_battle(game, rng):
    sp, lvl = rng.randint(1, MAX_SPECIES), min(100, _avg_level(game) + 2)
    return f"¡Un {species_name(sp)} salvaje (Nv. {lvl}) te ataca!", [{"type": "start_wild_battle", "species": sp, "level": lvl}]


def _weather(weather: str, text: str):
    def f(game, rng):
        return text, [{"type": "set_weather", "weather": weather}]
    return f


def _teleport(game, rng):
    city = rng.choice(TELEPORT_CITIES)
    return f"¡Viaje sorpresa a {city.capitalize()}!", [{"type": "teleport", "zone": city}]


# id -> (nombre corto para la rueda, descripción, función, peso por defecto, activo por defecto)
EFFECTS = {
    "nada": ("Nada", "No pasa nada", _nothing, 3, True),
    "curar": ("Curar equipo", "Cura vida, estado y PP de todo el equipo", _heal, 3, True),
    "pokeballs": ("5 Poké Balls", "5 Poké Balls a la mochila", _items(4, 5), 3, True),
    "ultraballs": ("3 Ultra Balls", "3 Ultra Balls a la mochila", _items(2, 3), 2, True),
    "masterball": ("Master Ball", "1 Master Ball a la mochila", _items(1, 1), 1, False),
    "caramelo": ("Caramelo raro", "1 Caramelo Raro a la mochila", _items(50, 1), 2, True),
    "revivir": ("2 Revivir", "2 Revivir a la mochila", _items(28, 2), 2, True),
    "dinero_mas": ("+5.000 ₽", "Gana 5.000 ₽", _money(5000), 2, True),
    "dinero_menos": ("-3.000 ₽", "Pierde 3.000 ₽", _money(-3000), 2, True),
    "pokemon": ("Pokémon al azar", "Un Pokémon al azar del nivel medio del equipo, a la caja 1", _random_pokemon(False), 2, True),
    "shiny": ("Variocolor al azar", "Un Pokémon variocolor al azar, a la caja 1", _random_pokemon(True), 1, False),
    "paralizar": ("Parálisis", "Paraliza a un Pokémon al azar del equipo", _status_one("paralysis", "¡{} quedó paralizado!"), 2, True),
    "dormir": ("Sueño", "Duerme a un Pokémon al azar del equipo", _status_one("sleep", "¡{} se durmió!"), 2, True),
    "envenenar": ("Veneno a todos", "Envenena a todo el equipo", _poison_all, 1, True),
    "debilitar": ("Debilitar a uno", "Debilita a un Pokémon al azar (nunca al último en pie)", _faint_one, 1, False),
    "salvaje": ("Combate salvaje", "Un Pokémon salvaje al azar te ataca (2 niveles más que tu media)", _wild_battle, 2, True),
    "lluvia": ("Lluvia", "Empieza a llover en el mapa", _weather("rain", "¡Empieza a llover!"), 1, True),
    "nieve": ("Nieve", "Empieza a nevar en el mapa", _weather("snow", "¡Empieza a nevar!"), 1, True),
    "viaje": ("Viaje sorpresa", "Te lleva a una ciudad al azar", _teleport, 1, False),
}
assert all(c in field_script.CITIES for c in TELEPORT_CITIES)


def catalog() -> list:
    return [{"id": k, "label": v[0], "description": v[1]} for k, v in EFFECTS.items()]


def default_prizes() -> list:
    return [{"effect": k, "label": v[0], "weight": v[3], "enabled": v[4]} for k, v in EFFECTS.items()]


def apply(effect: str, game: dict, rng=random) -> tuple:
    """(texto del resultado, eventos) para el estado actual del juego."""
    if effect not in EFFECTS:
        raise ValueError(f"efecto desconocido: {effect}")
    return EFFECTS[effect][2](game, rng)
