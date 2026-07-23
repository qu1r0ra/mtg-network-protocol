"""CAST_SPELL handler (RFC §10.2.7): hand -> stack (RFC §8.3).

Validates mana payment against the resolved card's cost and targets against
its primitive effect's target_type, resolves `card_id` -> `Card` via the
catalog (protocol/catalog.py), removes the card from hand, and pushes a
StackItem (stack.py). The Active Player retains priority afterward per the
RFC §8.3 example -- stack.push does not re-grant it generically, so this
handler owns that call.

A different responsibility from stack.py (LIFO push/resolve mechanics):
cast.py depends on stack.py (calls stack.push as its last step), not the
reverse.
"""

from __future__ import annotations

import mtgnp.server.priority as priority
import mtgnp.server.stack as stack
from mtgnp.protocol.catalog import base_id, load_catalog
from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import CastSpell, Error
from mtgnp.server.engine import Outbound
from mtgnp.server.state import (
    GameState,
    StackItem,
    find_permanent,
    find_permanent_owner,
    is_targetable_by,
)

_TARGET_TYPE_ACCEPTS_PLAYER = {"any", "player"}
_TARGET_TYPE_ACCEPTS_CREATURE = {"any", "creature"}


def _illegal(
    connection_id: str, state: GameState, code: ErrorCode, message: str, pdu
) -> list[Outbound]:
    state.seq_num += 1
    return [
        Outbound(
            recipient=connection_id,
            pdu=Error(
                seq_num=state.seq_num,
                code=code.value,
                message=message,
                rejected_action=pdu.model_dump(),
            ),
        )
    ]


def _permanent_controller(state: GameState, target_id: str) -> str | None:
    """The id of whichever player's battlefield holds `target_id`, or None if
    it isn't a permanent (e.g. a player or stack-item/spell target) -- used to
    queue ADR 0011's targeted-trigger hook only for permanent targets."""
    found = find_permanent_owner(state, target_id)
    return found[0] if found else None


def _target_legal(
    state: GameState, target_id: str, target_type: str, caster_id: str
) -> bool:
    if target_id in state.players:
        return target_type in _TARGET_TYPE_ACCEPTS_PLAYER
    if target_type == "spell":
        return any(
            item.stack_item_id == target_id and item.item_type == "SPELL"
            for item in state.stack
        )
    if target_type not in _TARGET_TYPE_ACCEPTS_CREATURE:
        return False
    permanent = find_permanent(state, target_id)
    if permanent is None:
        return False
    return is_targetable_by(permanent, caster_id)


def handle_cast_spell(
    state: GameState, connection_id: str, pdu: CastSpell
) -> list[Outbound]:
    errors = priority.validate_priority(state, connection_id, pdu)
    if errors:
        return errors

    player_id = state.priority_holder
    player = state.players[player_id]

    if pdu.card_id not in player.hand:
        return _illegal(
            connection_id,
            state,
            ErrorCode.ILLEGAL_ACTION,
            f"'{pdu.card_id}' is not in hand.",
            pdu,
        )

    card = load_catalog().get(base_id(pdu.card_id))
    if card is None:
        return _illegal(
            connection_id,
            state,
            ErrorCode.ILLEGAL_ACTION,
            f"'{pdu.card_id}' is not a known card.",
            pdu,
        )

    if pdu.kicked and card.kicker_cost is None:
        return _illegal(
            connection_id,
            state,
            ErrorCode.ILLEGAL_ACTION,
            f"'{card.name}' has no kicker cost.",
            pdu,
        )

    required_cost = dict(card.mana_cost)
    if pdu.kicked:
        for key, amount in card.kicker_cost.items():
            required_cost[key] = required_cost.get(key, 0) + amount

    for key, required in required_cost.items():
        if pdu.mana_payment.get(key, 0) < required:
            return _illegal(
                connection_id,
                state,
                ErrorCode.INSUFFICIENT_MANA,
                f"Insufficient mana paid for '{card.name}' (needs {required_cost}).",
                pdu,
            )

    if card.effect is not None:
        target_type = card.effect["target_type"]
        if len(pdu.targets) != 1 or not _target_legal(
            state, pdu.targets[0], target_type, player_id
        ):
            return _illegal(
                connection_id,
                state,
                ErrorCode.ILLEGAL_TARGET,
                "Illegal or missing target.",
                pdu,
            )
    elif pdu.targets:
        return _illegal(
            connection_id,
            state,
            ErrorCode.ILLEGAL_TARGET,
            f"'{card.name}' has no legal targets.",
            pdu,
        )

    player.hand.remove(pdu.card_id)

    item = StackItem(
        stack_item_id=f"{pdu.card_id}_{state.seq_num + 1}",
        item_type="SPELL",
        source_id=pdu.card_id,
        controller_id=player_id,
        targets=pdu.targets,
        kicked=pdu.kicked,
    )
    outbounds = stack.push(state, item)

    is_noncreature = "Creature" not in card.card_type.split()
    state.pending_cast_trigger.append((player_id, is_noncreature))

    for target_id in pdu.targets:
        target_controller = _permanent_controller(state, target_id)
        if target_controller is not None:
            state.pending_targeted_trigger.append((target_id, target_controller))

    outbounds += priority.grant(state, player_id)
    return outbounds
