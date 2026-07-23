"""Trigger funnel tests (Phase 3, RFC §8.6): custom_effects registry + ETB
detection/placement in sba.resolve. Gray Merchant's own effect is proved
through effects.apply() in test_effects.py, matching how every other
primitive/custom resolution is tested (dispatch through apply(), not by
calling the handler directly)."""

from __future__ import annotations

from mtgnp.protocol.pdus import AttackerDeclaration, CastSpell, DeclareAttackers, PriorityPass, TriggerChoiceResponse
from mtgnp.server import custom_effects
from mtgnp.server.state import Lifecycle, Permanent, Phase, PlayerState


def test_unregistered_base_id_returns_none():
    assert custom_effects.get("__definitely_not_registered__") is None


def test_register_and_get_roundtrip():
    @custom_effects.register("__test_trigger__", kind="etb")
    def handler(state, item):
        return []

    spec = custom_effects.get("__test_trigger__")
    assert spec.resolver is handler
    assert spec.requires_target is False
    assert spec.legal_targets_fn is None
    assert spec.kicker_gated is False
    assert spec.kind == "etb"


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


def test_gravedigger_end_to_end_resolves_targeted_trigger_through_engine(make_engine):
    """Proves the Gravedigger TRIGGER_CHOICE slice (ADR 0007): CAST_SPELL ->
    creature ETB -> sba.resolve drains it, finds a legal target, holds in
    pending_trigger_choice and emits TRIGGER_CHOICE (no STACK_PUSH yet) ->
    TRIGGER_CHOICE_RESPONSE pushes the TRIGGER_ABILITY -> both pass again ->
    trigger resolves -> chosen creature card moves graveyard -> hand."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["gravedigger_001"], graveyard=["gray_merchant_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    cast_pdu = CastSpell(seq_num=1, card_id="gravedigger_001", targets=[], mana_payment={"B": 1, "generic": 3})
    engine.handle("player_1", cast_pdu.model_dump_json().encode("utf-8"))
    assert len(engine.state.stack) == 1  # Gravedigger SPELL on the stack

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token  # ETB-drain grant issued a fresh token too

    assert len(engine.state.players["alice"].battlefield) == 1
    assert engine.state.stack == []  # deferred: no push until TRIGGER_CHOICE_RESPONSE
    pending = engine.state.pending_trigger_choice
    assert pending is not None
    assert pending.source_id == "gravedigger_001"
    assert pending.legal_targets == ["gray_merchant_001"]

    response = TriggerChoiceResponse(seq_num=99, trigger_id=pending.trigger_id, accept=True, chosen_target="gray_merchant_001")
    engine.handle("player_1", response.model_dump_json().encode("utf-8"))

    assert engine.state.pending_trigger_choice is None
    assert len(engine.state.stack) == 1
    assert engine.state.stack[0].item_type == "TRIGGER_ABILITY"

    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert engine.state.stack == []
    assert engine.state.players["alice"].graveyard == []
    assert engine.state.players["alice"].hand == ["gray_merchant_001"]
    assert any(o.pdu.type == "STACK_RESOLVE" and o.pdu.result == "RESOLVED" for o in outbounds)


def test_goblin_bushwhacker_end_to_end_kicked_pumps_creatures_through_engine(make_engine):
    """Proves the kicker slice: CAST_SPELL with kicked=True and kicker mana
    paid -> creature ETB -> sba.resolve drains it (kicker_gated, not
    discarded since kicked=True) -> TRIGGER_ABILITY resolves -> +1/+0 and
    haste on every creature the controller controls."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["goblin_bushwhacker_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    cast_pdu = CastSpell(
        seq_num=1, card_id="goblin_bushwhacker_001", targets=[], mana_payment={"R": 2, "generic": 1}, kicked=True
    )
    engine.handle("player_1", cast_pdu.model_dump_json().encode("utf-8"))
    assert len(engine.state.stack) == 1  # Goblin Bushwhacker SPELL on the stack

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert len(engine.state.stack) == 1
    assert engine.state.stack[0].item_type == "TRIGGER_ABILITY"
    permanent = engine.state.players["alice"].battlefield[0]
    assert permanent.power_bonus == 0  # not yet resolved

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert engine.state.stack == []
    assert permanent.power_bonus == 1
    assert permanent.temp_haste is True
    assert any(o.pdu.type == "STACK_RESOLVE" and o.pdu.result == "RESOLVED" for o in outbounds)


def test_goblin_bushwhacker_end_to_end_unkicked_discards_trigger_through_engine(make_engine):
    """The "intervening if it was kicked" clause: casting Bushwhacker without
    kicked=True still enters the battlefield, but its trigger never reaches
    the stack (kicker_gated discard, sba.py)."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["goblin_bushwhacker_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    cast_pdu = CastSpell(seq_num=1, card_id="goblin_bushwhacker_001", targets=[], mana_payment={"R": 1}, kicked=False)
    engine.handle("player_1", cast_pdu.model_dump_json().encode("utf-8"))

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert len(engine.state.players["alice"].battlefield) == 1
    assert engine.state.stack == []
    assert not any(o.pdu.type == "STACK_PUSH" and o.pdu.item_type == "TRIGGER_ABILITY" for o in outbounds)
    permanent = engine.state.players["alice"].battlefield[0]
    assert permanent.power_bonus == 0
    assert permanent.temp_haste is False


def test_goblin_guide_end_to_end_attack_trigger_reveals_land_through_engine(make_engine):
    """Proves the ADR 0009 slice: DECLARE_ATTACKERS -> pending_attack_trigger
    queued -> the handler's own trailing priority.grant drains it through
    sba.resolve -> TRIGGER_ABILITY placed -> both pass -> resolves -> land
    revealed and moved to the defender's hand."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.phase = Phase.DECLARE_ATTACKERS
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(
            player_id="alice",
            life=20,
            battlefield=[Permanent(id="goblin_guide_001", power=2, toughness=2, damage=0, haste=True)],
        ),
        "bob": PlayerState(player_id="bob", life=20, library=["mountain_001", "grizzly_bears_002"]),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    declare_pdu = DeclareAttackers(
        seq_num=1, attackers=[AttackerDeclaration(creature_id="goblin_guide_001", target="bob")]
    )
    engine.handle("player_1", declare_pdu.model_dump_json().encode("utf-8"))

    assert engine.state.pending_attack_trigger == []  # drained by the trailing priority.grant
    assert len(engine.state.stack) == 1
    assert engine.state.stack[0].item_type == "TRIGGER_ABILITY"
    assert engine.state.players["bob"].hand == []  # not yet resolved

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert engine.state.stack == []
    assert engine.state.players["bob"].library == ["grizzly_bears_002"]
    assert engine.state.players["bob"].hand == ["mountain_001"]
    resolve = next(o for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve.pdu.result == "RESOLVED"
    assert resolve.pdu.state_changes == [
        {"type": "REVEAL", "player": "bob", "card": "mountain_001", "moved_to_hand": True}
    ]


def test_monastery_swiftspear_end_to_end_prowess_cast_trigger_through_engine(make_engine):
    """Proves the ADR 0010 slice: CAST_SPELL (noncreature) -> pending_cast_trigger
    queued -> the handler's own trailing priority.grant drains it through
    sba.resolve -> cast-trigger drain scans the caster's battlefield ->
    TRIGGER_ABILITY placed (on top of the SPELL) -> resolves first -> +1/+1
    -> then the spell itself resolves."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(
            player_id="alice",
            life=20,
            hand=["lightning_bolt_001"],
            battlefield=[Permanent(id="monastery_swiftspear_001", power=1, toughness=2)],
        ),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    cast_pdu = CastSpell(seq_num=1, card_id="lightning_bolt_001", targets=["bob"], mana_payment={"R": 1})
    engine.handle("player_1", cast_pdu.model_dump_json().encode("utf-8"))

    assert engine.state.pending_cast_trigger == []  # drained by the trailing priority.grant
    assert len(engine.state.stack) == 2
    assert engine.state.stack[0].item_type == "SPELL"
    assert engine.state.stack[1].item_type == "TRIGGER_ABILITY"

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    permanent = engine.state.players["alice"].battlefield[0]
    assert permanent.power_bonus == 1
    assert permanent.toughness_bonus == 1
    assert len(engine.state.stack) == 1  # bolt still on the stack
    assert engine.state.players["bob"].life == 20  # not yet resolved

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert engine.state.stack == []
    assert engine.state.players["bob"].life == 17
    resolve = next(o for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve.pdu.result == "RESOLVED"


def test_gravedigger_end_to_end_empty_graveyard_discards_trigger_silently(make_engine):
    """RFC §8.6.4: no legal targets -> the trigger is discarded before
    TRIGGER_CHOICE is ever sent. Zero client interaction beyond casting."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["gravedigger_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    cast_pdu = CastSpell(seq_num=1, card_id="gravedigger_001", targets=[], mana_payment={"B": 1, "generic": 3})
    engine.handle("player_1", cast_pdu.model_dump_json().encode("utf-8"))

    token = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))
    token = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token).model_dump_json().encode("utf-8"))

    assert len(engine.state.players["alice"].battlefield) == 1
    assert engine.state.stack == []
    assert engine.state.pending_trigger_choice is None
    assert not any(o.pdu.type == "TRIGGER_CHOICE" for o in outbounds)
