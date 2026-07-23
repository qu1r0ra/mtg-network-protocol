"""CAST_SPELL handler tests (Phase 2, docs/agents/plan-effects-catalog-triggers.md):
tested directly against cast.py's pure functions, plus one end-to-end proof
through engine.handle for the full CAST_SPELL -> STACK_PUSH -> resolve slice.
"""

from __future__ import annotations

from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import CastSpell, PriorityPass
from mtgnp.server import cast
from mtgnp.server import priority
from mtgnp.server.state import GameState, Lifecycle, PlayerState, StackItem


def _two_player_state(*, hand: list[str] | None = None) -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=1, phase=None)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=hand if hand is not None else ["lightning_bolt_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    state.priority_holder = "alice"
    state.priority_token = 1
    return state


def _bolt_pdu(**overrides) -> CastSpell:
    fields = dict(seq_num=1, card_id="lightning_bolt_001", targets=["bob"], mana_payment={"R": 1})
    fields.update(overrides)
    return CastSpell(**fields)


def test_cast_spell_pushes_stack_item_and_removes_from_hand():
    state = _two_player_state()

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu())

    assert "lightning_bolt_001" not in state.players["alice"].hand
    assert len(state.stack) == 1
    item = state.stack[0]
    assert item.source_id == "lightning_bolt_001"
    assert item.controller_id == "alice"
    assert item.targets == ["bob"]
    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def test_cast_spell_caster_retains_priority_after_push():
    state = _two_player_state()

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu())

    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert len(grants) == 1
    assert grants[0].pdu.player_id == "alice"
    assert state.priority_holder == "alice"


def test_cast_spell_insufficient_mana_rejected():
    state = _two_player_state()

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu(mana_payment={}))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.INSUFFICIENT_MANA.value
    assert "lightning_bolt_001" in state.players["alice"].hand
    assert state.stack == []


def test_cast_spell_wrong_target_count_rejected():
    state = _two_player_state()

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu(targets=["bob", "alice"]))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_TARGET.value
    assert state.stack == []


def test_cast_spell_illegal_target_rejected():
    state = _two_player_state()

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu(targets=["nonexistent_creature"]))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_TARGET.value


def test_cast_spell_card_not_in_hand_rejected():
    state = _two_player_state(hand=[])

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu())

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_ACTION.value


def test_cast_creature_spell_rejects_declared_targets():
    state = _two_player_state(hand=["gravedigger_001"])
    pdu = CastSpell(seq_num=1, card_id="gravedigger_001", targets=["bob"], mana_payment={"B": 1, "generic": 3})

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_TARGET.value


def test_cast_creature_spell_with_no_targets_pushes_stack():
    state = _two_player_state(hand=["gravedigger_001"])
    pdu = CastSpell(seq_num=1, card_id="gravedigger_001", targets=[], mana_payment={"B": 1, "generic": 3})

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert len(state.stack) == 1
    assert state.stack[0].targets == []
    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def test_cast_noncreature_spell_queues_a_cast_trigger_as_noncreature(monkeypatch):
    """ADR 0010: Lightning Bolt (Instant) queues (caster_id, True). Its
    trailing `priority.grant` synchronously drains the queue via
    sba.resolve, same as every other pending-queue append in this engine, so
    `priority.grant` is stubbed out here to inspect the queue before that
    happens."""
    monkeypatch.setattr(priority, "grant", lambda state, player_id: [])
    state = _two_player_state()

    cast.handle_cast_spell(state, "player_1", _bolt_pdu())

    assert state.pending_cast_trigger == [("alice", True)]


def test_cast_creature_spell_queues_a_cast_trigger_as_not_noncreature(monkeypatch):
    """ADR 0010: a creature spell still queues an entry (drain-time filters
    it), but flagged is_noncreature=False."""
    monkeypatch.setattr(priority, "grant", lambda state, player_id: [])
    state = _two_player_state(hand=["gravedigger_001"])
    pdu = CastSpell(seq_num=1, card_id="gravedigger_001", targets=[], mana_payment={"B": 1, "generic": 3})

    cast.handle_cast_spell(state, "player_1", pdu)

    assert state.pending_cast_trigger == [("alice", False)]


def test_cast_spell_targeting_a_player_does_not_queue_a_targeted_trigger(monkeypatch):
    """ADR 0011: only permanent targets queue -- a player target (Bolt at a
    face) is not "a permanent became the target of a spell or ability"."""
    monkeypatch.setattr(priority, "grant", lambda state, player_id: [])
    state = _two_player_state()

    cast.handle_cast_spell(state, "player_1", _bolt_pdu(targets=["bob"]))

    assert state.pending_targeted_trigger == []


def test_cast_spell_targeting_a_permanent_queues_a_targeted_trigger(monkeypatch):
    """ADR 0011: Bolt at a creature on bob's battlefield queues
    (target_id, controller_id) for the targeted-trigger drain."""
    from mtgnp.server.state import Permanent

    monkeypatch.setattr(priority, "grant", lambda state, player_id: [])
    state = _two_player_state()
    state.players["bob"].battlefield.append(Permanent(id="phantasmal_bear_001", power=2, toughness=2))

    cast.handle_cast_spell(state, "player_1", _bolt_pdu(targets=["phantasmal_bear_001"]))

    assert state.pending_targeted_trigger == [("phantasmal_bear_001", "bob")]


def test_cast_spell_targeting_a_permanent_protected_by_a_different_caster_rejected():
    """ADR 0012: bob's Vines protected the bear against everyone but bob --
    alice's Bolt at it is illegal even though the bear itself still exists."""
    from mtgnp.server.state import Permanent

    state = _two_player_state()
    state.players["bob"].battlefield.append(
        Permanent(id="phantasmal_bear_001", power=2, toughness=2, protected_by="bob")
    )

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu(targets=["phantasmal_bear_001"]))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_TARGET.value


def test_cast_spell_targeting_a_permanent_protected_by_the_caster_allowed():
    """The protecting player can still target their own protected permanent."""
    from mtgnp.server.state import Permanent

    state = _two_player_state()
    state.players["bob"].battlefield.append(
        Permanent(id="phantasmal_bear_001", power=2, toughness=2, protected_by="alice")
    )

    outbounds = cast.handle_cast_spell(state, "player_1", _bolt_pdu(targets=["phantasmal_bear_001"]))

    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def test_cast_counterspell_targeting_a_spell_on_the_stack_pushes():
    state = _two_player_state(hand=["counterspell_001"])
    state.stack = [
        StackItem(stack_item_id="stk_bear", item_type="SPELL", source_id="bear_001", controller_id="bob", targets=[])
    ]
    pdu = CastSpell(seq_num=1, card_id="counterspell_001", targets=["stk_bear"], mana_payment={"U": 2})

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert len(state.stack) == 2
    assert state.stack[-1].targets == ["stk_bear"]
    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def test_cast_counterspell_targeting_a_player_rejected():
    state = _two_player_state(hand=["counterspell_001"])

    outbounds = cast.handle_cast_spell(
        state, "player_1",
        CastSpell(seq_num=1, card_id="counterspell_001", targets=["bob"], mana_payment={"U": 2}),
    )

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_TARGET.value


def test_cast_kicked_spell_requires_kicker_cost_paid():
    state = _two_player_state(hand=["goblin_bushwhacker_001"])
    pdu = CastSpell(seq_num=1, card_id="goblin_bushwhacker_001", targets=[], mana_payment={"R": 1}, kicked=True)

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.INSUFFICIENT_MANA.value
    assert "goblin_bushwhacker_001" in state.players["alice"].hand


def test_cast_kicked_spell_with_kicker_cost_paid_pushes_stack():
    state = _two_player_state(hand=["goblin_bushwhacker_001"])
    pdu = CastSpell(
        seq_num=1, card_id="goblin_bushwhacker_001", targets=[], mana_payment={"R": 2, "generic": 1}, kicked=True
    )

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert len(state.stack) == 1
    assert state.stack[0].kicked is True
    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def test_cast_unkicked_spell_does_not_require_kicker_cost():
    state = _two_player_state(hand=["goblin_bushwhacker_001"])
    pdu = CastSpell(seq_num=1, card_id="goblin_bushwhacker_001", targets=[], mana_payment={"R": 1}, kicked=False)

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert len(state.stack) == 1
    assert state.stack[0].kicked is False
    assert any(o.pdu.type == "STACK_PUSH" for o in outbounds)


def test_cast_kicked_spell_on_card_with_no_kicker_cost_rejected():
    state = _two_player_state()
    pdu = _bolt_pdu(kicked=True)

    outbounds = cast.handle_cast_spell(state, "player_1", pdu)

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_ACTION.value


def test_cast_spell_end_to_end_lightning_bolt_resolves_through_engine(make_engine):
    """Proves the full vertical slice (plan Phase 2): CAST_SPELL -> STACK_PUSH
    -> both pass -> STACK_RESOLVE deals 3 damage -> life total drops."""
    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["lightning_bolt_001"]),
        "bob": PlayerState(player_id="bob", life=20),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    engine.handle(
        "player_1",
        _bolt_pdu(seq_num=1).model_dump_json().encode("utf-8"),
    )
    assert len(engine.state.stack) == 1
    token_after_cast = engine.state.priority_token

    engine.handle("player_1", PriorityPass(seq_num=token_after_cast).model_dump_json().encode("utf-8"))
    token_for_bob = engine.state.priority_token
    outbounds = engine.handle("player_2", PriorityPass(seq_num=token_for_bob).model_dump_json().encode("utf-8"))

    assert engine.state.players["bob"].life == 17
    assert engine.state.stack == []
    assert any(o.pdu.type == "STACK_RESOLVE" and o.pdu.result == "RESOLVED" for o in outbounds)


def test_cast_kicked_vines_of_vastwood_end_to_end_protects_and_pumps_through_engine(make_engine):
    """ADR 0012 full vertical slice: kicked CAST_SPELL -> STACK_PUSH -> both
    pass -> STACK_RESOLVE sets protected_by and applies +4/+4, then a
    follow-up Bolt from the opponent at the now-protected bear is rejected."""
    from mtgnp.server.state import Permanent

    engine = make_engine()
    engine.state.lifecycle = Lifecycle.IN_GAME
    engine.state.turn = 1
    engine.state.connections = {"player_1": "alice", "player_2": "bob"}
    engine.state.players = {
        "alice": PlayerState(player_id="alice", life=20, hand=["vines_of_vastwood_001", "lightning_bolt_001"]),
        "bob": PlayerState(
            player_id="bob", life=20, hand=["lightning_bolt_001"],
            battlefield=[Permanent(id="bear_1", power=2, toughness=2)],
        ),
    }
    engine.state.active_player = "alice"
    engine.state.priority_holder = "alice"
    engine.state.priority_token = 1

    vines_pdu = CastSpell(
        seq_num=1, card_id="vines_of_vastwood_001", targets=["bear_1"],
        mana_payment={"G": 2}, kicked=True,
    )
    engine.handle("player_1", vines_pdu.model_dump_json().encode("utf-8"))
    token_after_cast = engine.state.priority_token
    engine.handle("player_1", PriorityPass(seq_num=token_after_cast).model_dump_json().encode("utf-8"))
    token_for_bob = engine.state.priority_token
    engine.handle("player_2", PriorityPass(seq_num=token_for_bob).model_dump_json().encode("utf-8"))

    bear = engine.state.players["bob"].battlefield[0]
    assert bear.protected_by == "alice"
    assert bear.power_bonus == 4
    assert bear.toughness_bonus == 4

    # resolve_top re-grants AP (alice) priority; pass it to bob before he acts.
    engine.handle("player_1", PriorityPass(seq_num=engine.state.priority_token).model_dump_json().encode("utf-8"))

    bolt_pdu = _bolt_pdu(seq_num=engine.state.priority_token, targets=["bear_1"])
    outbounds = engine.handle("player_2", bolt_pdu.model_dump_json().encode("utf-8"))

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == ErrorCode.ILLEGAL_TARGET.value
