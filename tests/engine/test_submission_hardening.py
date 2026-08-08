"""Regression tests for submission-critical RFC validation gaps."""

from __future__ import annotations

from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import CastSpell, Discard, PlayLand, PlayerReady
from mtgnp.server import cast, lifecycle, stack, turn
from mtgnp.server.state import (
    GameState,
    Lifecycle,
    Permanent,
    Phase,
    PlayerState,
    StackItem,
)


def _ready(deck: list[str], player_id: str = "alice") -> PlayerReady:
    return PlayerReady(seq_num=1, player_id=player_id, deck_list=deck)


def _game_state(
    *,
    phase: Phase = Phase.PRECOMBAT_MAIN,
    hand: list[str] | None = None,
    battlefield: list[Permanent] | None = None,
) -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=2, phase=phase)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(
            player_id="alice",
            life=20,
            hand=list(hand or []),
            battlefield=list(battlefield or []),
        ),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    state.priority_holder = "alice"
    state.priority_token = 1
    return state


def test_player_ready_rejects_blank_player_id():
    state = GameState()
    out = lifecycle.handle_player_ready(state, "player_1", _ready(["mountain_001"], "   "))
    assert out[0].pdu.code == ErrorCode.ILLEGAL_ACTION.value
    assert state.players == {}


def test_player_ready_rejects_unknown_instance_id():
    state = GameState()
    out = lifecycle.handle_player_ready(state, "player_1", _ready(["mountain_999"]))
    assert out[0].pdu.code == ErrorCode.ILLEGAL_DECK.value
    assert state.players == {}


def test_player_ready_rejects_repeated_instance_id():
    state = GameState()
    out = lifecycle.handle_player_ready(
        state, "player_1", _ready(["mountain_001", "mountain_001"])
    )
    assert out[0].pdu.code == ErrorCode.ILLEGAL_DECK.value


def test_player_ready_rejected_outside_lobby():
    state = GameState(lifecycle=Lifecycle.IN_GAME)
    out = lifecycle.handle_player_ready(state, "player_1", _ready(["mountain_001"]))
    assert out[0].pdu.code == ErrorCode.WRONG_PHASE.value


def test_play_land_rejects_non_land_card():
    state = _game_state(hand=["shock_001"])
    out = turn.handle_play_land(
        state, "player_1", PlayLand(seq_num=1, card_id="shock_001")
    )
    assert out[0].pdu.code == ErrorCode.ILLEGAL_ACTION.value
    assert state.players["alice"].hand == ["shock_001"]


def test_cast_sorcery_rejected_outside_main_phase():
    state = _game_state(
        phase=Phase.UPKEEP,
        hand=["flame_slash_001"],
        battlefield=[Permanent(id="mountain_001")],
    )
    state.players["bob"].battlefield.append(
        Permanent(id="grizzly_bears_001", power=2, toughness=2, damage=0)
    )
    out = cast.handle_cast_spell(
        state,
        "player_1",
        CastSpell(
            seq_num=1,
            card_id="flame_slash_001",
            targets=["grizzly_bears_001"],
            mana_payment={"R": 1},
        ),
    )
    assert out[0].pdu.code == ErrorCode.WRONG_PHASE.value


def test_cast_noninstant_rejected_when_stack_is_not_empty():
    state = _game_state(
        hand=["goblin_guide_001"],
        battlefield=[Permanent(id="mountain_001")],
    )
    state.stack.append(
        StackItem("stk_1", "SPELL", "shock_001", "bob", ["alice"])
    )
    out = cast.handle_cast_spell(
        state,
        "player_1",
        CastSpell(
            seq_num=1,
            card_id="goblin_guide_001",
            targets=[],
            mana_payment={"R": 1},
        ),
    )
    assert out[0].pdu.code == ErrorCode.WRONG_PHASE.value


def test_cast_rejects_fabricated_mana_without_sources():
    state = _game_state(hand=["shock_001"])
    out = cast.handle_cast_spell(
        state,
        "player_1",
        CastSpell(
            seq_num=1,
            card_id="shock_001",
            targets=["bob"],
            mana_payment={"R": 1},
        ),
    )
    assert out[0].pdu.code == ErrorCode.INSUFFICIENT_MANA.value
    assert state.stack == []


def test_cast_taps_authoritative_mana_source():
    mountain = Permanent(id="mountain_001")
    state = _game_state(hand=["shock_001"], battlefield=[mountain])
    out = cast.handle_cast_spell(
        state,
        "player_1",
        CastSpell(
            seq_num=1,
            card_id="shock_001",
            targets=["bob"],
            mana_payment={"R": 1},
        ),
    )
    assert any(o.pdu.type == "STACK_PUSH" for o in out)
    assert mountain.tapped is True


def test_permanent_with_catalog_effect_casts_as_permanent_not_damage_spell(monkeypatch):
    island_sources = [Permanent(id=f"island_{n:03d}") for n in range(1, 4)]
    state = _game_state(hand=["prodigal_sorcerer_001"], battlefield=island_sources)
    monkeypatch.setattr("mtgnp.server.priority.grant", lambda state, player_id: [])
    cast.handle_cast_spell(
        state,
        "player_1",
        CastSpell(
            seq_num=1,
            card_id="prodigal_sorcerer_001",
            targets=[],
            mana_payment={"U": 1, "generic": 2},
        ),
    )
    stack.resolve_top(state)
    assert any(p.id == "prodigal_sorcerer_001" for p in state.players["alice"].battlefield)
    assert state.players["bob"].life == 20


def test_resolved_instant_moves_to_owners_graveyard(monkeypatch):
    state = _game_state()
    state.stack = [StackItem("stk", "SPELL", "shock_001", "alice", ["bob"])]
    monkeypatch.setattr("mtgnp.server.priority.grant", lambda state, player_id: [])
    stack.resolve_top(state)
    assert "shock_001" in state.players["alice"].graveyard
    assert state.players["bob"].life == 18


def test_fizzled_instant_moves_to_owners_graveyard(monkeypatch):
    state = _game_state()
    state.stack = [
        StackItem("stk", "SPELL", "shock_001", "alice", ["missing_target"])
    ]
    monkeypatch.setattr("mtgnp.server.priority.grant", lambda state, player_id: [])
    out = stack.resolve_top(state)
    assert "shock_001" in state.players["alice"].graveyard
    assert out[0].pdu.result == "FIZZLE"


def test_discard_rejected_outside_cleanup():
    state = _game_state(phase=Phase.END_STEP, hand=["mountain_001"] * 8)
    out = turn.handle_discard(
        state, "player_1", Discard(seq_num=1, card_ids=["mountain_001"])
    )
    assert out[0].pdu.code == ErrorCode.WRONG_PHASE.value


def test_discard_rejects_duplicate_card_ids():
    hand = [f"mountain_{n:03d}" for n in range(1, 9)]
    state = _game_state(phase=Phase.CLEANUP, hand=hand)
    out = turn.handle_discard(
        state,
        "player_1",
        Discard(seq_num=1, card_ids=["mountain_001", "mountain_001"]),
    )
    assert out[0].pdu.code == ErrorCode.ILLEGAL_ACTION.value


def test_unsupported_client_pdu_returns_error_instead_of_silent_drop(make_engine):
    from mtgnp.protocol.pdus import ActivateAbility

    engine = make_engine()
    pdu = ActivateAbility(
        seq_num=1,
        source_id="llanowar_elves_001",
        ability_index=0,
        targets=[],
        cost_payment={"tap": True, "mana": {}},
    )
    out = engine.handle("player_1", pdu.model_dump_json().encode())
    assert out[0].pdu.type == "ERROR"
    assert out[0].pdu.code == ErrorCode.ILLEGAL_ACTION.value


def test_mulligan_rejects_stale_personalized_state_token(make_engine):
    from mtgnp.protocol.pdus import MulliganChoice

    engine = make_engine(seed=3)
    engine.handle(
        "player_1",
        _ready([f"mountain_{n:03d}" for n in range(1, 8)], "alice")
        .model_dump_json()
        .encode(),
    )
    engine.handle(
        "player_2",
        _ready([f"forest_{n:03d}" for n in range(1, 8)], "bob")
        .model_dump_json()
        .encode(),
    )
    expected = engine.state.request_tokens["bob"]
    out = engine.handle(
        "player_2",
        MulliganChoice(seq_num=expected - 1, keep=True, cards_to_bottom=[])
        .model_dump_json()
        .encode(),
    )
    assert out[0].pdu.code == ErrorCode.STALE_ACTION.value


def test_cleanup_discard_rejects_stale_state_update_token():
    hand = [f"mountain_{n:03d}" for n in range(1, 9)]
    state = _game_state(phase=Phase.CLEANUP, hand=hand)
    state.request_tokens["alice"] = 41
    out = turn.handle_discard(
        state,
        "player_1",
        Discard(seq_num=40, card_ids=["mountain_001"]),
    )
    assert out[0].pdu.code == ErrorCode.STALE_ACTION.value


def test_trigger_choice_rejects_wrong_player_and_stale_token():
    from mtgnp.protocol.pdus import TriggerChoiceResponse
    from mtgnp.server import triggers
    from mtgnp.server.state import PendingTriggerChoice

    state = _game_state()
    state.pending_trigger_choice = PendingTriggerChoice(
        trigger_id="trg_1",
        source_id="gravedigger_001",
        controller_id="alice",
        legal_targets=["grizzly_bears_001"],
        request_seq_num=22,
    )
    wrong_player = triggers.handle_trigger_choice_response(
        state,
        "player_2",
        TriggerChoiceResponse(
            seq_num=22,
            trigger_id="trg_1",
            accept=True,
            chosen_target="grizzly_bears_001",
        ),
    )
    assert wrong_player[0].pdu.code == ErrorCode.TRIGGER_CHOICE_INVALID.value

    stale = triggers.handle_trigger_choice_response(
        state,
        "player_1",
        TriggerChoiceResponse(
            seq_num=21,
            trigger_id="trg_1",
            accept=True,
            chosen_target="grizzly_bears_001",
        ),
    )
    assert stale[0].pdu.code == ErrorCode.STALE_ACTION.value
