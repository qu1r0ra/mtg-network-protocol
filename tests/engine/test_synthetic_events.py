"""Synthetic shell-event tests (RFC §4.2, §4.3, §6.1; ADR 0005): the four
GameEngine methods transport calls that aren't driven by a parsed client PDU --
on_priority_timeout, on_disconnect, on_reconnect, and the visible_state query
they (and ordinary resync/render) depend on."""

from __future__ import annotations

from mtgnp.server.state import GameState, Lifecycle, PlayerState


def _mid_game_state() -> GameState:
    state = GameState()
    state.lifecycle = Lifecycle.IN_GAME
    state.turn = 3
    state.phase = None
    state.connections = {"player_1": "player_1", "player_2": "player_2"}
    state.players = {
        "player_1": PlayerState(player_id="player_1", life=18, hand=["mountain_001"]),
        "player_2": PlayerState(player_id="player_2", life=20, hand=["shock_001", "shock_002"]),
    }
    state.active_player = "player_1"
    return state


def test_on_priority_timeout_ends_game_with_disconnect_reason(make_engine):
    engine = make_engine()
    engine.state = _mid_game_state()
    engine.state.priority_holder = "player_1"

    outbounds = engine.on_priority_timeout("player_1")

    assert len(outbounds) == 1
    assert outbounds[0].recipient == "ALL"
    assert outbounds[0].pdu.type == "GAME_OVER"
    assert outbounds[0].pdu.winner_id == "player_2"
    assert outbounds[0].pdu.reason == "DISCONNECT"
    assert engine.state.lifecycle == Lifecycle.LOBBY


def test_on_disconnect_first_call_marks_player_disconnected_without_ending_game(make_engine):
    engine = make_engine()
    engine.state = _mid_game_state()

    outbounds = engine.on_disconnect("player_1")

    assert outbounds == []
    assert engine.state.players["player_1"].connected is False
    assert engine.state.lifecycle == Lifecycle.IN_GAME


def test_on_disconnect_second_call_on_same_player_ends_game(make_engine):
    engine = make_engine()
    engine.state = _mid_game_state()

    engine.on_disconnect("player_1")
    outbounds = engine.on_disconnect("player_1")

    assert len(outbounds) == 1
    assert outbounds[0].pdu.type == "GAME_OVER"
    assert outbounds[0].pdu.winner_id == "player_2"
    assert outbounds[0].pdu.reason == "DISCONNECT"
    assert engine.state.lifecycle == Lifecycle.LOBBY


def test_on_reconnect_clears_disconnected_flag_and_resyncs_reconnecting_slot(make_engine):
    engine = make_engine()
    engine.state = _mid_game_state()
    engine.on_disconnect("player_1")

    outbounds = engine.on_reconnect("player_1")

    assert engine.state.players["player_1"].connected is True
    assert len(outbounds) == 1
    assert outbounds[0].recipient == "player_1"
    assert outbounds[0].pdu.type == "GAME_STATE_UPDATE"
    assert outbounds[0].pdu.state["hand"] == ["mountain_001"]
    assert outbounds[0].pdu.state["hand_counts"] == {"player_2": 2}


def test_visible_state_in_game_matches_broadcast_view(make_engine):
    engine = make_engine()
    engine.state = _mid_game_state()

    view = engine.visible_state("player_2")

    assert view["hand"] == ["shock_001", "shock_002"]
    assert view["hand_counts"] == {"player_1": 1}
    assert view["life_totals"] == {"player_2": 20, "player_1": 18}


def test_visible_state_during_lobby_returns_lobby_metadata(make_engine):
    engine = make_engine()
    engine.state.connections = {"player_1": "player_1", "player_2": None}

    view = engine.visible_state("player_1")

    assert view == {"phase": "LOBBY", "players_ready": 1, "waiting_for": ["player_2"]}


def test_visible_state_during_mulligan_matches_lifecycle_view(make_engine):
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.MULLIGAN
    engine.state.connections = {"player_1": "player_1", "player_2": "player_2"}
    engine.state.players = {
        "player_1": PlayerState(player_id="player_1", life=20, hand=["mountain_001"]),
        "player_2": PlayerState(player_id="player_2", life=20, hand=["shock_001"]),
    }

    view = engine.visible_state("player_1")

    assert view["phase"] == "MULLIGAN"
    assert view["hand"] == ["mountain_001"]
    assert view["hand_counts"] == {"player_2": 1}
