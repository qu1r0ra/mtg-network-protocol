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
            toughness = None if permanent.toughness is None else permanent.toughness + permanent.toughness_bonus
            lethal = toughness is not None and (toughness <= 0 or (permanent.damage or 0) >= toughness)
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
    for permanent_id, controller_id, kicked in pending:
        spec = custom_effects.get(base_id(permanent_id))
        if spec is None or spec.kind != "etb":
            continue
        if spec.kicker_gated and not kicked:
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


def _drain_pending_attack_trigger(state: GameState) -> list[Outbound]:
    """Twin of _drain_pending_etb (ADR 0009): places a TRIGGER_ABILITY for
    each drained declared attacker whose base_id is registered in
    custom_effects (e.g. Goblin Guide); vanilla attackers are dropped
    silently. No requires_target/kicker_gated branch -- no attack-triggered
    card in this set needs either yet; extend to match _drain_pending_etb's
    shape if one does."""
    pending, state.pending_attack_trigger = state.pending_attack_trigger, []
    outbounds: list[Outbound] = []
    for attacker_id, controller_id in pending:
        spec = custom_effects.get(base_id(attacker_id))
        if spec is None or spec.kind != "attack":
            continue
        item = StackItem(
            stack_item_id=f"{attacker_id}_trigger_{state.seq_num + 1}",
            item_type="TRIGGER_ABILITY",
            source_id=attacker_id,
            controller_id=controller_id,
            targets=[],
        )
        outbounds += stack.push(state, item)
    return outbounds


def _drain_pending_cast_trigger(state: GameState) -> list[Outbound]:
    """ADR 0010: unlike _drain_pending_etb/_drain_pending_attack_trigger,
    the queued entity (the caster) is not the trigger source -- the source
    is a *different* permanent already on the caster's battlefield (e.g.
    Monastery Swiftspear). So this drain scans the caster's battlefield for
    any permanent registered with kind="cast", instead of looking up the
    queued entity's own base_id. Vanilla battlefields, and creature-spell
    casts (is_noncreature=False), are dropped without a scan."""
    pending, state.pending_cast_trigger = state.pending_cast_trigger, []
    outbounds: list[Outbound] = []
    for caster_id, is_noncreature in pending:
        if not is_noncreature:
            continue
        for permanent in state.players[caster_id].battlefield:
            spec = custom_effects.get(base_id(permanent.id))
            if spec is None or spec.kind != "cast":
                continue
            item = StackItem(
                stack_item_id=f"{permanent.id}_trigger_{state.seq_num + 1}",
                item_type="TRIGGER_ABILITY",
                source_id=permanent.id,
                controller_id=caster_id,
                targets=[],
            )
            outbounds += stack.push(state, item)
    return outbounds


def resolve(state: GameState) -> list[Outbound]:
    """SBA loop -> trigger placement; may end the game (RFC §8.4)."""
    _sweep_lethal_creatures(state)

    dead = [player_id for player_id, player in state.players.items() if player.life <= 0]
    if not dead:
        return (
            _drain_pending_etb(state)
            + _drain_pending_attack_trigger(state)
            + _drain_pending_cast_trigger(state)
        )

    if len(dead) == len(state.players):
        winner_id = next(pid for pid in state.players if pid != state.active_player)
    else:
        loser_id = dead[0]
        winner_id = next(pid for pid in state.players if pid != loser_id)

    return lifecycle.enter_game_over(state, winner_id, "LIFE_ZERO")
