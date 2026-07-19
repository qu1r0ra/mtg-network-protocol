"""Priority window tests (RFC §8.1-8.2, §8.5), tested directly against
priority.py's pure functions."""

from mtgnp.protocol.pdus import PlayerReady, PriorityPass
from mtgnp.server import priority
from mtgnp.server.state import GameState, Lifecycle, PlayerState


def _two_player_state() -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=1, phase=None)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    return state


def test_grant_stamps_fresh_seq_num_as_the_priority_token():
    state = _two_player_state()
    state.seq_num = 10

    outbounds = priority.grant(state, "alice")

    assert state.priority_holder == "alice"
    assert state.priority_token == 11
    assert outbounds[0].recipient == "player_1"
    assert outbounds[0].pdu.seq_num == 11
    assert outbounds[0].pdu.player_id == "alice"


def test_pass_hands_priority_to_the_other_player():
    state = _two_player_state()
    priority.grant(state, "alice")
    token = state.priority_token

    outbounds = priority.handle_pass(state, "player_1", PriorityPass(seq_num=token))

    assert state.priority_holder == "bob"
    assert outbounds[-1].recipient == "player_2"
    assert outbounds[-1].pdu.type == "PRIORITY_GRANT"


def test_stale_action_rejected_and_grant_reissued_with_same_seq_num():
    state = _two_player_state()
    priority.grant(state, "alice")
    stale_token = state.priority_token - 1  # deliberately wrong

    outbounds = priority.handle_pass(state, "player_1", PriorityPass(seq_num=stale_token))

    assert len(outbounds) == 2
    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == "STALE_ACTION"
    assert outbounds[1].pdu.type == "PRIORITY_GRANT"
    assert outbounds[1].pdu.seq_num == state.priority_token  # re-issued, same token
    assert state.priority_holder == "alice"  # unchanged


def test_action_from_non_holder_rejected_not_your_priority():
    state = _two_player_state()
    priority.grant(state, "alice")
    token = state.priority_token

    outbounds = priority.handle_pass(state, "player_2", PriorityPass(seq_num=token))

    assert len(outbounds) == 1
    assert outbounds[0].pdu.code == "NOT_YOUR_PRIORITY"
    assert state.priority_holder == "alice"  # unchanged


def test_player_ready_exempt_from_priority_token_check():
    state = _two_player_state()
    priority.grant(state, "alice")

    errors = priority.validate_priority(
        state, "player_2", PlayerReady(seq_num=999, player_id="bob", deck_list=["x"])
    )

    assert errors == []
