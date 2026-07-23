"""State-based action tests (RFC §8.4): life<=0 and the toughness/lethal-damage
sweep (the trigger funnel still waits on combat.py/catalog wiring)."""

from mtgnp.server import custom_effects, sba
from mtgnp.server.state import GameState, Lifecycle, Permanent, PlayerState


def _two_player_state() -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=3, phase=None)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    return state


def test_no_sba_when_both_players_alive():
    state = _two_player_state()

    assert sba.resolve(state) == []
    assert state.lifecycle == Lifecycle.IN_GAME


def test_life_zero_ends_the_game():
    state = _two_player_state()
    state.players["bob"].life = 0

    outbounds = sba.resolve(state)

    game_over = next(o for o in outbounds if o.pdu.type == "GAME_OVER")
    assert game_over.pdu.winner_id == "alice"
    assert game_over.pdu.loser_id == "bob"
    assert game_over.pdu.reason == "LIFE_ZERO"
    assert state.lifecycle == Lifecycle.LOBBY  # enter_game_over resets to LOBBY


def test_simultaneous_life_zero_active_player_loses():
    state = _two_player_state()
    state.players["alice"].life = -1  # AP
    state.players["bob"].life = 0

    outbounds = sba.resolve(state)

    game_over = next(o for o in outbounds if o.pdu.type == "GAME_OVER")
    assert game_over.pdu.winner_id == "bob"  # NAP wins
    assert game_over.pdu.loser_id == "alice"


def test_creature_with_lethal_damage_moves_to_graveyard():
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="bear_1", power=2, toughness=2, damage=2)
    ]

    sba.resolve(state)

    assert state.players["alice"].battlefield == []
    assert state.players["alice"].graveyard == ["bear_1"]


def test_creature_with_zero_toughness_moves_to_graveyard():
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="shrunk_1", power=1, toughness=0, damage=0)
    ]

    sba.resolve(state)

    assert state.players["alice"].battlefield == []
    assert state.players["alice"].graveyard == ["shrunk_1"]


def test_creature_with_sublethal_damage_survives():
    state = _two_player_state()
    surviving = Permanent(id="bear_1", power=2, toughness=2, damage=1)
    state.players["alice"].battlefield = [surviving]

    sba.resolve(state)

    assert state.players["alice"].battlefield == [surviving]
    assert state.players["alice"].graveyard == []


def test_noncreature_permanent_is_never_swept():
    state = _two_player_state()
    land = Permanent(id="mountain_1")
    state.players["alice"].battlefield = [land]

    sba.resolve(state)

    assert state.players["alice"].battlefield == [land]


def test_registered_pending_etb_is_placed_on_the_stack():
    @custom_effects.register("__test_sba_trigger__", kind="etb")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_sba_trigger___001", "alice", False)]

    outbounds = sba.resolve(state)

    push = next(o for o in outbounds if o.pdu.type == "STACK_PUSH")
    assert push.pdu.item_type == "TRIGGER_ABILITY"
    assert push.pdu.source == "__test_sba_trigger___001"
    assert push.pdu.controller == "alice"
    assert state.stack[-1].item_type == "TRIGGER_ABILITY"
    assert state.pending_etb == []


def test_unregistered_pending_etb_is_drained_without_a_stack_push():
    state = _two_player_state()
    state.pending_etb = [("some_vanilla_creature_001", "alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_etb == []


def test_targeted_trigger_with_legal_targets_holds_for_trigger_choice():
    @custom_effects.register(
        "__test_targeted_trigger__",
        kind="etb",
        requires_target=True,
        legal_targets_fn=lambda state, controller_id: ["some_creature_1"],
    )
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_targeted_trigger___001", "alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    choice = next(o for o in outbounds if o.pdu.type == "TRIGGER_CHOICE")
    assert choice.pdu.source_id == "__test_targeted_trigger___001"
    assert choice.pdu.requires_target is True
    assert choice.pdu.legal_targets == ["some_creature_1"]
    assert state.stack == []
    assert state.pending_etb == []
    assert state.pending_trigger_choice is not None
    assert state.pending_trigger_choice.trigger_id == choice.pdu.trigger_id
    assert state.pending_trigger_choice.source_id == "__test_targeted_trigger___001"
    assert state.pending_trigger_choice.controller_id == "alice"
    assert state.pending_trigger_choice.legal_targets == ["some_creature_1"]


def test_targeted_trigger_with_no_legal_targets_is_discarded_silently():
    @custom_effects.register(
        "__test_targeted_trigger_no_targets__",
        kind="etb",
        requires_target=True,
        legal_targets_fn=lambda state, controller_id: [],
    )
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_targeted_trigger_no_targets___001", "alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert not any(o.pdu.type == "TRIGGER_CHOICE" for o in outbounds)
    assert state.stack == []
    assert state.pending_etb == []
    assert state.pending_trigger_choice is None


def test_kicker_gated_trigger_is_discarded_silently_when_not_kicked():
    @custom_effects.register(
        "__test_kicker_gated_trigger__", kind="etb", kicker_gated=True
    )
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_kicker_gated_trigger___001", "alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.stack == []
    assert state.pending_etb == []


def test_kicker_gated_trigger_is_placed_on_the_stack_when_kicked():
    @custom_effects.register(
        "__test_kicker_gated_trigger_kicked__", kind="etb", kicker_gated=True
    )
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_kicker_gated_trigger_kicked___001", "alice", True)]

    outbounds = sba.resolve(state)

    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert len(state.stack) == 1
    assert state.stack[0].item_type == "TRIGGER_ABILITY"


def test_registered_pending_attack_trigger_is_placed_on_the_stack():
    """ADR 0009 twin of test_registered_pending_etb_is_placed_on_the_stack."""

    @custom_effects.register("__test_sba_attack_trigger__", kind="attack")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_attack_trigger = [("__test_sba_attack_trigger___001", "alice")]

    outbounds = sba.resolve(state)

    push = next(o for o in outbounds if o.pdu.type == "STACK_PUSH")
    assert push.pdu.item_type == "TRIGGER_ABILITY"
    assert push.pdu.source == "__test_sba_attack_trigger___001"
    assert push.pdu.controller == "alice"
    assert state.stack[-1].item_type == "TRIGGER_ABILITY"
    assert state.pending_attack_trigger == []


def test_unregistered_pending_attack_trigger_is_drained_without_a_stack_push():
    state = _two_player_state()
    state.pending_attack_trigger = [("some_vanilla_attacker_001", "alice")]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_attack_trigger == []


def test_registered_pending_targeted_trigger_is_placed_on_the_stack():
    """ADR 0011 twin of test_registered_pending_attack_trigger_is_placed_on_the_stack."""

    @custom_effects.register("__test_sba_targeted_trigger__", kind="targeted")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_targeted_trigger = [("__test_sba_targeted_trigger___001", "alice")]

    outbounds = sba.resolve(state)

    push = next(o for o in outbounds if o.pdu.type == "STACK_PUSH")
    assert push.pdu.item_type == "TRIGGER_ABILITY"
    assert push.pdu.source == "__test_sba_targeted_trigger___001"
    assert push.pdu.controller == "alice"
    assert state.stack[-1].item_type == "TRIGGER_ABILITY"
    assert state.pending_targeted_trigger == []


def test_unregistered_pending_targeted_trigger_is_drained_without_a_stack_push():
    state = _two_player_state()
    state.pending_targeted_trigger = [("some_vanilla_creature_001", "alice")]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_targeted_trigger == []


def test_attack_registered_permanent_does_not_drain_as_a_targeted_trigger():
    """Kind-guard (ADR 0010/0011): a permanent registered for a different
    trigger source must not misfire when it happens to be targeted."""

    @custom_effects.register("__test_targeted_wrong_kind_attack__", kind="attack")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_targeted_trigger = [
        ("__test_targeted_wrong_kind_attack___001", "alice")
    ]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_targeted_trigger == []


def test_targeted_registered_permanent_does_not_drain_as_an_etb_trigger():
    """Phantasmal Bear is a creature -- it lands in pending_etb on every
    cast, same as any other creature spell resolving. Without the kind guard,
    _drain_pending_etb would find its kind="targeted" spec and fire the
    sacrifice resolver on entry, destroying the Bear the instant it enters
    play. ADR 0011 twin of ADR 0010's
    test_cast_registered_permanent_does_not_drain_as_an_etb_trigger."""
    state = _two_player_state()
    state.pending_etb = [("phantasmal_bear_001", "alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_etb == []


def test_pending_targeted_trigger_is_left_undrained_when_the_game_ends_this_sweep():
    """ADR 0011 twin of the pending_attack_trigger game-ending guard above."""
    state = _two_player_state()
    state.players["bob"].life = 0
    state.pending_targeted_trigger = [("__test_sba_targeted_trigger___001", "alice")]

    outbounds = sba.resolve(state)

    assert any(o.pdu.type == "GAME_OVER" for o in outbounds)
    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_targeted_trigger == [
        ("__test_sba_targeted_trigger___001", "alice")
    ]


def test_pending_etb_is_left_undrained_when_the_game_ends_this_sweep():
    """Confirmed decision (2026-07-23 grilling, plan handoff bullet 1):
    triggers are only ever placed while the game is still live. A
    game-ending SBA sweep takes the early-return path entirely -- it must
    not also push a trigger onto a stack nobody will ever resolve."""
    state = _two_player_state()
    state.players["bob"].life = 0
    state.pending_etb = [("__test_sba_trigger___001", "alice", False)]

    outbounds = sba.resolve(state)

    assert any(o.pdu.type == "GAME_OVER" for o in outbounds)
    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_etb == [("__test_sba_trigger___001", "alice", False)]


def test_pending_attack_trigger_is_left_undrained_when_the_game_ends_this_sweep():
    """ADR 0009 twin of the pending_etb game-ending guard above."""
    state = _two_player_state()
    state.players["bob"].life = 0
    state.pending_attack_trigger = [("__test_sba_attack_trigger___001", "alice")]

    outbounds = sba.resolve(state)

    assert any(o.pdu.type == "GAME_OVER" for o in outbounds)
    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_attack_trigger == [
        ("__test_sba_attack_trigger___001", "alice")
    ]


def test_registered_pending_cast_trigger_scans_casters_battlefield_and_pushes():
    """ADR 0010: unlike the ETB/attack twins, the queued entity (the caster)
    is not the trigger source -- the drain must scan the caster's own
    battlefield for a registered permanent (e.g. Monastery Swiftspear)."""

    @custom_effects.register("__test_sba_cast_trigger__", kind="cast")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="__test_sba_cast_trigger___001", power=1, toughness=2)
    ]
    state.pending_cast_trigger = [("alice", True)]

    outbounds = sba.resolve(state)

    push = next(o for o in outbounds if o.pdu.type == "STACK_PUSH")
    assert push.pdu.item_type == "TRIGGER_ABILITY"
    assert push.pdu.source == "__test_sba_cast_trigger___001"
    assert push.pdu.controller == "alice"
    assert state.stack[-1].item_type == "TRIGGER_ABILITY"
    assert state.pending_cast_trigger == []


def test_creature_spell_cast_does_not_drain_a_cast_trigger():
    """is_noncreature=False (a creature spell was cast) is dropped without
    scanning the caster's battlefield at all."""

    @custom_effects.register("__test_sba_cast_trigger_creature_cast__", kind="cast")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(
            id="__test_sba_cast_trigger_creature_cast___001", power=1, toughness=2
        )
    ]
    state.pending_cast_trigger = [("alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_cast_trigger == []


def test_unregistered_battlefield_permanent_does_not_drain_a_cast_trigger():
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="some_vanilla_creature_001", power=1, toughness=1)
    ]
    state.pending_cast_trigger = [("alice", True)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_cast_trigger == []


def test_cast_registered_permanent_does_not_drain_as_an_etb_trigger():
    """ADR 0010's `kind` guard is load-bearing, not just hygiene: casting
    Goblin Guide (kind="attack") makes it ETB into pending_etb same as any
    creature. Pre-guard, the ETB drain would have fired its attack resolver
    -- which reads `state.attackers[item.source_id]` and KeyErrors, since
    Goblin Guide was never declared as an attacker here."""
    state = _two_player_state()
    state.pending_etb = [("goblin_guide_001", "alice", False)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_etb == []


def test_attack_registered_permanent_does_not_drain_as_a_cast_trigger():
    """ADR 0010's headline fix: a permanent registered under a different
    `kind` (e.g. Goblin Guide's kind="attack") must not misfire when the
    cast-trigger drain scans past it on the caster's battlefield."""
    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="goblin_guide_001", power=2, toughness=2)
    ]
    state.pending_cast_trigger = [("alice", True)]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_cast_trigger == []


def test_cast_trigger_only_scans_the_casters_own_battlefield_not_opponents():
    """Prowess text is 'whenever *you* cast a noncreature spell' -- a
    registered permanent on the non-caster's battlefield must not fire."""

    @custom_effects.register("__test_sba_cast_trigger_not_yours__", kind="cast")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.players["alice"].battlefield = [
        Permanent(id="__test_sba_cast_trigger_not_yours___001", power=1, toughness=2)
    ]
    state.pending_cast_trigger = [("bob", True)]  # bob cast it, not alice

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_cast_trigger == []


def test_pending_cast_trigger_is_left_undrained_when_the_game_ends_this_sweep():
    """ADR 0010 twin of the pending_etb/pending_attack_trigger game-ending guards."""
    state = _two_player_state()
    state.players["bob"].life = 0
    state.pending_cast_trigger = [("alice", True)]

    outbounds = sba.resolve(state)

    assert any(o.pdu.type == "GAME_OVER" for o in outbounds)
    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_cast_trigger == [("alice", True)]
