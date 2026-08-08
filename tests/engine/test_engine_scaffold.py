"""Engine dispatch tests (Phase 1, docs/agents/plan-effects-catalog-triggers.md):
feed a raw payload to engine.handle, assert the returned Outbounds + resulting
state. Reuses turn/priority/stack/combat's already-tested behavior through the
one public seam; no networking involved.
"""

from __future__ import annotations

import json

from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import (
    Concede,
    MulliganChoice,
    Ping,
    PlayerReady,
    PriorityPass,
)
from mtgnp.server.state import Lifecycle, Phase


def _payload(pdu) -> bytes:
    return pdu.model_dump_json().encode("utf-8")


def _deck(n: int) -> list[str]:
    return [f"mountain_{i:03d}" for i in range(1, n + 1)]


def test_handle_invalid_json_returns_error(make_engine):
    engine = make_engine()

    outbounds = engine.handle("player_1", b"not json at all")

    assert len(outbounds) == 1
    assert outbounds[0].recipient == "player_1"
    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.INVALID_JSON.value
    assert outbounds[0].pdu.rejected_action is None


def test_handle_unknown_type_returns_error(make_engine):
    engine = make_engine()
    payload = json.dumps({"type": "TOTALLY_BOGUS", "seq_num": 1}).encode("utf-8")

    outbounds = engine.handle("player_1", payload)

    assert len(outbounds) == 1
    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.UNKNOWN_TYPE.value
    assert outbounds[0].pdu.rejected_action == {"type": "TOTALLY_BOGUS", "seq_num": 1}


def test_handle_known_type_with_missing_field_is_invalid_json(make_engine):
    """pdus.py's contract: `type` unrecognized -> UNKNOWN_TYPE, but a known
    `type` failing field-level validation (missing required field) ->
    INVALID_JSON, not UNKNOWN_TYPE."""
    engine = make_engine()
    payload = json.dumps({"type": "CAST_SPELL", "seq_num": 1}).encode(
        "utf-8"
    )  # missing card_id/targets/mana_payment

    outbounds = engine.handle("player_1", payload)

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.INVALID_JSON.value


def test_handle_player_ready_valid_first_player_gets_lobby_ack(make_engine):
    engine = make_engine()
    pdu = PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8))

    outbounds = engine.handle("player_1", _payload(pdu))

    assert len(outbounds) == 1
    assert outbounds[0].recipient == "player_1"
    assert outbounds[0].pdu.type == "GAME_STATE_UPDATE"
    assert outbounds[0].pdu.state == {
        "phase": "LOBBY",
        "players_ready": 1,
        "waiting_for": ["player_2"],
    }
    assert engine.state.players["player_1"].library == _deck(8)


def test_handle_player_ready_illegal_deck_rejected(make_engine):
    engine = make_engine()
    pdu = PlayerReady(seq_num=1, player_id="player_1", deck_list=[])

    outbounds = engine.handle("player_1", _payload(pdu))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_DECK.value
    assert "player_1" not in engine.state.players


def test_both_players_ready_auto_runs_game_setup(make_engine):
    engine = make_engine(seed=42)
    engine.handle(
        "player_1",
        _payload(PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8))),
    )

    outbounds = engine.handle(
        "player_2",
        _payload(PlayerReady(seq_num=1, player_id="player_2", deck_list=_deck(8))),
    )

    # GAME_SETUP's own transition GSU, then run_game_setup's two personalized
    # MULLIGAN-phase GSUs, wired together by the engine automatically.
    assert len(outbounds) == 3
    assert outbounds[0].recipient == "ALL"
    assert outbounds[0].pdu.state["phase"] == "GAME_SETUP"
    assert {o.recipient for o in outbounds[1:]} == {"player_1", "player_2"}
    assert all(o.pdu.state["phase"] == "MULLIGAN" for o in outbounds[1:])
    assert engine.state.lifecycle == Lifecycle.MULLIGAN
    assert engine.state.players["player_1"].life == 20


def test_both_players_keep_mulligan_auto_begins_first_turn(make_engine):
    engine = make_engine(seed=1)
    engine.handle(
        "player_1",
        _payload(PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8))),
    )
    engine.handle(
        "player_2",
        _payload(PlayerReady(seq_num=1, player_id="player_2", deck_list=_deck(8))),
    )

    token_p1 = engine.state.request_tokens["player_1"]
    token_p2 = engine.state.request_tokens["player_2"]
    engine.handle(
        "player_1", _payload(MulliganChoice(seq_num=token_p1, keep=True, cards_to_bottom=[]))
    )
    outbounds = engine.handle(
        "player_2", _payload(MulliganChoice(seq_num=token_p2, keep=True, cards_to_bottom=[]))
    )

    assert engine.state.lifecycle == Lifecycle.IN_GAME
    assert engine.state.turn == 1
    assert engine.state.phase == Phase.UPKEEP
    assert any(o.pdu.type == "PRIORITY_GRANT" for o in outbounds)


def test_priority_pass_stale_action_rejects_and_regrants(make_engine):
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.connections = {"player_1": "player_1", "player_2": "player_2"}
    from mtgnp.server.state import PlayerState

    engine.state.players = {
        "player_1": PlayerState(player_id="player_1", life=20),
        "player_2": PlayerState(player_id="player_2", life=20),
    }
    engine.state.active_player = "player_1"
    engine.state.priority_holder = "player_1"
    engine.state.priority_token = 99

    outbounds = engine.handle("player_1", _payload(PriorityPass(seq_num=1)))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.STALE_ACTION.value
    assert outbounds[1].pdu.type == "PRIORITY_GRANT"
    assert outbounds[1].pdu.seq_num == 99


def test_concede_is_exempt_from_priority_and_ends_game(make_engine):
    from mtgnp.server.state import PlayerState

    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.connections = {"player_1": "player_1", "player_2": "player_2"}
    engine.state.players = {
        "player_1": PlayerState(player_id="player_1", life=20),
        "player_2": PlayerState(player_id="player_2", life=20),
    }
    engine.state.active_player = "player_1"
    engine.state.priority_holder = "player_2"  # player_1 does NOT hold priority

    outbounds = engine.handle(
        "player_1", _payload(Concede(seq_num=1, player_id="player_1"))
    )

    assert len(outbounds) == 1
    assert outbounds[0].recipient == "ALL"
    assert outbounds[0].pdu.type == "GAME_OVER"
    assert outbounds[0].pdu.winner_id == "player_2"
    assert outbounds[0].pdu.reason == "CONCEDE"
    assert engine.state.lifecycle == Lifecycle.LOBBY


def test_ping_gets_pong_echoing_timestamp(make_engine):
    engine = make_engine()

    outbounds = engine.handle("player_1", _payload(Ping(seq_num=1, timestamp=12345)))

    assert len(outbounds) == 1
    assert outbounds[0].recipient == "player_1"
    assert outbounds[0].pdu.type == "PONG"
    assert outbounds[0].pdu.timestamp == 12345
