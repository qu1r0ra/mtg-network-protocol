"""Code escape hatch for cards that don't reduce to primitives (ADR 0004).

A registry keyed by card base_id for genuinely novel mechanics (e.g. Gray Merchant
of Asphodel — life drain by devotion to black, an optional "you may" trigger). The
engine checks this registry before falling back to the data-driven primitives, so
the common case stays pure data and only real complexity lands here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mtgnp.protocol.catalog import base_id, load_catalog
from mtgnp.server.state import GameState, StackItem

Handler = Callable[[GameState, StackItem], list[dict]]
LegalTargetsFn = Callable[[GameState, str], list[str]]


@dataclass(frozen=True)
class TriggerSpec:
    """A registered trigger's shape (ADR 0007): whether it needs a target
    picked via TRIGGER_CHOICE before it can go on the stack, how to compute
    its legal targets, and the resolver that applies its effect once it
    resolves off the stack. `kicker_gated=True` marks an "intervening if it
    was kicked" trigger (e.g. Goblin Bushwhacker): discarded silently at
    drain time -- never placed on the stack -- if the spell that created it
    wasn't kicked, same discard idiom as an empty `legal_targets_fn`."""

    resolver: Handler
    requires_target: bool
    legal_targets_fn: LegalTargetsFn | None
    kicker_gated: bool = False


_REGISTRY: dict[str, TriggerSpec] = {}


def register(
    base_id: str,
    *,
    requires_target: bool = False,
    legal_targets_fn: LegalTargetsFn | None = None,
    kicker_gated: bool = False,
) -> Callable[[Handler], Handler]:
    """Decorator: `@register("gray_merchant")` registers a resolver for a
    TRIGGER_ABILITY (or ABILITY) StackItem whose source resolves to that
    base_id, called with the same (state, item) -> list[dict] shape as the
    primitives in effects.py. `requires_target=True` triggers pause via
    `pending_trigger_choice` (ADR 0007) instead of pushing immediately."""

    def _decorate(handler: Handler) -> Handler:
        _REGISTRY[base_id] = TriggerSpec(
            resolver=handler,
            requires_target=requires_target,
            legal_targets_fn=legal_targets_fn,
            kicker_gated=kicker_gated,
        )
        return handler

    return _decorate


def get(base_id: str) -> TriggerSpec | None:
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


@register("gray_merchant", requires_target=False)
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


def _gravedigger_legal_targets(state: GameState, controller_id: str) -> list[str]:
    """Creature cards in the controller's own graveyard (RFC §8.6.4: no
    legal targets -> discard the trigger, no STACK_PUSH)."""
    catalog = load_catalog()
    return [
        card_id
        for card_id in state.players[controller_id].graveyard
        if catalog[base_id(card_id)].card_type == "Creature"
    ]


@register("gravedigger", requires_target=True, legal_targets_fn=_gravedigger_legal_targets)
def _gravedigger(state: GameState, item: StackItem) -> list[dict]:
    """When Gravedigger enters, return target creature card from your
    graveyard to your hand (docs/references/master_card_list.tsv). Target
    was already chosen via TRIGGER_CHOICE before STACK_PUSH (ADR 0007)."""
    controller_id = item.controller_id
    target = item.targets[0]

    state.players[controller_id].graveyard.remove(target)
    state.players[controller_id].hand.append(target)
    return [{"type": "RETURN_TO_HAND", "target": target, "controller": controller_id}]


@register("goblin_bushwhacker", kicker_gated=True)
def _goblin_bushwhacker(state: GameState, item: StackItem) -> list[dict]:
    """When Goblin Bushwhacker enters, if it was kicked, creatures you
    control get +1/+0 and gain haste until end of turn (docs/references/
    master_card_list.tsv). `kicker_gated=True` means this only ever runs
    when the spell was actually kicked -- the drain-time gate discards the
    trigger unkicked, per the "intervening if" wording."""
    controller_id = item.controller_id
    changes = []
    for permanent in state.players[controller_id].battlefield:
        if permanent.power is None:  # non-creature permanent (e.g. a land)
            continue
        permanent.power_bonus += 1
        permanent.temp_haste = True
        changes.append({"type": "PUMP", "target": permanent.id, "power_bonus": 1, "haste": True})
    return changes
