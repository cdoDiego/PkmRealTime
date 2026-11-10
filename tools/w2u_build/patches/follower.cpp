// Pokémon que te sigue, como en HeartGold y SoulSilver (PkmRealTime, 08-nov).
//
// El juego ya trae un sistema para que un personaje te siga (pair_sys, overlay 12): lo usa la historia con aliados
// como Bianca en el Monte Tuerca. Guarda quién te sigue en el guardado (FieldFollowWk), lo vuelve a crear al cambiar de
// mapa (TryRespawnFollowActor) y tiene modelos de Pokémon que caminan (TPOKE, códigos de objeto desde 0x1000).
//
// Aquí se usa ese sistema para el primero del equipo:
//   - al entrar en un mapa (EventWarpSequence_CreateIn, justo antes de TryRespawnFollowActor) se pone como acompañante
//     el modelo del primero del equipo, o se quita si es un huevo o no tiene modelo;
//   - el resto del juego no lo cuenta como compañero: con un aliado de la historia el juego cura el equipo tras cada
//     combate, hace los combates salvajes dobles, no deja usar la bici, Surf, Cascada, Buceo ni la Cuerda Huida, y
//     algunos guiones cambian. Por eso GameData_CheckPairFlag y las órdenes de guion que leen la bandera 0x966 dicen
//     "nadie te sigue" cuando el que te sigue es el nuestro; solo lo que mueve al acompañante ve la bandera real;
//   - si la historia pone a un aliado (ActorPairSet), el nuestro se quita antes y vuelve en el siguiente mapa.
// La bandera FLAG_FOLLOWER_OFF lo apaga (el puente la cambia con el evento set_follower). FLAG_FOLLOWER_OURS dice que
// el que te sigue es el nuestro. Las dos van en el guardado; ningún guion de W2, White2Upgrade ni Redux las usa
// (0xA80-0xA9F libres; desde 0xAA0 son las diarias).
// Direcciones de W2 USA (decomp pokebw2, config/w2_us), las mismas en White2Upgrade.

#include "swantypes.h"

#define FLAG_PAIR 0x966              // pair_sys: alguien te sigue
#define WORK_PAIR 0x4043             // pair_sys: índice del que te sigue
#define FLAG_FOLLOWER_OFF 0xA90      // acompañante apagado
#define FLAG_FOLLOWER_OURS 0xA91     // el que te sigue es el primero del equipo
#define FOLLOWER_ACTOR_ID 0xFE
#define FOLLOWER_INDEX 7
#define FOLLOWER_INDEX_NONE 0xFF
#define TPOKE_INDEX_NONE 0xFFFF
#define HEAPID_FIELDMAP_TAIL 0x8015    // HEAPID_FIELDMAP, por el final (memoria de usar y tirar)
#define OBJ_CODE_POKEMON_MIN 0x1000
#define OBJ_CODE_POKEMON_END 0x126C     // los 620 modelos de Pokémon, en la tabla desde la posición 0x179
#define OBJ_CODE_POKEMON_INDEX 0x179
#define OBJ_CODE_SPECIAL_MIN 0x2000     // 11 modelos especiales, desde la posición 0x3E5
#define OBJ_CODE_SPECIAL_END 0x200B
#define OBJ_CODE_SPECIAL_INDEX 0x3E5
#define OBJ_CODE_NPC_END 0x179
#define OBJ_CODE_SHINY_MIN 0x3000       // copias variocolor de tools/follower_shiny.py, al final de la tabla
#define OBJ_CODE_SHINY_INDEX 0x3F0
#define OBJ_INDEX_FALLBACK 10           // lo que da el juego con un código que no conoce
#define PKM_PARAM_SPECIES 0x05
#define PKM_PARAM_IS_EGG 0x4C
#define PKM_PARAM_SEX 0x6E
#define PKM_PARAM_FORM 0x6F

struct TPokeData {                   // de LoadTPokeData
    void *entries;
    u32 *mmodelTable;                // tabla de modelos: primero cuántos hay
    void *configs;
    u32 count;
};

struct FollowWk {                    // FieldFollowWk de pair_sys
    u16 heapId;
    u8 index;
    u8 originActorId;
    u16 objCode : 15;
    u16 isPersistent : 1;
    u16 scrId;
    u16 trainerId;
};

extern "C" {
void *GameData_GetEventWork(void *gameData);
void *GameData_GetParty(void *gameData);
void *GameData_GetMMSys(void *gameData);
FollowWk *GetFieldFollowerCfg(void *gameData);
bool EventWork_FlagGet(void *eventWork, u16 flag);
void EventWork_FlagSet(void *eventWork, u16 flag);
void EventWork_FlagReset(void *eventWork, u16 flag);
u16 *EventWork_GetWkPtr(void *eventWork, u16 work);
int PokeParty_GetPkmCount(void *party);
void *PokeParty_GetPkm(void *party, u32 index);
bool PokeParty_IsRare(void *pkm);
u32 PML_PkmGetParam(void *pkm, u32 param, void *buffer);
TPokeData *LoadTPokeData(u16 heapId);
void FreeTPokeData(TPokeData *data);
u16 GetPokemonFieldOBJCODE(TPokeData *data, u16 species, u16 sex, u16 form);
int GetFieldPokemonMMdlLUTIndex_(const TPokeData *data, u16 species, u16 sex, u16 form);
bool IsFieldPokemonSpriteHugeBillboard(void *gameData, TPokeData *data, u16 species, u16 sex, u16 form);
bool setupNpcFollower(void *gameData, u8 index, u8 isPersistent, u32 originActorId, u16 objCode, u16 scrId,
                      u16 trainerId);
void TryRespawnFollowActor(void *gameData, u32 behind);
void *FindFieldActor(void *mmSys, u16 id);
void DeleteActor(void *actor);
struct ShadowOffset {
    s32 x, y, z;
};
void CopyActorPosOffset(void *actor, ShadowOffset *offset);
const u16 *GetActorMdlInfo(void *actor);    // FieldActorConfig: el código de objeto (uid) va primero
}

static void *sGameData;              // GameData (uno durante toda la partida), para ActorPairEnd

static bool isOurs(void *eventWork) {
    return EventWork_FlagGet(eventWork, FLAG_PAIR) && EventWork_FlagGet(eventWork, FLAG_FOLLOWER_OURS);
}

// Un Pokémon que te sigue para siempre y sin entrenador es nuestro aunque falte la marca (el prototipo del puente,
// que lo ponía con un guion, o partidas guardadas con él)
static void adoptLegacy(void *gameData, void *eventWork) {
    FollowWk *wk = GetFieldFollowerCfg(gameData);
    if (EventWork_FlagGet(eventWork, FLAG_PAIR) && !EventWork_FlagGet(eventWork, FLAG_FOLLOWER_OURS) &&
        wk->isPersistent && wk->trainerId == 0 && wk->objCode >= OBJ_CODE_POKEMON_MIN) {
        EventWork_FlagSet(eventWork, FLAG_FOLLOWER_OURS);
    }
}

// Lo que ve el juego: alguien de la historia te sigue
static bool storyPair(void *eventWork) {
    return EventWork_FlagGet(eventWork, FLAG_PAIR) && !EventWork_FlagGet(eventWork, FLAG_FOLLOWER_OURS);
}

// Modelo del primero del equipo (su copia variocolor si lo es y la ROM la tiene); 0 si es un huevo o no tiene modelo
static u16 leadObjCode(void *gameData) {
    void *party = GameData_GetParty(gameData);
    if (PokeParty_GetPkmCount(party) == 0) {
        return 0;
    }
    void *pkm = PokeParty_GetPkm(party, 0);
    if (PML_PkmGetParam(pkm, PKM_PARAM_IS_EGG, 0)) {
        return 0;
    }
    u16 species = PML_PkmGetParam(pkm, PKM_PARAM_SPECIES, 0);
    u16 sex = PML_PkmGetParam(pkm, PKM_PARAM_SEX, 0);
    u16 form = PML_PkmGetParam(pkm, PKM_PARAM_FORM, 0);
    TPokeData *data = LoadTPokeData(HEAPID_FIELDMAP_TAIL);
    u16 code = 0;
    if (GetFieldPokemonMMdlLUTIndex_(data, species, sex, form) != TPOKE_INDEX_NONE &&
        !IsFieldPokemonSpriteHugeBillboard(gameData, data, species, sex, form)) {
        code = GetPokemonFieldOBJCODE(data, species, sex, form);
        u32 shinyIndex = OBJ_CODE_SHINY_INDEX + code - OBJ_CODE_POKEMON_MIN;
        if (PokeParty_IsRare(pkm) && code >= OBJ_CODE_POKEMON_MIN && code < OBJ_CODE_POKEMON_END &&
            *data->mmodelTable > shinyIndex) {
            code = OBJ_CODE_SHINY_MIN + code - OBJ_CODE_POKEMON_MIN;
        }
    }
    FreeTPokeData(data);
    return code;
}

// Quita el nuestro: su personaje (si está en el mapa) y los datos de pair_sys
static void removeOurs(void *gameData, void *eventWork) {
    void *actor = FindFieldActor(GameData_GetMMSys(gameData), FOLLOWER_ACTOR_ID);
    if (actor) {
        DeleteActor(actor);
    }
    FollowWk *wk = GetFieldFollowerCfg(gameData);
    wk->index = FOLLOWER_INDEX_NONE;
    wk->isPersistent = 0;
    wk->objCode = 0;
    EventWork_FlagReset(eventWork, FLAG_PAIR);
    EventWork_FlagReset(eventWork, FLAG_FOLLOWER_OURS);
    *EventWork_GetWkPtr(eventWork, WORK_PAIR) = FOLLOWER_INDEX_NONE;
}

extern "C" {

// Posición de un código de objeto en la tabla de modelos (a/0/4/7). La del juego solo conoce sus tres rangos; se
// añade el de las copias variocolor
u32 THUMB_BRANCH_GetIndexOfObjID(u16 objCode) {
    if (objCode < OBJ_CODE_NPC_END) {
        return objCode;
    }
    if (objCode >= OBJ_CODE_POKEMON_MIN && objCode < OBJ_CODE_POKEMON_END) {
        return OBJ_CODE_POKEMON_INDEX + objCode - OBJ_CODE_POKEMON_MIN;
    }
    if (objCode >= OBJ_CODE_SPECIAL_MIN && objCode < OBJ_CODE_SPECIAL_END) {
        return OBJ_CODE_SPECIAL_INDEX + objCode - OBJ_CODE_SPECIAL_MIN;
    }
    if (objCode >= OBJ_CODE_SHINY_MIN && objCode < OBJ_CODE_SHINY_MIN + (OBJ_CODE_POKEMON_END - OBJ_CODE_POKEMON_MIN)) {
        return OBJ_CODE_SHINY_INDEX + objCode - OBJ_CODE_SHINY_MIN;
    }
    return OBJ_INDEX_FALLBACK;
}

// Para el resto del juego, el nuestro no es un compañero
bool THUMB_BRANCH_GameData_CheckPairFlag(void *gameData) {
    sGameData = gameData;
    void *eventWork = GameData_GetEventWork(gameData);
    adoptLegacy(gameData, eventWork);
    return storyPair(eventWork);
}

// CheckPerStepEvents (ov36): al dar el primer paso coloca y muestra al que te sigue (updateFollowerModel).
// Vuelo, Cuerda Huida, Teletransporte y caer debilitado cambian de mapa sin pasar por EventWarpSequence_CreateIn:
// si el nuestro falta en el mapa, se crea aquí (escondido; updateFollowerModel lo pone a tu lado en este mismo paso)
bool THUMB_BRANCH_LINK_36_0x21821F8(void *gameData) {
    void *eventWork = GameData_GetEventWork(gameData);
    if (isOurs(eventWork) && !FindFieldActor(GameData_GetMMSys(gameData), FOLLOWER_ACTOR_ID)) {
        TryRespawnFollowActor(gameData, 0);
    }
    return EventWork_FlagGet(eventWork, FLAG_PAIR);
}

// EventWarpSequence_StartWalkTask (ov36): el que te sigue camina contigo al cruzar una puerta
bool THUMB_BRANCH_LINK_36_0x21B7488(void *gameData) {
    return EventWork_FlagGet(GameData_GetEventWork(gameData), FLAG_PAIR);
}

// Órdenes de guion VMStackPushFlag y FlagGet (ov12): la bandera 0x966, como GameData_CheckPairFlag
static bool scriptFlagGet(void *eventWork, u16 flag) {
    if (flag == FLAG_PAIR) {
        if (sGameData) {
            adoptLegacy(sGameData, eventWork);
        }
        return storyPair(eventWork);
    }
    return EventWork_FlagGet(eventWork, flag);
}
bool THUMB_BRANCH_LINK_12_0x215444E(void *eventWork, u16 flag) { return scriptFlagGet(eventWork, flag); }
bool THUMB_BRANCH_LINK_12_0x2154722(void *eventWork, u16 flag) { return scriptFlagGet(eventWork, flag); }

// EventWarpSequence_CreateIn (ov36), al entrar en un mapa: el primero del equipo pasa a ser el que te sigue
void THUMB_BRANCH_LINK_36_0x21B77F8(void *gameData, u32 behind) {
    sGameData = gameData;
    void *eventWork = GameData_GetEventWork(gameData);
    adoptLegacy(gameData, eventWork);
    if (!storyPair(eventWork)) {
        u16 code = EventWork_FlagGet(eventWork, FLAG_FOLLOWER_OFF) ? 0 : leadObjCode(gameData);
        if (code == 0) {
            if (isOurs(eventWork)) {
                removeOurs(gameData, eventWork);
            }
        } else if (isOurs(eventWork)) {
            GetFieldFollowerCfg(gameData)->objCode = code;
        } else if (setupNpcFollower(gameData, FOLLOWER_INDEX, 1, FOLLOWER_ACTOR_ID, code, 0, 0)) {
            EventWork_FlagSet(eventWork, FLAG_FOLLOWER_OURS);
        }
    }
    TryRespawnFollowActor(gameData, behind);
}

// Scrcmd_PairSys_ActorPairSet (ov12): la historia pone a un aliado; el nuestro se va antes
bool THUMB_BRANCH_LINK_12_0x216A5F2(void *gameData, u8 index, u8 isPersistent, u32 originActorId, u16 objCode,
                                    u16 scrId, u16 trainerId) {
    void *eventWork = GameData_GetEventWork(gameData);
    if (isOurs(eventWork)) {
        removeOurs(gameData, eventWork);
    }
    return setupNpcFollower(gameData, index, isPersistent, originActorId, objCode, scrId, trainerId);
}

// FldeffShadow_Draw (ov36): la sombra se pone con el mismo desplazamiento que el modelo (wPosOffsetY de la tabla de
// modelos). follower_models.py baja los modelos de Pokémon para que no floten; su sombra se queda en el suelo, al nivel
// de la del entrenador
void THUMB_BRANCH_LINK_36_0x21A3D90(void *actor, ShadowOffset *offset) {
    CopyActorPosOffset(actor, offset);
    if (*GetActorMdlInfo(actor) >= OBJ_CODE_POKEMON_MIN) {
        offset->y = 0;
    }
}

// Scrcmd_PairSys_ActorPairEnd (ov12): no se aplica al nuestro (lo dejaría quieto en el sitio)
void *THUMB_BRANCH_LINK_12_0x216A644(void *mmSys, u16 id) {
    if (sGameData && isOurs(GameData_GetEventWork(sGameData))) {
        return 0;
    }
    return FindFieldActor(mmSys, id);
}

}
