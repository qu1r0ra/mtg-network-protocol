"""TRIGGER_CHOICE_RESPONSE handler tests (ADR 0007): resumes a targeted ETB
trigger held in pending_trigger_choice -- pushes to the stack on a legal
accept, rejects a declined mandatory trigger or a stale/unknown trigger_id."""

from __future__ import annotations

from mtgnp.protocol.pdus import TriggerChoiceResponse
from mtgnp.server import triggers
from mtgnp.server.state import GameState, Lifecycle, PendingTriggerChoice, PlayerState


def test_engine_dispatch_routes_trigger_choice_response(make_engine):
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.seq_num = 5
    engine.state.pending_trigger_choice = PendingTriggerChoice(
        trigger_id="gravedigger_001_trigger_5",
        source_id="gravedigger_001",
        controller_id="alice",
        legal_targets=["bear_001"],
    )
    pdu = TriggerChoiceResponse(seq_num=6, trigger_id="gravedigger_001_trigger_5", accept=True, chosen_target="bear_001")

    outbounds = engine.handle("player_1", pdu.model_dump_json().encode("utf-8"))

    assert engine.state.pending_trigger_choice is None
    assert len(engine.state.stack) == 1
    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def _state_with_pending_choice() -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=1, phase=None)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    state.seq_num = 5
    state.pending_trigger_choice = PendingTriggerChoice(
        trigger_id="gravedigger_001_trigger_5",
        source_id="gravedigger_001",
        controller_id="alice",
        legal_targets=["bear_001"],
    )
    return state


def test_accepted_response_pushes_stack_item_and_clears_pending_choice():
    state = _state_with_pending_choice()
    pdu = TriggerChoiceResponse(seq_num=6, trigger_id="gravedigger_001_trigger_5", accept=True, chosen_target="bear_001")

    outbounds = triggers.handle_trigger_choice_response(state, "player_1", pdu)

    assert state.pending_trigger_choice is None
    assert len(state.stack) == 1
    pushed = state.stack[0]
    assert pushed.item_type == "TRIGGER_ABILITY"
    assert pushed.source_id == "gravedigger_001"
    assert pushed.controller_id == "alice"
    assert pushed.targets == ["bear_001"]
    push_pdu = next(o for o in outbounds if o.pdu.type == "STACK_PUSH")
    assert push_pdu.pdu.stack_item_id == "gravedigger_001_trigger_5"


def test_declined_mandatory_trigger_is_rejected_and_pending_choice_kept():
    state = _state_with_pending_choice()
    pdu = TriggerChoiceResponse(seq_num=6, trigger_id="gravedigger_001_trigger_5", accept=False)

    outbounds = triggers.handle_trigger_choice_response(state, "player_1", pdu)

    assert state.pending_trigger_choice is not None  # left for retry
    assert state.stack == []
    error = next(o for o in outbounds if o.pdu.type == "ERROR")
    assert error.pdu.code == "TRIGGER_CHOICE_INVALID"


def test_unknown_trigger_id_is_rejected():
    state = _state_with_pending_choice()
    pdu = TriggerChoiceResponse(seq_num=6, trigger_id="not_the_pending_trigger", accept=True, chosen_target="bear_001")

    outbounds = triggers.handle_trigger_choice_response(state, "player_1", pdu)

    assert state.pending_trigger_choice is not None
    assert state.stack == []
    error = next(o for o in outbounds if o.pdu.type == "ERROR")
    assert error.pdu.code == "TRIGGER_CHOICE_INVALID"


def test_illegal_chosen_target_is_rejected():
    state = _state_with_pending_choice()
    pdu = TriggerChoiceResponse(seq_num=6, trigger_id="gravedigger_001_trigger_5", accept=True, chosen_target="not_a_legal_target")

    outbounds = triggers.handle_trigger_choice_response(state, "player_1", pdu)

    assert state.pending_trigger_choice is not None
    assert state.stack == []
    error = next(o for o in outbounds if o.pdu.type == "ERROR")
    assert error.pdu.code == "TRIGGER_CHOICE_INVALID"
