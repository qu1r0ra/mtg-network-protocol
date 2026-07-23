"""Code escape hatch for cards that don't reduce to primitives (ADR 0004).

A registry keyed by card base_id for genuinely novel mechanics (e.g. Gray Merchant
of Asphodel — life drain by devotion to black, an optional "you may" trigger). The
engine checks this registry before falling back to the data-driven primitives, so
the common case stays pure data and only real complexity lands here.
"""

from __future__ import annotations

from typing import Callable

from mtgnp.protocol.catalog import base_id, load_catalog
from mtgnp.server.state import GameState, StackItem

Handler = Callable[[GameState, StackItem], list[dict]]

_REGISTRY: dict[str, Handler] = {}


def register(base_id: str) -> Callable[[Handler], Handler]:
    """Decorator: `@register("gray_merchant")` registers a resolver for a
    TRIGGER_ABILITY (or ABILITY) StackItem whose source resolves to that
    base_id, called with the same (state, item) -> list[dict] shape as the
    primitives in effects.py."""

    def _decorate(handler: Handler) -> Handler:
        _REGISTRY[base_id] = handler
        return handler

    return _decorate


def get(base_id: str) -> Handler | None:
    return _REGISTRY.get(base_id)


def _devotion_to_black(state: GameState, controller_id: str) -> int:
    """Sum of black mana symbols in the controller's own mana costs (RFC
    devotion), across every permanent on their battlefield -- including the
    ETB permanent itself, since it's already there by the time its trigger
    resolves (place-then-resolve)."""
    catalog = load_catalog()
    total = 0
    for permanent in state.players[controller_id].battlefield:
        card = catalog.get(base_id(permanent.id))
        if card is not None:
            total += card.mana_cost.get("B", 0)
    return total


@register("gray_merchant")
def _gray_merchant(state: GameState, item: StackItem) -> list[dict]:
    """When Gray Merchant enters, each opponent loses X life and its
    controller gains X life, X = devotion to black (docs/references/
    master_card_list.tsv)."""
    controller_id = item.controller_id
    devotion = _devotion_to_black(state, controller_id)

    changes = []
    for player_id, player in state.players.items():
        if player_id == controller_id:
            continue
        player.life -= devotion
        changes.append({"type": "DRAIN", "source": controller_id, "target": player_id, "amount": devotion})

    state.players[controller_id].life += devotion
    changes.append({"type": "GAIN_LIFE", "target": controller_id, "amount": devotion})
    return changes
