// Profundidad de las piezas de los sprites convertidos (PkmRealTime, 07-nov).
//
// El combate dibuja cada sprite pieza a pieza (MCSS_DrawQuad) y, tras cada una, deja la siguiente 1 píxel más al fondo:
// así las partes de los sprites originales (10-29 piezas que se solapan) quedan en el orden correcto. Los sprites que
// convierte tools/sprites_gen5.py son una rejilla de 30-120 piezas que no se solapan: la última queda hasta 120 píxeles
// más al fondo y, cuando la cámara se acerca (captura, algunos ataques), la perspectiva separa las filas en franjas.
//
// Aquí se desvían las 3 llamadas de MCSSSys_Draw a MCSS_DrawQuad: si la pieza es de un sprite convertido, la profundidad
// no avanza. sprites_gen5.py marca sus piezas con un desplazamiento x de 1/4096 de píxel (byte bajo = 0x01, invisible);
// en los 649 originales ese byte siempre es 0, así que se dibujan exactamente igual que antes.
// Direcciones en patches/mcss.esdb.yml (W2 USA; el ARM9 de PMC es igual en estas funciones).

#include "swantypes.h"

#define CONVERTED_PIECE_MARK 0x01   // byte bajo de quad.x en las piezas de sprites_gen5.py

extern "C" void MCSS_DrawQuad(void *system, void *mcss, s32 x, s32 y, s32 width, s32 height, s32 s, s32 t,
                              const void *cellSrt, const void *mcSrt, void *shadowPltt, int node, int ortho, s32 *z,
                              u8 flip);

static void drawQuad(void *system, void *mcss, s32 x, s32 y, s32 width, s32 height, s32 s, s32 t, const void *cellSrt,
                     const void *mcSrt, void *shadowPltt, int node, int ortho, s32 *z, u8 flip) {
    s32 before = *z;
    MCSS_DrawQuad(system, mcss, x, y, width, height, s, t, cellSrt, mcSrt, shadowPltt, node, ortho, z, flip);
    if ((x & 0xFF) == CONVERTED_PIECE_MARK) {
        *z = before;
    }
}

#define DRAW_QUAD_HOOK(name)                                                                                          \
    void name(void *system, void *mcss, s32 x, s32 y, s32 width, s32 height, s32 s, s32 t, const void *cellSrt,      \
              const void *mcSrt, void *shadowPltt, int node, int ortho, s32 *z, u8 flip) {                            \
        drawQuad(system, mcss, x, y, width, height, s, t, cellSrt, mcSrt, shadowPltt, node, ortho, z, flip);          \
    }

extern "C" {
    DRAW_QUAD_HOOK(THUMB_BRANCH_LINK_MCSSSys_Draw_0x7a4)
    DRAW_QUAD_HOOK(THUMB_BRANCH_LINK_MCSSSys_Draw_0x7da)
    DRAW_QUAD_HOOK(THUMB_BRANCH_LINK_MCSSSys_Draw_0x836)
}
