"""State-based actions + trigger funnel — the single post-event pipeline (RFC §8.4, §8.6).

CRITICAL (advisor R4): after EVERY game event, before ANY priority is granted:
  1. Apply state-based actions repeatedly until none remain:
       * creature toughness <= 0 -> graveyard
       * creature damage >= toughness -> destroyed -> graveyard
       * life <= 0 -> that player loses (GAME_OVER LIFE_ZERO; simultaneous -> NAP wins)
  2. Detect triggered abilities from those events and place them on the stack,
     ordered AP-first (bottom) then NAP (top); a controller with >=2 simultaneous
     triggers is asked via TRIGGER_ORDER; optional "you may" triggers via
     TRIGGER_CHOICE; targeted triggers pick a target before STACK_PUSH.
  3. Only then grant priority.

Every action handler in the engine routes through resolve() before returning, so
this ordering is enforced in exactly one place rather than scattered per phase.

This session adds the toughness/lethal-damage sweep (step 1, in full). The
trigger funnel (step 2) is still deferred: nothing on the battlefield declares
triggered abilities yet (no CAST_SPELL/combat/catalog wired), so there is no
real event to detect a trigger from — building TRIGGER_ORDER/TRIGGER_CHOICE
handling now would be guessing at their shape rather than testing it.
"""

from __future__ import annotations

import mtgnp.server.lifecycle as lifecycle
import mtgnp.server.stack as stack
from mtgnp.protocol.catalog import base_id
from mtgnp.protocol.pdus import TriggerChoice
from mtgnp.server import custom_effects
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, PendingTriggerChoice, StackItem


def _sweep_lethal_creatures(state: GameState) -> None:
    """RFC §8.4: toughness <= 0, or damage >= toughness -> owner's graveyard.
    Non-creature permanents (toughness is None) are never swept here."""
    for player in state.players.values():
        survivors = []
        for permanent in player.battlefield:
            lethal = permanent.toughness is not None and (
                permanent.toughness <= 0 or (permanent.damage or 0) >= permanent.toughness
            )
            if lethal:
                player.graveyard.append(permanent.id)
            else:
                survivors.append(permanent)
        player.battlefield = survivors


def _slot_for(state: GameState, player_id: str) -> str:
    return next(slot for slot, claimed in state.connections.items() if claimed == player_id)


def _drain_pending_etb(state: GameState) -> list[Outbound]:
    """Place a TRIGGER_ABILITY for each drained ETB whose base_id is
    registered in custom_effects; unregistered entries (e.g. vanilla
    creatures) are dropped silently. Targeted triggers (ADR 0007) hold in
    `pending_trigger_choice` and emit TRIGGER_CHOICE instead of pushing
    immediately -- with no legal targets, RFC §8.6.4 discards them silently.
    Triggers are only ever placed while the game is still live -- see
    resolve()'s `not dead` guard."""
    pending, state.pending_etb = state.pending_etb, []
    outbounds: list[Outbound] = []
    for permanent_id, controller_id in pending:
        spec = custom_effects.get(base_id(permanent_id))
        if spec is None:
            continue

        if spec.requires_target:
            legal_targets = spec.legal_targets_fn(state, controller_id)
            if not legal_targets:
                continue
            state.seq_num += 1
            trigger_id = f"{permanent_id}_trigger_{state.seq_num}"
            state.pending_trigger_choice = PendingTriggerChoice(
                trigger_id=trigger_id,
                source_id=permanent_id,
                controller_id=controller_id,
                legal_targets=legal_targets,
            )
            outbounds.append(
                Outbound(
                    recipient=_slot_for(state, controller_id),
                    pdu=TriggerChoice(
                        seq_num=state.seq_num,
                        trigger_id=trigger_id,
                        source_id=permanent_id,
                        effect_summary=base_id(permanent_id),
                        requires_target=True,
                        legal_targets=legal_targets,
                    ),
                )
            )
            continue

        item = StackItem(
            stack_item_id=f"{permanent_id}_trigger_{state.seq_num + 1}",
            item_type="TRIGGER_ABILITY",
            source_id=permanent_id,
            controller_id=controller_id,
            targets=[],
        )
        outbounds += stack.push(state, item)
    return outbounds


def resolve(state: GameState) -> list[Outbound]:
    """SBA loop -> trigger placement; may end the game (RFC §8.4)."""
    _sweep_lethal_creatures(state)

    dead = [player_id for player_id, player in state.players.items() if player.life <= 0]
    if not dead:
        return _drain_pending_etb(state)

    if len(dead) == len(state.players):
        winner_id = next(pid for pid in state.players if pid != state.active_player)
    else:
        loser_id = dead[0]
        winner_id = next(pid for pid in state.players if pid != loser_id)

    return lifecycle.enter_game_over(state, winner_id, "LIFE_ZERO")
