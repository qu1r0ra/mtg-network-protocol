"""Code escape hatch for cards that don't reduce to primitives (ADR 0004).

A registry keyed by card base_id for genuinely novel mechanics (e.g. Gray Merchant
of Asphodel — life drain by devotion to black, an optional "you may" trigger). The
engine checks this registry before falling back to the data-driven primitives, so
the common case stays pure data and only real complexity lands here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from mtgnp.protocol.catalog import base_id, load_catalog
from mtgnp.server.state import GameState, StackItem

Handler = Callable[[GameState, StackItem], list[dict]]
LegalTargetsFn = Callable[[GameState, str], list[str]]
TriggerKind = Literal["etb", "attack", "cast", "targeted"]


@dataclass(frozen=True)
class TriggerSpec:
    """A registered trigger's shape (ADR 0007): whether it needs a target
    picked via TRIGGER_CHOICE before it can go on the stack, how to compute
    its legal targets, and the resolver that applies its effect once it
    resolves off the stack. `kicker_gated=True` marks an "intervening if it
    was kicked" trigger (e.g. Goblin Bushwhacker): discarded silently at
    drain time -- never placed on the stack -- if the spell that created it
    wasn't kicked, same discard idiom as an empty `legal_targets_fn`.

    `kind` (ADR 0010) tags which pending-queue this resolver belongs to --
    `_drain_pending_etb`/`_drain_pending_attack_trigger` only fire specs
    whose `kind` matches their own queue, so a permanent registered for one
    trigger source (e.g. Goblin Guide's attack-trigger) can't misfire when a
    different queue's drain happens to scan past it (e.g. the cast-trigger
    drain's battlefield scan, ADR 0010). `kind="targeted"` (ADR 0011) fires
    whenever the registered permanent becomes the target of a spell or
    ability."""

    resolver: Handler
    requires_target: bool
    legal_targets_fn: LegalTargetsFn | None
    kind: TriggerKind
    kicker_gated: bool = False


_REGISTRY: dict[str, TriggerSpec] = {}


def register(
    base_id: str,
    *,
    kind: TriggerKind,
    requires_target: bool = False,
    legal_targets_fn: LegalTargetsFn | None = None,
    kicker_gated: bool = False,
) -> Callable[[Handler], Handler]:
    """Decorator: `@register("gray_merchant", kind="etb")` registers a
    resolver for a TRIGGER_ABILITY (or ABILITY) StackItem whose source
    resolves to that base_id, called with the same (state, item) ->
    list[dict] shape as the primitives in effects.py. `requires_target=True`
    triggers pause via `pending_trigger_choice` (ADR 0007) instead of pushing
    immediately. `kind` (ADR 0010) must match the pending-queue this trigger
    fires from -- `"etb"`, `"attack"`, or `"cast"`."""

    def _decorate(handler: Handler) -> Handler:
        _REGISTRY[base_id] = TriggerSpec(
            resolver=handler,
            requires_target=requires_target,
            legal_targets_fn=legal_targets_fn,
            kind=kind,
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


@register("gray_merchant", kind="etb", requires_target=False)
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
        changes.append(
            {
                "type": "DRAIN",
                "source": controller_id,
                "target": player_id,
                "amount": devotion,
            }
        )

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


@register(
    "gravedigger",
    kind="etb",
    requires_target=True,
    legal_targets_fn=_gravedigger_legal_targets,
)
def _gravedigger(state: GameState, item: StackItem) -> list[dict]:
    """When Gravedigger enters, return target creature card from your
    graveyard to your hand (docs/references/master_card_list.tsv). Target
    was already chosen via TRIGGER_CHOICE before STACK_PUSH (ADR 0007)."""
    controller_id = item.controller_id
    target = item.targets[0]

    state.players[controller_id].graveyard.remove(target)
    state.players[controller_id].hand.append(target)
    return [{"type": "RETURN_TO_HAND", "target": target, "controller": controller_id}]


@register("goblin_bushwhacker", kind="etb", kicker_gated=True)
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
        changes.append(
            {"type": "PUMP", "target": permanent.id, "power_bonus": 1, "haste": True}
        )
    return changes


@register("goblin_guide", kind="attack")
def _goblin_guide(state: GameState, item: StackItem) -> list[dict]:
    """Whenever Goblin Guide attacks, defending player reveals top card of
    library; if it's a land, that player puts it into their hand (docs/
    references/master_card_list.tsv). Defender is read from state.attackers
    at resolution time (ADR 0009) -- still populated, cleared only at
    END_OF_COMBAT. An empty library has no card to reveal: no-op, matching
    the real-rules "reveal" doing nothing when there's nothing to show."""
    defender_id = state.attackers[item.source_id]
    library = state.players[defender_id].library
    if not library:
        return []

    top_card = library[0]
    catalog = load_catalog()
    is_land = "Land" in catalog[base_id(top_card)].card_type.split()
    if is_land:
        library.pop(0)
        state.players[defender_id].hand.append(top_card)
    return [
        {
            "type": "REVEAL",
            "player": defender_id,
            "card": top_card,
            "moved_to_hand": is_land,
        }
    ]


@register("monastery_swiftspear", kind="cast")
def _monastery_swiftspear(state: GameState, item: StackItem) -> list[dict]:
    """Prowess (docs/references/master_card_list.tsv): whenever you cast a
    noncreature spell, this creature gets +1/+1 until end of turn (ADR 0010).
    `item.source_id` is Swiftspear itself -- the cast-trigger drain scans the
    caster's battlefield rather than the queued (cast) entity, since the
    trigger source and the cast spell are different permanents. Swiftspear
    can leave the battlefield (e.g. killed in response) before this trigger
    resolves -- the real-rules trigger still resolves and does nothing to a
    source that's gone, matching Goblin Guide's already-established "read
    state at resolution time, no-op if it's not there" idiom."""
    permanent = next(
        (
            p
            for p in state.players[item.controller_id].battlefield
            if p.id == item.source_id
        ),
        None,
    )
    if permanent is None:
        return []
    permanent.power_bonus += 1
    permanent.toughness_bonus += 1
    return [
        {"type": "PUMP", "target": permanent.id, "power_bonus": 1, "toughness_bonus": 1}
    ]


@register("phantasmal_bear", kind="targeted")
def _phantasmal_bear(state: GameState, item: StackItem) -> list[dict]:
    """When Phantasmal Bear becomes the target of a spell or ability,
    sacrifice it (docs/references/master_card_list.tsv). Re-reads
    `item.source_id` off the controller's battlefield at resolution time
    rather than closing over the Permanent found at drain time -- something
    else could remove the Bear (e.g. destroyed in response) before this
    trigger resolves off the stack, matching Swiftspear's already-established
    "read state at resolution time, no-op if it's not there" idiom. No new
    SACRIFICE primitive: this directly performs the same battlefield-removal
    + graveyard-append mutation _apply_destroy makes, since sacrifice here is
    a choice-free consequence of the trigger, not a spell-targeted effect."""
    controller = state.players[item.controller_id]
    for permanent in controller.battlefield:
        if permanent.id == item.source_id:
            controller.battlefield.remove(permanent)
            controller.graveyard.append(permanent.id)
            return [{"type": "SACRIFICE", "target": permanent.id}]
    return []
