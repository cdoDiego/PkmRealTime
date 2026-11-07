// Protección de la Pokédex del guardado (PkmRealTime, 06-nov).
//
// White2Upgrade llega a la especie 721, pero el bloque de la Pokédex del guardado sigue teniendo listas de 0x54 bytes:
// 672 especies. Ver o capturar una de la 673 en adelante escribe bits fuera de su lista y pisa las de al lado.
//
// Estas funciones empiezan comprobando la especie con PML_PkmIsBadMonsNo (que White2Upgrade amplía hasta la 721).
// Aquí se desvía solo esa llamada (THUMB_BRANCH_LINK_<función>_<desplazamiento> = la instrucción BL que hay en esa
// posición) para que, en ellas, las especies que no caben en el guardado también cuenten como "no válidas":
//   - PokeDex_RegistPkm (+0x6C) y addPkmToDex (+0x76): no se apuntan como vistas ni capturadas;
//   - PokeDex_IsSeen (+0x8) y PokeDex_IsCaught (+0x8): dicen "no" en vez de leer bits de otra lista.
// Las especies 673-721 se pueden ver, capturar y usar; solo no aparecen en la Pokédex. Desplazamientos medidos en el
// ARM9 de PMC (pmc/ARM9PMC.bin), que en estas funciones es igual que el de W2 USA.

#include "swantypes.h"

#define DEX_SAVE_SPECIES_MAX 672   // 0x54 bytes * 8 bits por lista

extern "C" bool PML_PkmIsBadMonsNo(u32 species);

static bool badForDexSave(u32 species) {
    return species > DEX_SAVE_SPECIES_MAX || PML_PkmIsBadMonsNo(species);
}

extern "C" {
    bool THUMB_BRANCH_LINK_PokeDex_RegistPkm_0x6c(u32 species) { return badForDexSave(species); }
    bool THUMB_BRANCH_LINK_addPkmToDex_0x76(u32 species) { return badForDexSave(species); }
    bool THUMB_BRANCH_LINK_PokeDex_IsSeen_0x8(u32 species) { return badForDexSave(species); }
    bool THUMB_BRANCH_LINK_PokeDex_IsCaught_0x8(u32 species) { return badForDexSave(species); }
}
