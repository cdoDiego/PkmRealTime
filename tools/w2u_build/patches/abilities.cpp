// Habilidades de Gen 6 que White2Upgrade solo trae con nombre (PkmRealTime, 10-nov).
//
// El combate le pone a cada Pokémon el código de su habilidad con AbilityEvent_AddItem (overlay 167): busca la
// habilidad en su tabla (sAbilityEventAddTable, 158 entradas) y registra sus funciones para los eventos del combate
// ("al calcular la potencia", "al entrar"...), como hace Pokémon Showdown. Las habilidades nuevas no están en la tabla
// y no hacen nada. Aquí se enganchan las 7 llamadas a AbilityEvent_AddItem: si la del juego no encuentra la habilidad,
// se busca en sNewAbilities.
// Piloto: Aura Oscura (186), Aura Feérica (187) y Rompeaura (188), con su mensaje al entrar ("Yveltal is radiating a
// dark aura!", tools/battle_text.py).
// Direcciones de W2 USA (decomp pokebw2, config/w2_us), las mismas en White2Upgrade; los nombres los añade
// patches/battle.esdb.yml.

#include "swantypes.h"

#define ABILITY_DARK_AURA 186
#define ABILITY_FAIRY_AURA 187
#define ABILITY_AURA_BREAK 188
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

static const AbilityEventAddEntry sNewAbilities[] = {
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
