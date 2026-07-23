"""Trigger funnel tests (Phase 3, RFC §8.6): custom_effects registry + ETB
detection/placement in sba.resolve. Gray Merchant's own effect is proved
through effects.apply() in test_effects.py, matching how every other
primitive/custom resolution is tested (dispatch through apply(), not by
calling the handler directly)."""

from __future__ import annotations

from mtgnp.protocol.pdus import CastSpell, PriorityPass
from mtgnp.server import custom_effects
from mtgnp.server.state import Lifecycle, PlayerState


def test_unregistered_base_id_returns_none():
    assert custom_effects.get("__definitely_not_registered__") is None


def test_register_and_get_roundtrip():
    @custom_effects.register("__test_trigger__")
    def handler(state, item):
        return []

    assert custom_effects.get("__test_trigger__") is handler


def test_gray_merchant_end_to_end_resolves_etb_trigger_through_engine(make_engine):
    """Proves the full Phase 3 slice (plan bullet 3): CAST_SPELL -> creature
    ETB (SPELL resolves, pending_etb records it) -> sba.resolve drains it,
    places a TRIGGER_ABILITY -> both pass again -> trigger resolves ->
    devotion-based life drain. Zero client interaction (untargeted,
    mandatory), unlike Gravedigger's TRIGGER_CHOICE slice."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["gray_merchant_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    cast_pdu = CastSpell(seq_num=1, card_id="gray_merchant_001", targets=[], mana_payment={"B": 2, "generic": 3})
    engine.handle("player_1", cast_pdu.model_dump_json().encode("utf-8"))
    assert len(engine.state.stack) == 1  # Gray Merchant SPELL on the stack

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert len(engine.state.players["alice"].battlefield) == 1
    assert len(engine.state.stack) == 1
    assert engine.state.stack[0].item_type == "TRIGGER_ABILITY"
    assert engine.state.players["bob"].life == 20  # not yet drained

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert engine.state.stack == []
    assert engine.state.players["bob"].life == 18  # devotion 2 (BB)
    assert engine.state.players["alice"].life == 22
    assert any(o.pdu.type == "STACK_RESOLVE" and o.pdu.result == "RESOLVED" for o in outbounds)
