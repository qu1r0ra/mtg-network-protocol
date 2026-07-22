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
from mtgnp.server.state import GameState, Permanent, StackItem


def _apply_damage(state: GameState, item: StackItem, amount: int) -> list[dict]:
    target = item.targets[0]
    if target in state.players:
        state.players[target].life -= amount
    else:
        for player in state.players.values():
            for permanent in player.battlefield:
                if permanent.id == target:
                    permanent.damage = (permanent.damage or 0) + amount
    return [{"type": "DAMAGE", "target": target, "amount": amount}]


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
        )
    )
    return [{"type": "ETB", "permanent_id": item.source_id}]


def apply(state: GameState, item: StackItem) -> list[dict]:
    """Dispatch to the primitive matching `item`'s card data (ADR 0004), or to
    the creature ETB path for card_type == "Creature" with no primitive
    effect. Cards needing real logic beyond that (Gravedigger's graveyard
    target, Gray Merchant's devotion math) resolve via custom_effects.py,
    wired in Phase 3 -- until then they resolve as a bare ETB with no further
    effect."""
    card = load_catalog().get(base_id(item.source_id))
    if card is None:
        return []

    if card.effect is not None and card.effect["type"] == "DAMAGE":
        return _apply_damage(state, item, card.effect["amount"])

    if card.card_type == "Creature":
        return _enter_battlefield(state, item, card)

    return []
