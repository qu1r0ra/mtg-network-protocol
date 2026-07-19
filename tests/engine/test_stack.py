"""Stack tests (RFC §8.3-8.4), tested directly against stack.py's pure
functions (not through engine.handle, which isn't wired yet)."""

from mtgnp.server import priority, stack
from mtgnp.server.state import GameState, Lifecycle, Permanent, PlayerState, StackItem


def _two_player_state() -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=1, phase=None)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    return state


def _item(**overrides) -> StackItem:
    fields = dict(
        stack_item_id="stk_01",
        item_type="SPELL",
        source_id="lightning_bolt_001",
        controller_id="alice",
        targets=["bob"],
    )
    fields.update(overrides)
    return StackItem(**fields)


# --- push ---------------------------------------------------------------


def test_push_appends_to_stack_and_broadcasts_stack_push():
    state = _two_player_state()
    item = _item()

    outbounds = stack.push(state, item)

    assert state.stack == [item]
    assert len(outbounds) == 1
    push_pdu = outbounds[0].pdu
    assert outbounds[0].recipient == "ALL"
    assert push_pdu.type == "STACK_PUSH"
    assert push_pdu.stack_item_id == "stk_01"
    assert push_pdu.item_type == "SPELL"
    assert push_pdu.source == "lightning_bolt_001"
    assert push_pdu.controller == "alice"
    assert push_pdu.targets == ["bob"]


def test_push_does_not_grant_priority():
    state = _two_player_state()

    stack.push(state, _item())

    assert state.priority_holder is None


# --- resolve_top: FIZZLE -------------------------------------------------


def test_resolve_top_fizzles_when_all_targets_illegal():
    state = _two_player_state()
    state.stack.append(_item(targets=["nonexistent_permanent"]))

    outbounds = stack.resolve_top(state)

    assert state.stack == []
    resolve_pdu = next(o.pdu for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve_pdu.result == "FIZZLE"
    assert resolve_pdu.state_changes == []


def test_resolve_top_fizzle_still_regrants_active_player_priority():
    state = _two_player_state()
    state.stack.append(_item(targets=["nonexistent_permanent"]))

    outbounds = stack.resolve_top(state)

    grant_pdu = next(o.pdu for o in outbounds if o.pdu.type == "PRIORITY_GRANT")
    assert grant_pdu.player_id == "alice"
    assert state.priority_holder == "alice"


# --- resolve_top: RESOLVED ------------------------------------------------


def test_resolve_top_resolves_when_a_player_target_is_legal():
    state = _two_player_state()
    state.stack.append(_item(targets=["bob"]))

    outbounds = stack.resolve_top(state)

    assert state.stack == []
    resolve_pdu = next(o.pdu for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve_pdu.result == "RESOLVED"
    gsu_recipients = {o.recipient for o in outbounds if o.pdu.type == "GAME_STATE_UPDATE"}
    assert gsu_recipients == {"player_1", "player_2"}


def test_resolve_top_resolves_when_a_permanent_target_is_legal():
    state = _two_player_state()
    state.players["bob"].battlefield = [Permanent(id="bear_1", power=2, toughness=2)]
    state.stack.append(_item(targets=["bear_1"]))

    outbounds = stack.resolve_top(state)

    resolve_pdu = next(o.pdu for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve_pdu.result == "RESOLVED"


def test_resolve_top_resolves_untargeted_item():
    state = _two_player_state()
    state.stack.append(_item(targets=[]))

    outbounds = stack.resolve_top(state)

    resolve_pdu = next(o.pdu for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve_pdu.result == "RESOLVED"


def test_resolve_top_pops_the_top_item_only():
    state = _two_player_state()
    bottom = _item(stack_item_id="stk_bottom", targets=[])
    top = _item(stack_item_id="stk_top", targets=[])
    state.stack = [bottom, top]

    outbounds = stack.resolve_top(state)

    assert state.stack == [bottom]
    resolve_pdu = next(o.pdu for o in outbounds if o.pdu.type == "STACK_RESOLVE")
    assert resolve_pdu.stack_item_id == "stk_top"


# --- handle_pass -> resolve_top integration ------------------------------


def test_both_pass_with_nonempty_stack_resolves_top_item():
    state = _two_player_state()
    state.stack.append(_item(targets=[]))
    priority.grant(state, "alice")
    token = state.priority_token

    from mtgnp.protocol.pdus import PriorityPass

    priority.handle_pass(state, "player_1", PriorityPass(seq_num=token))
    outbounds = priority.handle_pass(state, "player_2", PriorityPass(seq_num=state.priority_token))

    assert state.stack == []
    assert any(o.pdu.type == "STACK_RESOLVE" for o in outbounds)
