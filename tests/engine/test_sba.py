"""State-based action tests (RFC §8.4): life<=0 and the toughness/lethal-damage
sweep (the trigger funnel still waits on combat.py/catalog wiring)."""

from mtgnp.server import sba
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
