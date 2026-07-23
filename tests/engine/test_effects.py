"""effects.apply() primitive dispatch tests (Phase 2, ADR 0004)."""

from __future__ import annotations

from mtgnp.server import effects
from mtgnp.server.state import GameState, Lifecycle, Permanent, PlayerState, StackItem


def _two_player_state() -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=1, phase=None)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    return state


def test_damage_primitive_reduces_target_player_life():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="lightning_bolt_001",
        controller_id="alice", targets=["bob"],
    )

    changes = effects.apply(state, item)

    assert state.players["bob"].life == 17
    assert changes == [{"type": "DAMAGE", "target": "bob", "amount": 3}]


def test_damage_primitive_marks_damage_on_targeted_creature():
    from mtgnp.server.state import Permanent

    state = _two_player_state()
    state.players["bob"].battlefield.append(Permanent(id="some_creature_001", power=2, toughness=2, damage=0))
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="lightning_bolt_001",
        controller_id="alice", targets=["some_creature_001"],
    )

    effects.apply(state, item)

    assert state.players["bob"].battlefield[0].damage == 3


def test_creature_spell_with_no_primitive_effect_enters_battlefield():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="gravedigger_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    battlefield = state.players["alice"].battlefield
    assert len(battlefield) == 1
    assert battlefield[0].id == "gravedigger_001"
    assert battlefield[0].power == 2
    assert battlefield[0].toughness == 2
    assert battlefield[0].summoning_sick is True
    assert changes == [{"type": "ETB", "permanent_id": "gravedigger_001"}]


def test_creature_spell_records_pending_etb():
    """The ETB event Phase 3's trigger funnel drains -- captured as
    (permanent_id, controller_id) at append time (CONTEXT.md: ETB)."""
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="gray_merchant_001",
        controller_id="alice", targets=[],
    )

    effects.apply(state, item)

    assert state.pending_etb == [("gray_merchant_001", "alice")]


def test_trigger_ability_resolution_does_not_re_enter_battlefield():
    """A resolving TRIGGER_ABILITY (Gray Merchant's own ETB trigger) must not
    re-run the creature-ETB path just because its source_id maps to a
    Creature card -- that would double the permanent on the battlefield.
    Gray Merchant is already on the battlefield by the time its trigger
    resolves (its SPELL resolution placed it, per Phase 3's
    place-then-resolve funnel), so devotion counts it too: BB in its own
    mana cost -> devotion 2."""
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="gray_merchant_001", power=2, toughness=4, damage=0, summoning_sick=True)
    ]
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="gray_merchant_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert len(state.players["alice"].battlefield) == 1  # not duplicated
    assert state.players["bob"].life == 18  # 20 - devotion(2)
    assert state.players["alice"].life == 22  # 20 + devotion(2)
    assert changes == [
        {"type": "DRAIN", "source": "alice", "target": "bob", "amount": 2},
        {"type": "GAIN_LIFE", "target": "alice", "amount": 2},
    ]


def test_gray_merchant_devotion_counts_other_black_permanents_too():
    """Devotion sums black mana symbols across the controller's whole
    battlefield, not just the triggering permanent itself."""
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="gray_merchant_001", power=2, toughness=4, damage=0),
        Permanent(id="gravedigger_001", power=2, toughness=2, damage=0),  # B in its cost
    ]
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="gray_merchant_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert state.players["bob"].life == 17  # 20 - devotion(3): BB + B
    assert state.players["alice"].life == 23
    assert changes == [
        {"type": "DRAIN", "source": "alice", "target": "bob", "amount": 3},
        {"type": "GAIN_LIFE", "target": "alice", "amount": 3},
    ]


def test_unknown_card_resolves_as_no_op():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="not_a_real_card_001",
        controller_id="alice", targets=[],
    )

    assert effects.apply(state, item) == []
