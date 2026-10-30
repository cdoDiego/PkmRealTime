"""Pruebas de effects.py, roulette.py y del giro en el puente (sin juego): python tests/test_roulette.py"""
import asyncio, os, random, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bridge, effects, roulette

rng = random.Random(5)
mon = lambda sp, lvl, hp=20, **k: {"species": sp, "name": f"sp{sp}", "nickname": "", "level": lvl, "hp": hp, "max_hp": 30,
                                   "status": "none", "valid": True, "egg": False, **k}
game = {"party": [mon(501, 10), mon(25, 20), mon(1, 30, hp=0), mon(0, 1, egg=True)]}

# todos los efectos dan eventos que el puente acepta (EventIn los valida)
for eid in effects.EFFECTS:
    for _ in range(20):
        text, evs = effects.apply(eid, game, rng)
        assert text, eid
        for e in evs:
            bridge.EventIn(**e)

# objetivos: nunca huevos ni debilitados; "debilitar" no deja a nadie sin poder luchar
for _ in range(50):
    _, evs = effects.apply("paralizar", game, rng)
    assert evs[0]["target"]["slot"] in (0, 1)
    _, evs = effects.apply("debilitar", game, rng)
    assert evs[0]["target"]["slot"] in (0, 1)
_, evs = effects.apply("debilitar", {"party": [mon(1, 5), mon(4, 5, hp=0)]}, rng)
assert evs == []                                                  # solo uno en pie: se salva
_, evs = effects.apply("envenenar", game, rng)
assert sorted(e["target"]["slot"] for e in evs) == [0, 1]
_, evs = effects.apply("pokemon", game, rng)
assert evs[0]["level"] == 20 and 1 <= evs[0]["species"] <= 649   # nivel medio de 10, 20 y 30
_, evs = effects.apply("salvaje", {"party": []}, rng)
assert evs[0]["level"] == 7                                       # sin equipo: nivel 5 + 2

# premios: limpieza, guardado y elección por peso
prizes = effects.default_prizes()
assert roulette.clean(prizes) == prizes
try:
    roulette.clean([{"effect": "curar", "weight": 0}])
    raise AssertionError("sin premios activos debe fallar")
except ValueError:
    pass
try:
    roulette.clean([{"effect": "no_existe"}])
    raise AssertionError("efecto desconocido debe fallar")
except ValueError:
    pass
roulette.PATH = os.path.join(tempfile.mkdtemp(), "roulette.json")
assert roulette.load() == prizes                                  # sin archivo: los de fábrica
two = [{"effect": "curar", "label": "A" * 40, "weight": 3, "enabled": True},
       {"effect": "nada", "label": "", "weight": 99, "enabled": True},
       {"effect": "caramelo", "label": "x", "weight": 5, "enabled": False}]
saved = roulette.save(two)
assert saved[0]["label"] == "A" * roulette.MAX_LABEL and saved[1]["label"] == "Nada" and saved[1]["weight"] == 10
assert roulette.load() == saved
counts = [0, 0]
for _ in range(4000):
    segs, idx = roulette.pick(saved, rng)
    assert len(segs) == 2
    counts[idx] += 1
assert 0.15 < counts[0] / 4000 < 0.30, counts                     # 3 de 13

# giro completo en el puente: aviso "spin", espera, premio aplicado (evento encolado) y aviso "done"
roulette.SPIN_SECONDS = 0.05
roulette.save([{"effect": "curar", "label": "Curar", "weight": 1, "enabled": True}])
bridge.game["party"] = game["party"]
sent = []


async def fake_broadcast(msg):
    sent.append(msg)
bridge.broadcast = fake_broadcast


async def run():
    bridge.roulette_queue = asyncio.Queue()
    worker = asyncio.create_task(bridge.roulette_worker())
    bridge.roulette_queue.put_nowait("prueba")
    for _ in range(100):
        if any(m.get("phase") == "done" for m in sent):
            break
        await asyncio.sleep(0.02)
    worker.cancel()
asyncio.run(run())
phases = [m["phase"] for m in sent if m["kind"] == "roulette"]
assert phases == ["spin", "done"], phases
done = sent[-1]["spin"]
assert done["label"] == "Curar" and done["source"] == "prueba" and len(done["events"]) == 1
assert bridge.events[done["events"][0]].data["type"] == "heal"
print("OK")
