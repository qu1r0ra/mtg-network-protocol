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
    @custom_effects.register("__test_sba_trigger__")
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_sba_trigger___001", "alice")]

    outbounds = sba.resolve(state)

    push = next(o for o in outbounds if o.pdu.type == "STACK_PUSH")
    assert push.pdu.item_type == "TRIGGER_ABILITY"
    assert push.pdu.source == "__test_sba_trigger___001"
    assert push.pdu.controller == "alice"
    assert state.stack[-1].item_type == "TRIGGER_ABILITY"
    assert state.pending_etb == []


def test_unregistered_pending_etb_is_drained_without_a_stack_push():
    state = _two_player_state()
    state.pending_etb = [("some_vanilla_creature_001", "alice")]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_etb == []


def test_targeted_trigger_with_legal_targets_holds_for_trigger_choice():
    @custom_effects.register(
        "__test_targeted_trigger__",
        requires_target=True,
        legal_targets_fn=lambda state, controller_id: ["some_creature_1"],
    )
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_targeted_trigger___001", "alice")]

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
        requires_target=True,
        legal_targets_fn=lambda state, controller_id: [],
    )
    def _handler(state, item):
        return []

    state = _two_player_state()
    state.pending_etb = [("__test_targeted_trigger_no_targets___001", "alice")]

    outbounds = sba.resolve(state)

    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert not any(o.pdu.type == "TRIGGER_CHOICE" for o in outbounds)
    assert state.stack == []
    assert state.pending_etb == []
    assert state.pending_trigger_choice is None


def test_pending_etb_is_left_undrained_when_the_game_ends_this_sweep():
    """Confirmed decision (2026-07-23 grilling, plan handoff bullet 1):
    triggers are only ever placed while the game is still live. A
    game-ending SBA sweep takes the early-return path entirely -- it must
    not also push a trigger onto a stack nobody will ever resolve."""
    state = _two_player_state()
    state.players["bob"].life = 0
    state.pending_etb = [("__test_sba_trigger___001", "alice")]

    outbounds = sba.resolve(state)

    assert any(o.pdu.type == "GAME_OVER" for o in outbounds)
    assert not any(o.pdu.type == "STACK_PUSH" for o in outbounds)
    assert state.pending_etb == [("__test_sba_trigger___001", "alice")]
