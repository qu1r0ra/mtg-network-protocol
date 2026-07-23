"""Turn/phase driver — walks the fixed 14-phase sequence (RFC §7).

Each phase/step is handled explicitly; the driver advances through the ordered
Phase sequence, opening a PriorityWindow (priority.py) on steps that grant one
and transitioning automatically on those that do not (UNTAP, CLEANUP). Combat is
delegated to combat.py. Turn-1 first player skips the DRAW (RFC §7.4) — written
from the RFC, NOT from examples.md, which self-declares a deviation there (advisor
R3). Cleanup handles >7-card discard, damage/effect clearing, turn++ and AP swap
(RFC §7.8).

Every step-advance routes through sba.resolve (advisor R4) before any priority is
granted.

This session stops at the BEGIN_COMBAT wall: `advance()` broadcasts the
PRECOMBAT_MAIN -> BEGIN_COMBAT transition and then calls into combat.py, which is
still a stub (NotImplementedError) — the full combat sub-state machine (RFC §9)
is a later session's build. POSTCOMBAT_MAIN onward is independently reachable by
constructing a GameState already in that phase (as combat.py will do once it
hands control back), so it doesn't require driving through combat to test.
"""

from __future__ import annotations

import mtgnp.server.priority as priority
from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import Discard, Error, GameStateUpdate, PhaseTransition, PlayLand
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, Lifecycle, Permanent, Phase

_PHASE_ORDER = [
    Phase.UPKEEP,
    Phase.DRAW,
    Phase.PRECOMBAT_MAIN,
    Phase.BEGIN_COMBAT,
    Phase.POSTCOMBAT_MAIN,
    Phase.END_STEP,
    Phase.CLEANUP,
]

_MAIN_PHASES = {Phase.PRECOMBAT_MAIN, Phase.POSTCOMBAT_MAIN}


def _other(state: GameState, player_id: str) -> str:
    return next(pid for pid in state.players if pid != player_id)


def _permanent_view(permanent: Permanent) -> dict:
    view = {"id": permanent.id, "tapped": permanent.tapped}
    if permanent.power is not None:
        view["power"] = permanent.power + permanent.power_bonus
        view["toughness"] = permanent.toughness + permanent.toughness_bonus
        view["damage"] = permanent.damage
        view["summoning_sick"] = permanent.summoning_sick
    return view


def _in_game_view(state: GameState, player_id: str) -> dict:
    """Personalized IN_GAME GAME_STATE_UPDATE payload (own hand visible,
    opponent hand collapsed to a count — RFC §3 Visible State)."""
    other_id = _other(state, player_id)
    player_ids = [player_id, other_id]
    return {
        "turn": state.turn,
        "phase": state.phase.value if state.phase else None,
        "active_player": state.active_player,
        "life_totals": {pid: state.players[pid].life for pid in player_ids},
        "land_played": state.land_played_this_turn,
        "battlefield": {
            pid: [_permanent_view(p) for p in state.players[pid].battlefield]
            for pid in player_ids
        },
        "hand": state.players[player_id].hand,
        "hand_counts": {other_id: len(state.players[other_id].hand)},
        "library_counts": {pid: len(state.players[pid].library) for pid in player_ids},
        "graveyard": {pid: state.players[pid].graveyard for pid in player_ids},
        "stack": [
            {
                "stack_item_id": item.stack_item_id,
                "item_type": item.item_type,
                "source": item.source_id,
                "targets": item.targets,
                "controller": item.controller_id,
            }
            for item in state.stack
        ],
    }


def broadcast_state(state: GameState) -> list[Outbound]:
    """Personalized GAME_STATE_UPDATE to every connected slot. Public: stack.py
    (and future combat.py) reuse this rather than duplicating hidden-info
    filtering (RFC §3 Visible State)."""
    outbounds = []
    for slot, player_id in state.connections.items():
        state.seq_num += 1
        outbounds.append(
            Outbound(
                recipient=slot,
                pdu=GameStateUpdate(seq_num=state.seq_num, state=_in_game_view(state, player_id)),
            )
        )
    return outbounds


def _transition(state: GameState, from_phase: str, to_phase: Phase) -> Outbound:
    state.seq_num += 1
    outbound = Outbound(
        recipient="ALL",
        pdu=PhaseTransition(
            seq_num=state.seq_num,
            from_phase=from_phase,
            to_phase=to_phase.value,
            active_player=state.active_player,
            turn=state.turn,
        ),
    )
    state.phase = to_phase
    return outbound


def begin_turn(state: GameState, from_phase: str) -> list[Outbound]:
    """RFC §7.2: untap AP's permanents, reset land_played_this_turn, broadcast
    state, then immediately open the UPKEEP priority window."""
    outbounds = [_transition(state, from_phase, Phase.UNTAP)]

    ap = state.players[state.active_player]
    for permanent in ap.battlefield:
        permanent.tapped = False
    state.land_played_this_turn = False

    outbounds += broadcast_state(state)
    outbounds.append(_transition(state, Phase.UNTAP.value, Phase.UPKEEP))
    outbounds += priority.grant(state, state.active_player)
    return outbounds


def _do_draw(state: GameState) -> list[Outbound]:
    """RFC §7.4: draw one card for the AP, except turn 1's first player, who
    skips the draw entirely."""
    if state.turn != 1:
        ap = state.players[state.active_player]
        if not ap.library:
            import mtgnp.server.lifecycle as lifecycle

            winner_id = _other(state, state.active_player)
            return lifecycle.enter_game_over(state, winner_id, "DECK_EMPTY")
        ap.hand.append(ap.library.pop(0))
    return broadcast_state(state)


def advance(state: GameState) -> list[Outbound]:
    """Both players passed with an empty stack: move to the next phase/step
    (RFC §8.1 rule 6) and open its priority window, or run that phase's
    automatic behavior (DRAW's card-draw, CLEANUP's discard/turn-end)."""
    current = state.phase
    next_phase = _PHASE_ORDER[_PHASE_ORDER.index(current) + 1]
    outbounds = [_transition(state, current.value, next_phase)]

    if next_phase == Phase.DRAW:
        draw_outbounds = _do_draw(state)
        outbounds += draw_outbounds
        if state.lifecycle != Lifecycle.IN_GAME:
            # enter_game_over (DECK_EMPTY) resets straight to LOBBY (RFC §6.6)
            return outbounds
        outbounds += priority.grant(state, state.active_player)
        return outbounds

    if next_phase == Phase.BEGIN_COMBAT:
        import mtgnp.server.combat as combat

        return outbounds + combat.begin_combat(state)

    if next_phase == Phase.CLEANUP:
        return outbounds + _enter_cleanup(state)

    outbounds += priority.grant(state, state.active_player)
    return outbounds


def handle_play_land(state: GameState, connection_id: str, pdu: PlayLand) -> list[Outbound]:
    """RFC §7.5: one land per turn, Main Phase only, no stack, AP retains
    priority afterward."""
    errors = priority.validate_priority(state, connection_id, pdu)
    if errors:
        return errors

    player_id = state.priority_holder
    if state.phase not in _MAIN_PHASES:
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.WRONG_PHASE.value,
                    message="Lands may only be played during a Main Phase.",
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    player = state.players[player_id]
    if player_id != state.active_player:
        message = "Only the Active Player may play a land."
    elif state.land_played_this_turn:
        message = "Only one land may be played per turn."
    elif pdu.card_id not in player.hand:
        message = f"'{pdu.card_id}' is not in hand."
    else:
        message = None

    if message is not None:
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.ILLEGAL_ACTION.value,
                    message=message,
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    player.hand.remove(pdu.card_id)
    player.battlefield.append(Permanent(id=pdu.card_id))
    state.land_played_this_turn = True

    outbounds = broadcast_state(state)
    outbounds += priority.grant(state, player_id)
    return outbounds


def handle_discard(state: GameState, connection_id: str, pdu: Discard) -> list[Outbound]:
    """RFC §7.8: forced discard down to seven cards at Cleanup. No priority is
    active here, so this isn't gated through priority.validate_priority."""
    player_id = state.connections[connection_id]
    if player_id != state.active_player:
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.ILLEGAL_ACTION.value,
                    message="Only the Active Player discards at Cleanup.",
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    player = state.players[player_id]
    if not set(pdu.card_ids) <= set(player.hand):
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.ILLEGAL_ACTION.value,
                    message="card_ids must all be present in hand.",
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    for card_id in pdu.card_ids:
        player.hand.remove(card_id)
        player.graveyard.append(card_id)

    outbounds = broadcast_state(state)
    if len(player.hand) > 7:
        return outbounds
    return outbounds + _finish_cleanup(state)


def _enter_cleanup(state: GameState) -> list[Outbound]:
    ap = state.players[state.active_player]
    if len(ap.hand) > 7:
        return broadcast_state(state)
    return _finish_cleanup(state)


def _finish_cleanup(state: GameState) -> list[Outbound]:
    """RFC §7.8: clear damage, broadcast the cleared state, then increment the
    turn and swap the Active Player before starting the next turn's Untap."""
    for player in state.players.values():
        for permanent in player.battlefield:
            if permanent.damage is not None:
                permanent.damage = 0
            permanent.power_bonus = 0
            permanent.toughness_bonus = 0
            permanent.temp_haste = False
            permanent.protected_by = None

    outbounds = broadcast_state(state)

    state.turn += 1
    state.active_player = _other(state, state.active_player)
    return outbounds + begin_turn(state, Phase.CLEANUP.value)
