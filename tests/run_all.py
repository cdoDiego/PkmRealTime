"""Ejecuta todas las pruebas: python tests/run_all.py"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
failed = []
for name in sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py")):
    print(f"== {name}")
    if subprocess.run([sys.executable, os.path.join(HERE, name)]).returncode != 0:
        failed.append(name)
print("\nTODO OK" if not failed else f"\nFALLARON: {', '.join(failed)}")
sys.exit(1 if failed else 0)
