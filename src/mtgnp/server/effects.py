"""Primitive effect resolvers (ADR 0004).

The small closed vocabulary that most cards compile to. Each takes GameState + a
resolving StackItem and mutates state, returning the state_changes[] entries that
go into STACK_RESOLVE (RFC §8.4, §10.2.14). Cards declare their effect as data in
the catalog; the engine dispatches to the matching primitive here.

Primitives: DAMAGE, GAIN_LIFE, DESTROY, COUNTER, DRAW. Cards needing logic beyond
these register in custom_effects.py.
"""

from __future__ import annotations

from mtgnp.protocol.catalog import base_id, load_catalog
from mtgnp.server import custom_effects
from mtgnp.server.state import (
    GameState,
    Permanent,
    StackItem,
    find_permanent,
    find_permanent_owner,
)


def _apply_damage(state: GameState, item: StackItem, amount: int) -> list[dict]:
    target = item.targets[0]
    if target in state.players:
        state.players[target].life -= amount
    else:
        permanent = find_permanent(state, target)
        if permanent is not None:
            permanent.damage = (permanent.damage or 0) + amount
    return [{"type": "DAMAGE", "target": target, "amount": amount}]


def _apply_gain_life(state: GameState, item: StackItem, amount: int) -> list[dict]:
    target = item.targets[0]
    state.players[target].life += amount
    return [{"type": "GAIN_LIFE", "target": target, "amount": amount}]


def _apply_draw(state: GameState, item: StackItem, amount: int) -> list[dict]:
    """Draws for the spell's controller (the common "draw a card" shape in
    this set has no target -- e.g. Ponder), not a targeted player."""
    controller = state.players[item.controller_id]
    drawn = 0
    for _ in range(amount):
        if not controller.library:
            break
        controller.hand.append(controller.library.pop(0))
        drawn += 1
    return [{"type": "DRAW", "target": item.controller_id, "amount": drawn}]


def _apply_destroy(state: GameState, item: StackItem) -> list[dict]:
    target = item.targets[0]
    found = find_permanent_owner(state, target)
    if found is None:
        return []
    owner_id, permanent = found
    player = state.players[owner_id]
    player.battlefield.remove(permanent)
    player.graveyard.append(target)
    return [{"type": "DESTROY", "target": target}]


def _apply_counter(state: GameState, item: StackItem) -> list[dict]:
    """Counters a spell still on the stack (its resolving StackItem was
    already popped before apply() runs, so the target is looked up among
    what remains). The countered spell goes to its own controller's
    graveyard, not the counterspell's."""
    target = item.targets[0]
    for index, stack_item in enumerate(state.stack):
        if stack_item.stack_item_id == target:
            countered = state.stack.pop(index)
            state.players[countered.controller_id].graveyard.append(countered.source_id)
            return [{"type": "COUNTER", "target": target}]
    return []


def _apply_protect_and_pump(
    state: GameState, item: StackItem, power_bonus: int, toughness_bonus: int
) -> list[dict]:
    """ADR 0012: protects the target from the caster's opponents unconditionally,
    then adds the +N/+N pump only if the spell was kicked."""
    target = item.targets[0]
    permanent = find_permanent(state, target)
    if permanent is None:
        return []
    permanent.protected_by = item.controller_id
    changes = [
        {"type": "PROTECT", "target": target, "protected_by": item.controller_id}
    ]
    if item.kicked:
        permanent.power_bonus += power_bonus
        permanent.toughness_bonus += toughness_bonus
        changes.append(
            {
                "type": "PUMP",
                "target": target,
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        )
    return changes


_EFFECT_HANDLERS = {
    "DAMAGE": lambda state, item, effect: _apply_damage(state, item, effect["amount"]),
    "GAIN_LIFE": lambda state, item, effect: _apply_gain_life(
        state, item, effect["amount"]
    ),
    "DESTROY": lambda state, item, effect: _apply_destroy(state, item),
    "COUNTER": lambda state, item, effect: _apply_counter(state, item),
    "DRAW": lambda state, item, effect: _apply_draw(state, item, effect["amount"]),
    "PROTECT_AND_PUMP": lambda state, item, effect: _apply_protect_and_pump(
        state, item, effect["power_bonus"], effect["toughness_bonus"]
    ),
}


def _enter_battlefield(state: GameState, item: StackItem, card) -> list[dict]:
    """Creature spell with no primitive effect (ADR 0004): resolving puts a
    Permanent on its controller's battlefield. This is the ETB event Phase 3's
    trigger funnel (RFC §8.6) detects from -- ETB cards (Gravedigger, Gray
    Merchant) themselves resolve here with no further mutation; their trigger
    lands in custom_effects.py."""
    state.players[item.controller_id].battlefield.append(
        Permanent(
            id=item.source_id,
            power=card.power,
            toughness=card.toughness,
            damage=0,
            summoning_sick=True,
            haste="Haste" in card.keywords,
        )
    )
    state.pending_etb.append((item.source_id, item.controller_id, item.kicked))
    return [{"type": "ETB", "permanent_id": item.source_id}]


def apply(state: GameState, item: StackItem) -> list[dict]:
    """Dispatch to the primitive matching `item`'s card data (ADR 0004), or to
    the creature ETB path for card_type == "Creature" with no primitive
    effect. Only applies to item_type == "SPELL" -- a resolving
    TRIGGER_ABILITY/ABILITY is never a card entering the battlefield a second
    time (e.g. Gray Merchant's ETB trigger resolving off the stack must NOT
    re-run _enter_battlefield), so those dispatch to custom_effects.py's
    registry instead, keyed by the same base_id."""
    if item.item_type != "SPELL":
        spec = custom_effects.get(base_id(item.source_id))
        return spec.resolver(state, item) if spec is not None else []

    card = load_catalog().get(base_id(item.source_id))
    if card is None:
        return []

    if card.effect is not None:
        handler = _EFFECT_HANDLERS.get(card.effect["type"])
        if handler is not None:
            return handler(state, item, card.effect)

    if "Creature" in card.card_type.split():
        return _enter_battlefield(state, item, card)

    return []
