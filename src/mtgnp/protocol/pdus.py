"""PDU schemas — all 25 message types (RFC §10) as a pydantic v2 discriminated union.

Every PDU is modelled as a pydantic BaseModel with a literal `type` field. A
discriminated union keyed on `type` (`AnyPDU`) gives single-line dispatch and
automatic rejection of unknown types (mapped to ErrorCode.UNKNOWN_TYPE by the
engine's parse stage). Field-level validation encodes the RFC's required-field
and enum rules; parse failures map to ErrorCode.INVALID_JSON.

Every PDU carries `type` and `seq_num` (RFC §5.4). seq_num SEMANTICS (issuance,
echo, exemptions) are documented in ADR 0006 and enforced by the engine, NOT
here — this module only guarantees the field is present and integer-typed.

Direction legend (RFC §10.1): C->S client->server, S->C server->one client,
S->ALL server broadcast.

`state`, `state_changes`, and `rejected_action` are intentionally untyped
(`dict`/loose `object`) here: their shapes are game-state/echo payloads owned
by the engine, not wire-format decisions this module should freeze.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


# --- Base --------------------------------------------------------------------
class _PDU(BaseModel):
    seq_num: int


# --- Lifecycle / lobby (RFC §6, §10.2.1-3, §10.2.22) --------------------------
class PlayerReady(_PDU):
    """C->S (§10.2.1)"""

    type: Literal["PLAYER_READY"] = "PLAYER_READY"
    player_id: str
    deck_list: list[str]


class GameStateUpdate(_PDU):
    """S->C (§10.2.2), personalized. `state` shape varies by phase (lobby vs
    in-game); left untyped here, the engine owns its construction."""

    type: Literal["GAME_STATE_UPDATE"] = "GAME_STATE_UPDATE"
    state: dict[str, Any]


class MulliganChoice(_PDU):
    """C->S (§10.2.3)"""

    type: Literal["MULLIGAN_CHOICE"] = "MULLIGAN_CHOICE"
    keep: bool
    cards_to_bottom: list[str]


class GameOver(_PDU):
    """S->ALL (§10.2.22)"""

    type: Literal["GAME_OVER"] = "GAME_OVER"
    winner_id: str
    loser_id: str
    reason: Literal["LIFE_ZERO", "DECK_EMPTY", "CONCEDE", "DISCONNECT"]


# --- Turn / priority (RFC §7, §8, §10.2.4-8, §10.2.19-20) --------------------
Phase = Literal[
    "UNTAP",
    "UPKEEP",
    "DRAW",
    "PRECOMBAT_MAIN",
    "BEGIN_COMBAT",
    "DECLARE_ATTACKERS",
    "DECLARE_BLOCKERS",
    "ASSIGN_DAMAGE_ORDER",
    "FIRST_STRIKE_DAMAGE",
    "COMBAT_DAMAGE",
    "END_OF_COMBAT",
    "POSTCOMBAT_MAIN",
    "END_STEP",
    "CLEANUP",
]


class PhaseTransition(_PDU):
    """S->ALL (§10.2.4). from_phase additionally allows "MULLIGAN": the very
    first PHASE_TRANSITION of a game follows MULLIGAN -> UNTAP directly (RFC
    §6.4 example), never a turn Phase, since no turn has begun yet."""

    type: Literal["PHASE_TRANSITION"] = "PHASE_TRANSITION"
    from_phase: Phase | Literal["MULLIGAN"]
    to_phase: Phase
    active_player: str
    turn: int


class PriorityGrant(_PDU):
    """S->C (§10.2.5)"""

    type: Literal["PRIORITY_GRANT"] = "PRIORITY_GRANT"
    player_id: str
    time_limit_ms: int


class PriorityPass(_PDU):
    """C->S (§10.2.6). Exempt from priority-echo validation? No — this one IS
    the echo (seq_num must match current PRIORITY_GRANT token, ADR 0006)."""

    type: Literal["PRIORITY_PASS"] = "PRIORITY_PASS"


class CastSpell(_PDU):
    """C->S (§10.2.7)"""

    type: Literal["CAST_SPELL"] = "CAST_SPELL"
    card_id: str
    targets: list[str]
    mana_payment: dict[str, int]


class ActivateAbility(_PDU):
    """C->S (§10.2.8)"""

    type: Literal["ACTIVATE_ABILITY"] = "ACTIVATE_ABILITY"
    source_id: str
    ability_index: int
    targets: list[str]
    cost_payment: dict[str, Any]


class PlayLand(_PDU):
    """C->S (§10.2.19)"""

    type: Literal["PLAY_LAND"] = "PLAY_LAND"
    card_id: str


class Discard(_PDU):
    """C->S (§10.2.20)"""

    type: Literal["DISCARD"] = "DISCARD"
    card_ids: list[str]


# --- Stack / triggers (RFC §8.3-8.6, §10.2.9-14) -----------------------------
class StackPush(_PDU):
    """S->ALL (§10.2.9)"""

    type: Literal["STACK_PUSH"] = "STACK_PUSH"
    stack_item_id: str
    item_type: Literal["SPELL", "ABILITY", "TRIGGER_ABILITY"]
    source: str
    targets: list[str]
    controller: str


class TriggerOrder(_PDU):
    """S->C (§10.2.10)"""

    type: Literal["TRIGGER_ORDER"] = "TRIGGER_ORDER"
    player_id: str
    trigger_ids: list[str]


class TriggerOrderResponse(_PDU):
    """C->S (§10.2.11)"""

    type: Literal["TRIGGER_ORDER_RESPONSE"] = "TRIGGER_ORDER_RESPONSE"
    ordered_trigger_ids: list[str]


class TriggerChoice(_PDU):
    """S->C (§10.2.12)"""

    type: Literal["TRIGGER_CHOICE"] = "TRIGGER_CHOICE"
    trigger_id: str
    source_id: str
    effect_summary: str
    requires_target: bool
    legal_targets: list[str]


class TriggerChoiceResponse(_PDU):
    """C->S (§10.2.13). chosen_target non-null only when accept=True AND the
    corresponding TRIGGER_CHOICE had requires_target=True."""

    type: Literal["TRIGGER_CHOICE_RESPONSE"] = "TRIGGER_CHOICE_RESPONSE"
    trigger_id: str
    accept: bool
    chosen_target: str | None = None


class StackResolve(_PDU):
    """S->ALL (§10.2.14). state_changes elements are heterogeneous
    (change_type-keyed); left untyped, the engine owns their construction."""

    type: Literal["STACK_RESOLVE"] = "STACK_RESOLVE"
    stack_item_id: str
    result: Literal["RESOLVED", "FIZZLE"]
    state_changes: list[dict[str, Any]]


# --- Combat (RFC §9, §10.2.15-18) --------------------------------------------
class AttackerDeclaration(BaseModel):
    creature_id: str
    target: str


class DeclareAttackers(_PDU):
    """C->S (§10.2.15)"""

    type: Literal["DECLARE_ATTACKERS"] = "DECLARE_ATTACKERS"
    attackers: list[AttackerDeclaration]


class BlockerDeclaration(BaseModel):
    creature_id: str
    blocking_id: str


class DeclareBlockers(_PDU):
    """C->S (§10.2.16)"""

    type: Literal["DECLARE_BLOCKERS"] = "DECLARE_BLOCKERS"
    blockers: list[BlockerDeclaration]


class AssignDamageOrder(_PDU):
    """C->S (§10.2.17)"""

    type: Literal["ASSIGN_DAMAGE_ORDER"] = "ASSIGN_DAMAGE_ORDER"
    attacker_id: str
    blocker_order: list[str]


class DamageEvent(BaseModel):
    source: str
    target: str
    amount: int


class CombatDamageResult(_PDU):
    """S->ALL (§10.2.18)"""

    type: Literal["COMBAT_DAMAGE_RESULT"] = "COMBAT_DAMAGE_RESULT"
    damage_events: list[DamageEvent]
    life_totals: dict[str, int]
    creatures_died: list[str]


# --- Any-time / control (RFC §5.4, §11, §4.3, §10.2.21, §10.2.23-25) ---------
class Concede(_PDU):
    """C->S (§10.2.21). Exempt from priority-echo validation (ADR 0006)."""

    type: Literal["CONCEDE"] = "CONCEDE"
    player_id: str


class Error(_PDU):
    """S->C (§10.2.23). rejected_action echoes the original PDU payload when
    available (e.g. absent for INVALID_JSON, where no PDU could be parsed)."""

    type: Literal["ERROR"] = "ERROR"
    code: str  # ErrorCode value; kept as str to avoid a circular import
    message: str
    rejected_action: dict[str, Any] | None = None


class Ping(_PDU):
    """C->S (§10.2.24). Exempt from priority-echo validation (ADR 0006)."""

    type: Literal["PING"] = "PING"
    timestamp: int


class Pong(_PDU):
    """S->C (§10.2.25). Echoes the client's PING seq_num and timestamp."""

    type: Literal["PONG"] = "PONG"
    timestamp: int


AnyPDU = Annotated[
    Union[
        PlayerReady,
        GameStateUpdate,
        MulliganChoice,
        GameOver,
        PhaseTransition,
        PriorityGrant,
        PriorityPass,
        CastSpell,
        ActivateAbility,
        PlayLand,
        Discard,
        StackPush,
        TriggerOrder,
        TriggerOrderResponse,
        TriggerChoice,
        TriggerChoiceResponse,
        StackResolve,
        DeclareAttackers,
        DeclareBlockers,
        AssignDamageOrder,
        CombatDamageResult,
        Concede,
        Error,
        Ping,
        Pong,
    ],
    Field(discriminator="type"),
]
