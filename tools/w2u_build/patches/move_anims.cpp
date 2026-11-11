// Animaciones de los movimientos de Gen 6 de White2Upgrade (PkmRealTime, 10-nov).
//
// El combate pide la animación de un movimiento con BtlvEffect_StartMove (overlay 168), que llama a BtlvEffvm_Start con
// su número. Ahí, los números desde BTLV_EFFECT_FIRST (0x231 = 561) no son movimientos sino efectos del combate (salir
// de la Poké Ball, cambios de estadísticas...), en otro archivo (ARCID_BTLV_EFFVM_EFFECT_SCRIPTS, número - 561); y el
// 560 lee la copia de Destructor que White2Upgrade puso en a/0/6/5. White2Upgrade no lo cambia: sus 62 movimientos
// nuevos (560-621) hacían el efecto que les tocara. Fuerza Lunar se veía rara; Ala Mortífera (613, efecto 52) sacaba a
// Yveltal de la pantalla y colgaba el combate (visto el 10-nov).
// Aquí se cambia el número en la única llamada que pide la animación de un movimiento (BtlvScu, overlay 167): cada
// movimiento nuevo usa la de uno parecido del juego. Nunca uno de dos turnos (Vuelo, Bote, Golpe Umbrío...): su
// animación esconde al atacante hasta el turno siguiente.
// Direcciones de W2 USA (decomp pokebw2, config/w2_us), las mismas en White2Upgrade y en la mezcla con Redux.

#include "swantypes.h"

#define MOVE_NEW_FIRST 560
#define MOVE_NEW_LAST 621

struct BtlvMoveEffectParam {         // btlv_effect.h
    u16 move;
    u32 attackerPos;
    u32 targetPos;
    u8 variant;                      // turno de un movimiento de dos turnos
    u8 unk0D;
    s32 target;
};

extern "C" void BtlvEffect_StartMove(const BtlvMoveEffectParam *param);

// Movimiento nuevo (desde 560): el del juego cuya animación usa
static const u16 sAnimOf[MOVE_NEW_LAST - MOVE_NEW_FIRST + 1] = {
     34,  // 560 Flying Press: Body Slam
    469,  // 561 Mat Block: Wide Guard
    188,  // 562 Belch: Sludge Bomb
     74,  // 563 Rototiller: Growth
     81,  // 564 Sticky Web: String Shot
     40,  // 565 Fell Stinger: Poison Sting
    425,  // 566 Phantom Force: Shadow Sneak
    180,  // 567 Trick-or-Treat: Spite
     46,  // 568 Noble Roar: Roar
    268,  // 569 Ion Deluge: Charge
    435,  // 570 Parabolic Charge: Discharge
     73,  // 571 Forest's Curse: Leech Seed
     80,  // 572 Petal Blizzard: Petal Dance
     58,  // 573 Freeze-Dry: Ice Beam
    304,  // 574 Disarming Voice: Hyper Voice
    262,  // 575 Parting Shot: Memento
    391,  // 576 Topsy-Turvy: Heart Swap
    202,  // 577 Draining Kiss: Giga Drain
    501,  // 578 Crafty Shield: Quick Guard
    312,  // 579 Flower Shield: Aromatherapy
    275,  // 580 Grassy Terrain: Ingrain
     54,  // 581 Misty Terrain: Mist
     86,  // 582 Electrify: Thunder Wave
    251,  // 583 Play Rough: Beat Up
     16,  // 584 Fairy Wind: Gust
    396,  // 585 Moonblast: Aura Sphere
    304,  // 586 Boomburst: Hyper Voice
    212,  // 587 Fairy Lock: Mean Look
    182,  // 588 King's Shield: Protect
    204,  // 589 Play Nice: Charm
    321,  // 590 Confide: Tickle
    444,  // 591 Diamond Storm: Stone Edge
    503,  // 592 Steam Eruption: Scald
    364,  // 593 Hyperspace Hole: Feint
     55,  // 594 Water Shuriken: Water Gun
    481,  // 595 Mystical Fire: Flame Burst
    182,  // 596 Spiky Shield: Protect
    312,  // 597 Aromatic Mist: Aromatherapy
    451,  // 598 Eerie Impulse: Charge Beam
    491,  // 599 Venom Drench: Acid Spray
    147,  // 600 Powder: Spore
    483,  // 601 Geomancy: Quiver Dance
    393,  // 602 Magnetic Flux: Magnet Rise
      6,  // 603 Happy Hour: Pay Day
    268,  // 604 Electric Terrain: Charge
    148,  // 605 Dazzling Gleam: Flash
    270,  // 606 Celebrate: Helping Hand
    270,  // 607 Hold Hands: Helping Hand
    313,  // 608 Baby-Doll Eyes: Fake Tears
    209,  // 609 Nuzzle: Spark
    206,  // 610 Hold Back: False Swipe
    450,  // 611 Infestation: Bug Bite
    183,  // 612 Power-Up Punch: Mach Punch
    403,  // 613 Oblivion Wing: Air Slash
    414,  // 614 Thousand Arrows: Earth Power
     89,  // 615 Thousand Waves: Earthquake
    523,  // 616 Land's Wrath: Bulldoze
    430,  // 617 Light of Ruin: Flash Cannon
     56,  // 618 Origin Pulse: Hydro Pump
    444,  // 619 Precipice Blades: Stone Edge
    413,  // 620 Dragon Ascent: Brave Bird
    400,  // 621 Hyperspace Fury: Night Slash
};

extern "C" {

// BtlvScu (overlay 167): la animación del movimiento que se usa
void THUMB_BRANCH_LINK_167_0x21D3154(const BtlvMoveEffectParam *param) {
    if (param->move >= MOVE_NEW_FIRST && param->move <= MOVE_NEW_LAST) {
        BtlvMoveEffectParam copy = *param;
        copy.move = sAnimOf[param->move - MOVE_NEW_FIRST];
        BtlvEffect_StartMove(&copy);
        return;
    }
    BtlvEffect_StartMove(param);
}

}
