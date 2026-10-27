"""Datos del juego (especies, experiencia, movimientos, PP, nombres) en gen5_data.json.

El archivo se genera desde la ROM de cada persona con rom.py, así funciona con ROM
aleatorizadas y en cualquier idioma. DATA se actualiza en el sitio con load(), para que
los módulos que lo importan vean siempre los datos actuales.
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen5_data.json")
DATA: dict = {}


def load(path: str = PATH) -> dict:
    DATA.clear()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            DATA.update(json.load(f))
    return DATA


def rom_info() -> dict:
    """{"code", "header_crc", ...} de la ROM de la que salen los datos, o {} si son de PKHeX."""
    return DATA.get("rom", {})


load()
