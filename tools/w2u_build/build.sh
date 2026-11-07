#!/bin/sh
# Compila White2Upgrade dentro del contenedor.
#   /src  = tu copia de White2Upgrade (solo lectura; se clona de nuevo para tener finales de línea de Linux)
#   /rom  = carpeta con la ROM de White 2 USA (IRDO)
#   /patches = (opcional) parches .cpp propios que se añaden a src/
#   /out  = donde se deja White2Upgrade.nds (con el ARM9 marcado como no comprimido: si no, se queda en blanco)
# Ver docs/DOCUMENTACION.md, "White2Upgrade compilado".
set -e
# La ROM: $ROM_NAME si se pasa (docker run -e ROM_NAME=...), si no el nombre habitual o la única .nds de /rom
ROM="/rom/${ROM_NAME:-Pokemon - White Version 2 (USA, Europe) (NDSi Enhanced).nds}"
if [ ! -f "$ROM" ]; then
    set -- /rom/*.nds
    [ "$#" -eq 1 ] && [ -f "$1" ] || { echo "[w2u] no encuentro la ROM: usa -e ROM_NAME=archivo.nds"; exit 1; }
    ROM="$1"
fi
echo "[w2u] SHA-256 de la ROM (debe ser 3e50aec3...)"
sha256sum "$ROM"
rm -rf /work/w2u
git config --global --add safe.directory '*'
git -c core.autocrlf=false clone -q /src /work/w2u
cd /work/w2u
for m in swan extlib NitroKernel; do
    rm -rf "include/$m"
    git -c core.autocrlf=false clone -q "/src/include/$m" "include/$m"
done
# Parches propios (tools/w2u_build/patches, montado en /patches): se compilan junto al código de White2Upgrade
if [ -d /patches ]; then
    for f in /patches/*.cpp; do [ -f "$f" ] && cp "$f" src/ && echo "[w2u] parche: $(basename "$f")"; done
    # Símbolos que White2Upgrade no nombra (*.esdb.yml: entradas "- Name/Segment/Address" que se añaden al final de la
    # lista Symbols de pmc/ESDB.yml, para poder engancharse a esas funciones)
    for f in /patches/*.esdb.yml; do
        [ -f "$f" ] || continue
        echo >> pmc/ESDB.yml          # por si el archivo no acaba en salto de línea
        cat "$f" >> pmc/ESDB.yml && echo "[w2u] símbolos: $(basename "$f")"
    done
fi
mkdir -p tools/CTRMap
cp /src/tools/CTRMap/CTRMap.jar tools/CTRMap/
cp "$ROM" IRDO.nds
echo "[w2u] herramientas";      make tools
echo "[w2u] extraer la ROM";    make base
echo "[w2u] compilar";          make -j"$(nproc)"
echo "[w2u] ARM9 sin comprimir"; python3 /fix_arm9.py White2Upgrade.nds
cp White2Upgrade.nds /out/White2Upgrade.nds
cp White2Upgrade_DEBUG.txt /out/White2Upgrade_DEBUG.txt 2>/dev/null || true   # volcado del módulo: qué parches entraron
echo "[w2u] listo: /out/White2Upgrade.nds"
