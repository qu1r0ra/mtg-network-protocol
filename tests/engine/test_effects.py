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


def test_creature_with_static_haste_keyword_enters_with_haste_set():
    """ADR 0009: a card printed with Haste (e.g. Goblin Guide) gets
    Permanent.haste=True at ETB, distinct from temp_haste (a temporary
    grant, never set here)."""
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="goblin_guide_001",
        controller_id="alice", targets=[],
    )

    effects.apply(state, item)

    permanent = state.players["alice"].battlefield[0]
    assert permanent.haste is True
    assert permanent.temp_haste is False


def test_creature_without_haste_keyword_enters_with_haste_false():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="gravedigger_001",
        controller_id="alice", targets=[],
    )

    effects.apply(state, item)

    assert state.players["alice"].battlefield[0].haste is False


def test_creature_spell_records_pending_etb():
    """The ETB event Phase 3's trigger funnel drains -- captured as
    (permanent_id, controller_id, kicked) at append time (CONTEXT.md: ETB)."""
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="gray_merchant_001",
        controller_id="alice", targets=[],
    )

    effects.apply(state, item)

    assert state.pending_etb == [("gray_merchant_001", "alice", False)]


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


def test_gravedigger_moves_chosen_creature_card_from_graveyard_to_hand():
    """Gravedigger's TRIGGER_ABILITY resolves with chosen_target already
    populated in item.targets (ADR 0007 -- the target was picked via
    TRIGGER_CHOICE before STACK_PUSH, unlike Gray Merchant's untargeted
    trigger)."""
    state = _two_player_state()
    state.players["alice"].graveyard = ["bear_001", "gravedigger_001"]
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="gravedigger_001",
        controller_id="alice", targets=["bear_001"],
    )

    changes = effects.apply(state, item)

    assert state.players["alice"].graveyard == ["gravedigger_001"]
    assert state.players["alice"].hand == ["bear_001"]
    assert changes == [{"type": "RETURN_TO_HAND", "target": "bear_001", "controller": "alice"}]


def test_goblin_bushwhacker_pumps_and_hastes_controllers_creatures():
    """Kicker's "intervening if" is enforced at drain time (kicker_gated,
    sba.py); once this TRIGGER_ABILITY resolves, it always applies the
    buff -- resolving unkicked never happens in practice."""
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="goblin_bushwhacker_001", power=1, toughness=1, damage=0),
        Permanent(id="bear_001", power=2, toughness=2, damage=0),
    ]
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="goblin_bushwhacker_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    for permanent in state.players["alice"].battlefield:
        assert permanent.power_bonus == 1
        assert permanent.temp_haste is True
    assert changes == [
        {"type": "PUMP", "target": "goblin_bushwhacker_001", "power_bonus": 1, "haste": True},
        {"type": "PUMP", "target": "bear_001", "power_bonus": 1, "haste": True},
    ]


def test_goblin_bushwhacker_does_not_pump_noncreature_permanents():
    """"Creatures you control" -- a land on the battlefield must not be
    pumped or granted haste (power is None distinguishes it, same convention
    _permanent_view/combat.py already use for "is this a creature")."""
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="mountain_001", power=None, toughness=None),
        Permanent(id="goblin_bushwhacker_001", power=1, toughness=1, damage=0),
    ]
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="goblin_bushwhacker_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    mountain, bushwhacker = state.players["alice"].battlefield
    assert mountain.power_bonus == 0
    assert mountain.temp_haste is False
    assert bushwhacker.power_bonus == 1
    assert changes == [{"type": "PUMP", "target": "goblin_bushwhacker_001", "power_bonus": 1, "haste": True}]


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


def test_gain_life_primitive_raises_target_player_life():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="healing_salve_001",
        controller_id="alice", targets=["alice"],
    )

    changes = effects._apply_gain_life(state, item, 3)

    assert state.players["alice"].life == 23
    assert changes == [{"type": "GAIN_LIFE", "target": "alice", "amount": 3}]


def test_draw_primitive_moves_cards_from_library_to_hand():
    state = _two_player_state()
    state.players["alice"].library = ["ponder_001", "shock_002", "bear_003"]
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="ponder_001",
        controller_id="alice", targets=[],
    )

    changes = effects._apply_draw(state, item, 1)

    assert state.players["alice"].hand == ["ponder_001"]
    assert state.players["alice"].library == ["shock_002", "bear_003"]
    assert changes == [{"type": "DRAW", "target": "alice", "amount": 1}]


def test_draw_primitive_stops_early_on_empty_library():
    state = _two_player_state()
    state.players["alice"].library = ["only_card_001"]
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="ponder_001",
        controller_id="alice", targets=[],
    )

    changes = effects._apply_draw(state, item, 3)

    assert state.players["alice"].hand == ["only_card_001"]
    assert state.players["alice"].library == []
    assert changes == [{"type": "DRAW", "target": "alice", "amount": 1}]


def test_destroy_primitive_moves_permanent_to_owner_graveyard():
    state = _two_player_state()
    state.players["bob"].battlefield.append(Permanent(id="bear_001", power=2, toughness=2, damage=0))
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="doom_blade_001",
        controller_id="alice", targets=["bear_001"],
    )

    changes = effects._apply_destroy(state, item)

    assert state.players["bob"].battlefield == []
    assert state.players["bob"].graveyard == ["bear_001"]
    assert changes == [{"type": "DESTROY", "target": "bear_001"}]


def test_counter_primitive_removes_target_spell_from_stack_to_its_graveyard():
    state = _two_player_state()
    state.stack = [
        StackItem(
            stack_item_id="stk_01", item_type="SPELL", source_id="bear_001",
            controller_id="bob", targets=[],
        )
    ]
    item = StackItem(
        stack_item_id="stk_02", item_type="SPELL", source_id="counterspell_001",
        controller_id="alice", targets=["stk_01"],
    )

    changes = effects._apply_counter(state, item)

    assert state.stack == []
    assert state.players["bob"].graveyard == ["bear_001"]
    assert changes == [{"type": "COUNTER", "target": "stk_01"}]


def test_unknown_card_resolves_as_no_op():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="not_a_real_card_001",
        controller_id="alice", targets=[],
    )

    assert effects.apply(state, item) == []


def test_goblin_guide_reveals_land_and_moves_it_to_defenders_hand():
    """ADR 0009: defender is read from state.attackers[item.source_id] at
    resolution time, still populated since END_OF_COMBAT hasn't cleared it."""
    state = _two_player_state()
    state.players["bob"].library = ["mountain_001", "grizzly_bears_002"]
    state.attackers = {"goblin_guide_001": "bob"}
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="goblin_guide_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert state.players["bob"].library == ["grizzly_bears_002"]
    assert state.players["bob"].hand == ["mountain_001"]
    assert changes == [{"type": "REVEAL", "player": "bob", "card": "mountain_001", "moved_to_hand": True}]


def test_goblin_guide_reveals_nonland_and_leaves_it_on_top():
    state = _two_player_state()
    state.players["bob"].library = ["grizzly_bears_001", "mountain_002"]
    state.attackers = {"goblin_guide_001": "bob"}
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="goblin_guide_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert state.players["bob"].library == ["grizzly_bears_001", "mountain_002"]
    assert state.players["bob"].hand == []
    assert changes == [{"type": "REVEAL", "player": "bob", "card": "grizzly_bears_001", "moved_to_hand": False}]


def test_goblin_guide_with_empty_defender_library_is_a_no_op():
    state = _two_player_state()
    state.players["bob"].library = []
    state.attackers = {"goblin_guide_001": "bob"}
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="goblin_guide_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert state.players["bob"].hand == []
    assert changes == []


def test_monastery_swiftspear_prowess_pumps_itself():
    """ADR 0010: Swiftspear's cast-trigger resolver reads `item.source_id`
    (itself, not the cast spell) off the caster's own battlefield."""
    state = _two_player_state()
    permanent = Permanent(id="monastery_swiftspear_001", power=1, toughness=2)
    state.players["alice"].battlefield.append(permanent)
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="monastery_swiftspear_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert permanent.power_bonus == 1
    assert permanent.toughness_bonus == 1
    assert changes == [
        {"type": "PUMP", "target": "monastery_swiftspear_001", "power_bonus": 1, "toughness_bonus": 1}
    ]


def test_monastery_swiftspear_prowess_is_a_no_op_if_it_already_left_the_battlefield():
    """Swiftspear can die (e.g. bolted in response) after its prowess trigger
    is placed but before it resolves -- the real-rules trigger still
    resolves and does nothing, matching Goblin Guide's no-op idiom."""
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="monastery_swiftspear_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert changes == []


def test_phantasmal_bear_sacrifices_itself_when_targeted():
    """ADR 0011: becoming the target of a spell or ability sacrifices the
    Bear -- battlefield removal + graveyard append, same mutation shape as
    _apply_destroy, but reached via the targeted-trigger registry rather than
    a DESTROY primitive."""
    state = _two_player_state()
    permanent = Permanent(id="phantasmal_bear_001", power=2, toughness=2)
    state.players["alice"].battlefield.append(permanent)
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="phantasmal_bear_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert state.players["alice"].battlefield == []
    assert state.players["alice"].graveyard == ["phantasmal_bear_001"]
    assert changes == [{"type": "SACRIFICE", "target": "phantasmal_bear_001"}]


def test_phantasmal_bear_sacrifice_is_a_no_op_if_it_already_left_the_battlefield():
    """The Bear can die to an unrelated effect between drain and this
    trigger's own resolution -- matching Swiftspear's no-op idiom."""
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="TRIGGER_ABILITY", source_id="phantasmal_bear_001",
        controller_id="alice", targets=[],
    )

    changes = effects.apply(state, item)

    assert changes == []


def test_vines_of_vastwood_protects_target_but_does_not_pump_when_unkicked():
    """ADR 0012: protected_by is set unconditionally; the +4/+4 only applies
    when the spell was kicked."""
    state = _two_player_state()
    bear = Permanent(id="bear_001", power=2, toughness=2)
    state.players["alice"].battlefield.append(bear)
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="vines_of_vastwood_001",
        controller_id="alice", targets=["bear_001"], kicked=False,
    )

    changes = effects.apply(state, item)

    assert bear.protected_by == "alice"
    assert bear.power_bonus == 0
    assert bear.toughness_bonus == 0
    assert changes == [{"type": "PROTECT", "target": "bear_001", "protected_by": "alice"}]


def test_vines_of_vastwood_pumps_target_when_kicked():
    state = _two_player_state()
    bear = Permanent(id="bear_001", power=2, toughness=2)
    state.players["alice"].battlefield.append(bear)
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="vines_of_vastwood_001",
        controller_id="alice", targets=["bear_001"], kicked=True,
    )

    changes = effects.apply(state, item)

    assert bear.protected_by == "alice"
    assert bear.power_bonus == 4
    assert bear.toughness_bonus == 4
    assert changes == [
        {"type": "PROTECT", "target": "bear_001", "protected_by": "alice"},
        {"type": "PUMP", "target": "bear_001", "power_bonus": 4, "toughness_bonus": 4},
    ]


def test_vines_of_vastwood_is_a_no_op_if_target_already_left_the_battlefield():
    state = _two_player_state()
    item = StackItem(
        stack_item_id="stk_01", item_type="SPELL", source_id="vines_of_vastwood_001",
        controller_id="alice", targets=["bear_001"], kicked=True,
    )

    changes = effects.apply(state, item)

    assert changes == []
