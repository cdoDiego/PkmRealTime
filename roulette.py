"""Ruleta: lista de premios (efecto + nombre + peso) guardada en roulette.json y elección al azar por peso.

El archivo lo escribe la página de configuración del overlay; nadie tiene que editarlo a mano.
"""
import json
import os
import random

import effects

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roulette.json")
SPIN_SECONDS = 7          # lo que tarda la rueda en pararse en el overlay; el efecto se aplica al terminar
MAX_LABEL = 24
MAX_WEIGHT = 10


def clean(prizes: list) -> list:
    """Premios válidos: efecto conocido, nombre corto, peso 0-10. Lanza ValueError si no queda ninguno activo."""
    out = []
    for p in prizes:
        if not isinstance(p, dict) or p.get("effect") not in effects.EFFECTS:
            raise ValueError(f"premio no válido: {p}")
        label = str(p.get("label") or effects.EFFECTS[p["effect"]][0]).strip()[:MAX_LABEL]
        weight = max(0, min(MAX_WEIGHT, int(p.get("weight", 1))))
        out.append({"effect": p["effect"], "label": label, "weight": weight, "enabled": bool(p.get("enabled", True))})
    if not active(out):
        raise ValueError("la ruleta necesita al menos un premio activo con peso mayor que 0")
    return out


def active(prizes: list) -> list:
    return [p for p in prizes if p["enabled"] and p["weight"] > 0]


def load() -> list:
    try:
        with open(PATH, encoding="utf-8") as f:
            return clean(json.load(f)["prizes"])
    except (OSError, ValueError, KeyError, TypeError):
        return effects.default_prizes()


def save(prizes: list) -> list:
    prizes = clean(prizes)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump({"prizes": prizes}, f, ensure_ascii=False, indent=1)
    return prizes


def pick(prizes: list, rng=random) -> tuple:
    """(segmentos de la rueda, índice ganador). Cada premio activo es un segmento; el peso decide la probabilidad."""
    segs = active(prizes)
    idx = rng.choices(range(len(segs)), weights=[p["weight"] for p in segs])[0]
    return segs, idx
