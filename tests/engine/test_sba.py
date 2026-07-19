"""State-based action tests (RFC §8.4): the life<=0 check reachable this
session (toughness/triggers wait on stack.py/combat.py)."""

from mtgnp.server import sba
from mtgnp.server.state import GameState, Lifecycle, PlayerState


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
