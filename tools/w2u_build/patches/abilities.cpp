// Habilidades de Gen 6 que White2Upgrade solo trae con nombre (PkmRealTime, 10-nov).
//
// El combate le pone a cada Pokémon el código de su habilidad con AbilityEvent_AddItem (overlay 167): busca la
// habilidad en su tabla (sAbilityEventAddTable, 158 entradas) y registra sus funciones para los eventos del combate
// ("al calcular la potencia", "al entrar"...), como hace Pokémon Showdown. Las habilidades nuevas no están en la tabla
// y no hacen nada. Aquí se enganchan las 7 llamadas a AbilityEvent_AddItem: si la del juego no encuentra la habilidad,
// se busca en sNewAbilities.
// Hechas: Aura Oscura (186), Aura Feérica (187) y Rompeaura (188), con su mensaje al entrar ("Yveltal is radiating a
// dark aura!", tools/battle_text.py); y, copiando a una parecida del juego (ability_handlers.c de la decomp):
// Pelaje Recio (Escama Especial), Mandíbula Fuerte / Megadisparador / Garra Dura (Puño Férreo), Alas Vendaval
// (Bromista), Piel Helada / Piel Feérica / Piel Celeste (Normalidad), Tenacidad (Competitivo), Baba (Piel Tosca) y
// Antibalas (Insonorizar). Las listas de movimientos son por nombre en esta ROM: Redux cambia algunos (121 es
// Psicocolmillo, no Bomba Huevo).
// Direcciones de W2 USA (decomp pokebw2, config/w2_us), las mismas en White2Upgrade; los nombres los añade
// patches/battle.esdb.yml.

#include "swantypes.h"

#define ABILITY_DARK_AURA 186
#define ABILITY_FAIRY_AURA 187
#define ABILITY_AURA_BREAK 188
#define ABILITY_FUR_COAT 169
#define ABILITY_BULLETPROOF 171
#define ABILITY_COMPETITIVE 172
#define ABILITY_STRONG_JAW 173
#define ABILITY_REFRIGERATE 174
#define ABILITY_GALE_WINGS 177
#define ABILITY_MEGA_LAUNCHER 178
#define ABILITY_TOUGH_CLAWS 181
#define ABILITY_PIXILATE 182
#define ABILITY_GOOEY 183
#define ABILITY_AERILATE 184
#define TYPE_NORMAL 0
#define TYPE_FLYING 2
#define TYPE_ICE 14
#define CATEGORY_PHYSICAL 1
#define MOVE_FLAG_CONTACT 0
#define STAT_ATTACK_SP 3
#define STAT_SPEED 5
#define BTL_EVENT_GET_MOVE_PRIORITY 0x11
#define BTL_EVENT_GET_MOVE_PARAM 0x28    // tipo y categoría del movimiento que se usa
#define BTL_EVENT_CHECK_NO_EFFECT_3 0x2D // inmunidades por habilidad (Insonorizar)
#define BTL_EVENT_TARGET_DEFENSE 0x3C    // la defensa del que recibe
#define BTL_EVENT_DAMAGE_REACTION 0x4B   // tras recibir un golpe
#define BTL_EVENT_STAT_CHANGE_APPLIED 0x5D
#define BTL_EVAR_ATTACKER 0x03
#define BTL_EVAR_DEFENDER 0x04
#define BTL_EVAR_MOVE 0x12
#define BTL_EVAR_MOVE_PRIORITY 0x18
#define BTL_EVAR_MOVE_CATEGORY 0x1A
#define BTL_EVAR_AMOUNT 0x20
#define BTL_EVAR_RATIO 0x35
#define BTL_EVAR_NO_EFFECT_FLAG 0x40
#define BTL_EVAR_SUBSTITUTE_FLAG 0x46
#define BTL_HANDLER_STAT_CHANGE 14
#define MSG_NO_EFFECT 0xD2               // "It doesn't affect X..."
#define RATIO_X1_3 5325
#define RATIO_X1_5 6144
#define RATIO_X2 8192
#define TYPE_DARK 16
#define TYPE_FAIRY 17
#define BATTLEMON_ABILITY 16             // GetBattleMonStat: la habilidad de ahora
#define BTL_EVENT_FACTOR_ABILITY 4
#define BTL_EVENT_MOVE_POWER 0x38        // al calcular la potencia de un movimiento
#define BTL_EVAR_MOVE_TYPE 0x16
#define BTL_EVAR_POWER_RATIO 0x31        // multiplicador de la potencia (4096 = x1)
#define AURA_RATIO 5448                  // x4/3
#define AURA_BREAK_RATIO 3072            // x3/4
#define MON_ID_COUNT 24                  // ids de Pokémon en combate (4 entrenadores x 6)
#define BTL_EVENT_MEMBER_IN 0x55         // al entrar en el campo
#define BTL_EVENT_CHANGE_ABILITY_AFTER 0x8A   // al ganar la habilidad (Danza Mimética...)
#define BTL_EVAR_MON 0x02
#define BTL_HANDLER_ABILITY_POPUP_ADD 2  // la ventana con el nombre de la habilidad
#define BTL_HANDLER_ABILITY_POPUP_REMOVE 3
#define BTL_HANDLER_MESSAGE 4
#define BTL_STRTYPE_SET 2                // mensaje de tres (tu Pokémon, el salvaje, el del rival)
// Mensajes añadidos por tools/battle_text.py (FIRST_LINE), de tres en tres
#define MSG_DARK_AURA 1159
#define MSG_FAIRY_AURA 1162
#define MSG_AURA_BREAK 1165

struct BattleMon;
struct BtlServerFlow;
struct BattleEventItem;
typedef void (*BattleEventHandlerFn)(BattleEventItem *item, BtlServerFlow *flow, u8 monId, s32 *work);
struct BattleEventHandlerEntry {
    u32 event;
    BattleEventHandlerFn handler;
};
typedef const BattleEventHandlerEntry *(*AbilityEventAddFn)(u32 *packed);
struct BattleHandlerString;
struct BattleHandlerMessageParam {
    u32 flags;
    u8 string[1];                         // BattleHandlerString
};
// BattleHandlerStatChangeParam
struct StatChangeParam {
    u32 flags;                            // bit 23: con la ventana de la habilidad
    u32 stat;
    u32 value;
    s8 change;
    u8 flag;
    u8 showFail;
    u8 count;
    u8 monIds[8];
};
#define PARAM_POPUP (1u << 23)
struct AbilityEventAddEntry {
    u16 ability;
    AbilityEventAddFn eventAdd;
};

extern "C" {
BattleEventItem *AbilityEvent_AddItem(BattleMon *mon);
u32 GetBattleMonStat(BattleMon *mon, u32 stat);
u8 GetMonID(BattleMon *mon);
BattleEventItem *BattleEvent_AddItem(u32 factorType, u16 subId, u32 priority, u32 subPriority, u8 monId,
                                     const BattleEventHandlerEntry *handlers, u16 numHandlers);
u32 devideNumHandersAndPri(u32 *packed);
u16 calcAbilHandlerSubPriority(BattleMon *mon);
u32 BattleEventVar_GetValue(u32 key);
void BattleEventVar_MulValue(u16 key, s32 value);
BattleMon *GetBattleMon(BtlServerFlow *flow, u8 monId);
u8 BtlServerFlow_GetMonIDAtPos(BtlServerFlow *flow, u8 pos);
u32 BtlServerFlow_GetFrontPosCount(BtlServerFlow *flow);
void BattleHandler_StrSetup(BattleHandlerString *string, u32 type, u16 message);
void BattleHandler_AddArg(BattleHandlerString *string, u32 arg);
void *BattleHandler_PushWork(BtlServerFlow *flow, u32 command, u32 monId);
void BattleHandler_PushRun(BtlServerFlow *flow, u32 command, u32 monId);
void BattleHandler_PopWork(BtlServerFlow *flow, void *work);
u32 BattleEventVar_RewriteValue(u32 key, s32 value);
bool IsAllyMonID(u8 a, u8 b);
bool IsFainted(BattleMon *mon);
bool getMoveFlag(u16 move, u32 flag);
u8 PML_MoveGetType(u16 move);
s32 PML_MoveGetCategory(u16 move);
}

static bool inList(const u16 *list, u32 count, u32 move) {
    for (u32 i = 0; i < count; i++) {
        if (list[i] == move) {
            return true;
        }
    }
    return false;
}

// Al entrar (o al ganar la habilidad): la ventana de la habilidad y su mensaje, como Presión (HandlerPressureMemberIn)
static void announce(BtlServerFlow *flow, u8 monId, u16 message) {
    if (BattleEventVar_GetValue(BTL_EVAR_MON) != monId) {
        return;
    }
    BattleHandler_PushRun(flow, BTL_HANDLER_ABILITY_POPUP_ADD, monId);
    BattleHandlerMessageParam *param =
        (BattleHandlerMessageParam *)BattleHandler_PushWork(flow, BTL_HANDLER_MESSAGE, monId);
    BattleHandlerString *string = (BattleHandlerString *)param->string;
    BattleHandler_StrSetup(string, BTL_STRTYPE_SET, message);
    BattleHandler_AddArg(string, monId);
    BattleHandler_PopWork(flow, param);
    BattleHandler_PushRun(flow, BTL_HANDLER_ABILITY_POPUP_REMOVE, monId);
}

// Auras: los movimientos de su tipo, de cualquiera que esté en el campo, pegan x4/3; con Rompeaura en el campo, x3/4.
// Si hay dos con la misma aura (combates dobles), solo cuenta la primera
static void auraPower(BtlServerFlow *flow, u8 monId, u32 aura, u32 type) {
    if (BattleEventVar_GetValue(BTL_EVAR_MOVE_TYPE) != type) {
        return;
    }
    bool auraBreak = false;
    u32 first = MON_ID_COUNT;
    u32 count = BtlServerFlow_GetFrontPosCount(flow) * 2;   // devuelve los de un bando
    for (u32 pos = 0; pos < count; pos++) {
        u8 id = BtlServerFlow_GetMonIDAtPos(flow, pos);
        if (id >= MON_ID_COUNT) {
            continue;
        }
        u32 ability = GetBattleMonStat(GetBattleMon(flow, id), BATTLEMON_ABILITY);
        if (ability == ABILITY_AURA_BREAK) {
            auraBreak = true;
        } else if (ability == aura && id < first) {
            first = id;
        }
    }
    if (first == monId) {
        BattleEventVar_MulValue(BTL_EVAR_POWER_RATIO, auraBreak ? AURA_BREAK_RATIO : AURA_RATIO);
    }
}

static void handlerDarkAura(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    auraPower(flow, monId, ABILITY_DARK_AURA, TYPE_DARK);
}
static void handlerFairyAura(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    auraPower(flow, monId, ABILITY_FAIRY_AURA, TYPE_FAIRY);
}

static void inDarkAura(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    announce(flow, monId, MSG_DARK_AURA);
}
static void inFairyAura(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    announce(flow, monId, MSG_FAIRY_AURA);
}
static void inAuraBreak(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    announce(flow, monId, MSG_AURA_BREAK);
}

// --- Potencia: Mandíbula Fuerte (mordiscos x1,5), Megadisparador (pulsos x1,5), Garra Dura (de contacto x1,3)
static const u16 sBiteMoves[] = {44, 121, 158, 242, 305, 422, 423, 424};     // Mordisco ... Colmillo Ígneo
static const u16 sPulseMoves[] = {352, 396, 399, 406, 618};                   // Hidropulso ... Pulso Primigenio
static const u16 sBallMoves[] = {188, 190, 192, 247, 301, 311, 331, 360, 396, 402, 411, 412, 426, 439, 443,
                                 486, 491, 545};                              // Bomba Lodo ... Llama Azul

static bool attackerUses(u8 monId, const u16 *list, u32 count) {
    return BattleEventVar_GetValue(BTL_EVAR_ATTACKER) == monId &&
           inList(list, count, BattleEventVar_GetValue(BTL_EVAR_MOVE));
}
static void powerStrongJaw(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) {
    if (attackerUses(monId, sBiteMoves, sizeof(sBiteMoves) / 2)) {
        BattleEventVar_MulValue(BTL_EVAR_POWER_RATIO, RATIO_X1_5);
    }
}
static void powerMegaLauncher(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) {
    if (attackerUses(monId, sPulseMoves, sizeof(sPulseMoves) / 2)) {
        BattleEventVar_MulValue(BTL_EVAR_POWER_RATIO, RATIO_X1_5);
    }
}
static void powerToughClaws(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) {
    if (BattleEventVar_GetValue(BTL_EVAR_ATTACKER) == monId &&
        getMoveFlag(BattleEventVar_GetValue(BTL_EVAR_MOVE), MOVE_FLAG_CONTACT)) {
        BattleEventVar_MulValue(BTL_EVAR_POWER_RATIO, RATIO_X1_3);
    }
}

// --- Pelaje Recio: la Defensa x2 contra los golpes físicos (como Escama Especial)
static void defenseFurCoat(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) {
    if (BattleEventVar_GetValue(BTL_EVAR_DEFENDER) == monId &&
        BattleEventVar_GetValue(BTL_EVAR_MOVE_CATEGORY) == CATEGORY_PHYSICAL) {
        BattleEventVar_MulValue(BTL_EVAR_RATIO, RATIO_X2);
    }
}

// --- Alas Vendaval: los movimientos Volador van con +1 de prioridad (como Bromista; la de Gen 6, sin mirar la vida)
static void priorityGaleWings(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) {
    if (BattleEventVar_GetValue(BTL_EVAR_ATTACKER) == monId &&
        PML_MoveGetType(BattleEventVar_GetValue(BTL_EVAR_MOVE)) == TYPE_FLYING) {
        BattleEventVar_RewriteValue(BTL_EVAR_MOVE_PRIORITY, BattleEventVar_GetValue(BTL_EVAR_MOVE_PRIORITY) + 1);
    }
}

// --- Piel Helada / Piel Feérica / Piel Celeste: los movimientos Normal pasan a su tipo y pegan x1,3 (Gen 6). No los
// que calculan su tipo (Poder Oculto, Meteorobola, Don Natural, Sentencia, Tecno Shock) ni Combate
static const u16 sOwnTypeMoves[] = {165, 237, 311, 363, 449, 546};
static bool ateMove(u8 monId, u32 who) {
    u32 move = BattleEventVar_GetValue(BTL_EVAR_MOVE);
    return BattleEventVar_GetValue(who) == monId && PML_MoveGetType(move) == TYPE_NORMAL &&
           !inList(sOwnTypeMoves, sizeof(sOwnTypeMoves) / 2, move);
}
static void ateType(u8 monId, u32 type) {
    if (ateMove(monId, BTL_EVAR_MON) && BattleEventVar_GetValue(BTL_EVAR_MOVE_TYPE) == TYPE_NORMAL) {
        BattleEventVar_RewriteValue(BTL_EVAR_MOVE_TYPE, type);
    }
}
static void atePower(u8 monId, u32 type) {
    if (ateMove(monId, BTL_EVAR_ATTACKER) && BattleEventVar_GetValue(BTL_EVAR_MOVE_TYPE) == type) {
        BattleEventVar_MulValue(BTL_EVAR_POWER_RATIO, RATIO_X1_3);
    }
}
static void typeRefrigerate(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) { ateType(monId, TYPE_ICE); }
static void powerRefrigerate(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) { atePower(monId, TYPE_ICE); }
static void typePixilate(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) { ateType(monId, TYPE_FAIRY); }
static void powerPixilate(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) { atePower(monId, TYPE_FAIRY); }
static void typeAerilate(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) { ateType(monId, TYPE_FLYING); }
static void powerAerilate(BattleEventItem *, BtlServerFlow *, u8 monId, s32 *) { atePower(monId, TYPE_FLYING); }

// --- Cambios de características con la ventana de la habilidad
static void statChange(BtlServerFlow *flow, u8 monId, u8 target, u32 stat, s8 change) {
    StatChangeParam *param = (StatChangeParam *)BattleHandler_PushWork(flow, BTL_HANDLER_STAT_CHANGE, monId);
    param->flags |= PARAM_POPUP;
    param->stat = stat;
    param->change = change;
    param->showFail = 1;
    param->count = 1;
    param->monIds[0] = target;
    BattleHandler_PopWork(flow, param);
}

// Tenacidad: si un rival le baja una característica, Ataque Especial +2 (como Competitivo)
static void statCompetitive(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    if (BattleEventVar_GetValue(BTL_EVAR_MON) == monId &&
        !IsAllyMonID(monId, BattleEventVar_GetValue(BTL_EVAR_ATTACKER)) &&
        (s32)BattleEventVar_GetValue(BTL_EVAR_AMOUNT) < 0) {
        statChange(flow, monId, monId, STAT_ATTACK_SP, 2);
    }
}

// Baba: al que le golpea con contacto le baja la Velocidad 1 (como Piel Tosca)
static void reactionGooey(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    if (BattleEventVar_GetValue(BTL_EVAR_DEFENDER) == monId && BattleEventVar_GetValue(BTL_EVAR_SUBSTITUTE_FLAG) == 0 &&
        getMoveFlag(BattleEventVar_GetValue(BTL_EVAR_MOVE), MOVE_FLAG_CONTACT)) {
        u8 attackerId = BattleEventVar_GetValue(BTL_EVAR_ATTACKER);
        if (!IsFainted(GetBattleMon(flow, attackerId))) {
            statChange(flow, monId, attackerId, STAT_SPEED, -1);
        }
    }
}

// --- Antibalas: no le afectan las bombas y bolas (como Insonorizar)
static void noEffectBulletproof(BattleEventItem *, BtlServerFlow *flow, u8 monId, s32 *) {
    if (BattleEventVar_GetValue(BTL_EVAR_DEFENDER) == monId &&
        inList(sBallMoves, sizeof(sBallMoves) / 2, BattleEventVar_GetValue(BTL_EVAR_MOVE)) &&
        BattleEventVar_RewriteValue(BTL_EVAR_NO_EFFECT_FLAG, 1)) {
        BattleHandler_PushRun(flow, BTL_HANDLER_ABILITY_POPUP_ADD, monId);
        BattleHandlerMessageParam *param =
            (BattleHandlerMessageParam *)BattleHandler_PushWork(flow, BTL_HANDLER_MESSAGE, monId);
        BattleHandlerString *string = (BattleHandlerString *)param->string;
        BattleHandler_StrSetup(string, BTL_STRTYPE_SET, MSG_NO_EFFECT);
        BattleHandler_AddArg(string, monId);
        BattleHandler_PopWork(flow, param);
        BattleHandler_PushRun(flow, BTL_HANDLER_ABILITY_POPUP_REMOVE, monId);
    }
}

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))
static const BattleEventHandlerEntry sHandlersDarkAura[] = {
    {BTL_EVENT_MEMBER_IN, inDarkAura},
    {BTL_EVENT_CHANGE_ABILITY_AFTER, inDarkAura},
    {BTL_EVENT_MOVE_POWER, handlerDarkAura},
};
static const BattleEventHandlerEntry sHandlersFairyAura[] = {
    {BTL_EVENT_MEMBER_IN, inFairyAura},
    {BTL_EVENT_CHANGE_ABILITY_AFTER, inFairyAura},
    {BTL_EVENT_MOVE_POWER, handlerFairyAura},
};
// Rompeaura solo avisa: las auras miran si está en el campo
static const BattleEventHandlerEntry sHandlersAuraBreak[] = {
    {BTL_EVENT_MEMBER_IN, inAuraBreak},
    {BTL_EVENT_CHANGE_ABILITY_AFTER, inAuraBreak},
};

static const BattleEventHandlerEntry *eventAddDarkAura(u32 *packed) {
    *packed = COUNT(sHandlersDarkAura);
    return sHandlersDarkAura;
}
static const BattleEventHandlerEntry *eventAddFairyAura(u32 *packed) {
    *packed = COUNT(sHandlersFairyAura);
    return sHandlersFairyAura;
}
static const BattleEventHandlerEntry *eventAddAuraBreak(u32 *packed) {
    *packed = COUNT(sHandlersAuraBreak);
    return sHandlersAuraBreak;
}

#define HANDLERS(name, ...)                                                 \
    static const BattleEventHandlerEntry sHandlers##name[] = {__VA_ARGS__}; \
    static const BattleEventHandlerEntry *eventAdd##name(u32 *packed) {     \
        *packed = COUNT(sHandlers##name);                                   \
        return sHandlers##name;                                             \
    }
HANDLERS(FurCoat, {BTL_EVENT_TARGET_DEFENSE, defenseFurCoat})
HANDLERS(Bulletproof, {BTL_EVENT_CHECK_NO_EFFECT_3, noEffectBulletproof})
HANDLERS(Competitive, {BTL_EVENT_STAT_CHANGE_APPLIED, statCompetitive})
HANDLERS(StrongJaw, {BTL_EVENT_MOVE_POWER, powerStrongJaw})
HANDLERS(Refrigerate, {BTL_EVENT_GET_MOVE_PARAM, typeRefrigerate}, {BTL_EVENT_MOVE_POWER, powerRefrigerate})
HANDLERS(GaleWings, {BTL_EVENT_GET_MOVE_PRIORITY, priorityGaleWings})
HANDLERS(MegaLauncher, {BTL_EVENT_MOVE_POWER, powerMegaLauncher})
HANDLERS(ToughClaws, {BTL_EVENT_MOVE_POWER, powerToughClaws})
HANDLERS(Pixilate, {BTL_EVENT_GET_MOVE_PARAM, typePixilate}, {BTL_EVENT_MOVE_POWER, powerPixilate})
HANDLERS(Gooey, {BTL_EVENT_DAMAGE_REACTION, reactionGooey})
HANDLERS(Aerilate, {BTL_EVENT_GET_MOVE_PARAM, typeAerilate}, {BTL_EVENT_MOVE_POWER, powerAerilate})

static const AbilityEventAddEntry sNewAbilities[] = {
    {ABILITY_FUR_COAT, eventAddFurCoat},
    {ABILITY_BULLETPROOF, eventAddBulletproof},
    {ABILITY_COMPETITIVE, eventAddCompetitive},
    {ABILITY_STRONG_JAW, eventAddStrongJaw},
    {ABILITY_REFRIGERATE, eventAddRefrigerate},
    {ABILITY_GALE_WINGS, eventAddGaleWings},
    {ABILITY_MEGA_LAUNCHER, eventAddMegaLauncher},
    {ABILITY_TOUGH_CLAWS, eventAddToughClaws},
    {ABILITY_PIXILATE, eventAddPixilate},
    {ABILITY_GOOEY, eventAddGooey},
    {ABILITY_AERILATE, eventAddAerilate},
    {ABILITY_DARK_AURA, eventAddDarkAura},
    {ABILITY_FAIRY_AURA, eventAddFairyAura},
    {ABILITY_AURA_BREAK, eventAddAuraBreak},
};

// Lo mismo que AbilityEvent_AddItem, con la tabla nueva
static BattleEventItem *addAbility(BattleMon *mon) {
    BattleEventItem *item = AbilityEvent_AddItem(mon);
    if (item) {
        return item;
    }
    u16 ability = GetBattleMonStat(mon, BATTLEMON_ABILITY);
    for (u32 i = 0; i < sizeof(sNewAbilities) / sizeof(sNewAbilities[0]); i++) {
        if (sNewAbilities[i].ability == ability) {
            u16 subPriority = calcAbilHandlerSubPriority(mon);
            u8 monId = GetMonID(mon);
            u32 packed;
            const BattleEventHandlerEntry *handlers = sNewAbilities[i].eventAdd(&packed);
            u32 priority = devideNumHandersAndPri(&packed);
            return BattleEvent_AddItem(BTL_EVENT_FACTOR_ABILITY, ability, priority, subPriority, monId, handlers,
                                       packed);
        }
    }
    return 0;
}

extern "C" {

// Las 7 llamadas a AbilityEvent_AddItem (overlay 167): entrar en combate, cambiar de habilidad (Danza Mimética,
// Cambio de Habilidad, Mimetismo...), recuperarla
BattleEventItem *THUMB_BRANCH_LINK_167_0x21A142A(BattleMon *mon) { return addAbility(mon); }
BattleEventItem *THUMB_BRANCH_LINK_167_0x21A64E8(BattleMon *mon) { return addAbility(mon); }
BattleEventItem *THUMB_BRANCH_LINK_167_0x21AD69A(BattleMon *mon) { return addAbility(mon); }
BattleEventItem *THUMB_BRANCH_LINK_167_0x21AE084(BattleMon *mon) { return addAbility(mon); }
BattleEventItem *THUMB_BRANCH_LINK_167_0x21BDDC4(BattleMon *mon) { return addAbility(mon); }
BattleEventItem *THUMB_BRANCH_LINK_167_0x21BDE0A(BattleMon *mon) { return addAbility(mon); }
BattleEventItem *THUMB_BRANCH_LINK_167_0x21BDE10(BattleMon *mon) { return addAbility(mon); }

}
