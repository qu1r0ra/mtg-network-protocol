"""Combat sub-state machine tests (RFC §9), tested directly against combat.py's
pure functions (same seam as test_turn.py/test_stack.py -- not through
engine.handle)."""

import pytest

from mtgnp.protocol.pdus import (
    AssignDamageOrder,
    AttackerDeclaration,
    BlockerDeclaration,
    DeclareAttackers,
    DeclareBlockers,
    PriorityPass,
)
from mtgnp.server import combat, priority, turn
from mtgnp.server.state import GameState, Lifecycle, Permanent, Phase, PlayerState


def _two_player_state(phase: Phase = Phase.BEGIN_COMBAT) -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=1, phase=phase)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20),
        "bob": PlayerState(player_id="bob", life=20),
    }
    state.active_player = "alice"
    return state


def _pass(state: GameState, connection_id: str) -> list:
    pdu = PriorityPass(seq_num=state.priority_token)
    return priority.handle_pass(state, connection_id, pdu)


def _creature(id_, power=2, toughness=2, **kwargs) -> Permanent:
    return Permanent(id=id_, power=power, toughness=toughness, damage=0, **kwargs)


# --- begin_combat -------------------------------------------------------------


def test_begin_combat_opens_ap_priority_window():
    state = _two_player_state()

    outbounds = combat.begin_combat(state)

    assert state.priority_holder == "alice"
    assert outbounds[0].pdu.type == "PRIORITY_GRANT"
    assert outbounds[0].pdu.player_id == "alice"


def test_begin_combat_pass_pass_advances_to_declare_attackers():
    state = _two_player_state()
    combat.begin_combat(state)

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.DECLARE_ATTACKERS
    assert state.priority_holder == "alice"
    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[0].to_phase == "DECLARE_ATTACKERS"


# --- declare attackers ---------------------------------------------------------


def _at_declare_attackers() -> GameState:
    state = _two_player_state()
    state.players["alice"].battlefield = [_creature("goblin_1"), _creature("goblin_2", tapped=True)]
    combat.begin_combat(state)
    _pass(state, "player_1")
    _pass(state, "player_2")
    assert state.phase == Phase.DECLARE_ATTACKERS
    return state


def test_declare_attackers_taps_and_opens_ap_response_window():
    state = _at_declare_attackers()
    token = state.priority_token

    outbounds = combat.handle_declare_attackers(
        state, "player_1", DeclareAttackers(seq_num=token, attackers=[AttackerDeclaration(creature_id="goblin_1", target="bob")])
    )

    assert state.players["alice"].battlefield[0].tapped is True
    assert state.attackers == {"goblin_1": "bob"}
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"


def test_declare_tapped_creature_as_attacker_rejected():
    state = _at_declare_attackers()
    token = state.priority_token

    outbounds = combat.handle_declare_attackers(
        state, "player_1", DeclareAttackers(seq_num=token, attackers=[AttackerDeclaration(creature_id="goblin_2", target="bob")])
    )

    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == "ILLEGAL_ACTION"
    assert state.attackers == {}


def test_declare_no_attackers_skips_straight_to_end_of_combat():
    state = _at_declare_attackers()
    token = state.priority_token

    outbounds = combat.handle_declare_attackers(state, "player_1", DeclareAttackers(seq_num=token, attackers=[]))

    assert state.phase == Phase.END_OF_COMBAT
    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[0].to_phase == "END_OF_COMBAT"
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"


# --- declare blockers -----------------------------------------------------------


def _at_declare_blockers() -> GameState:
    state = _at_declare_attackers()
    token = state.priority_token
    combat.handle_declare_attackers(
        state, "player_1", DeclareAttackers(seq_num=token, attackers=[AttackerDeclaration(creature_id="goblin_1", target="bob")])
    )
    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")
    assert state.phase == Phase.DECLARE_BLOCKERS
    assert state.priority_holder == "bob"
    return state


def test_declare_blockers_opens_ap_response_window():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1")]
    token = state.priority_token

    outbounds = combat.handle_declare_blockers(
        state, "player_2", DeclareBlockers(seq_num=token, blockers=[BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1")])
    )

    assert state.blockers == {"wall_1": "goblin_1"}
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"


def test_declare_blocker_targeting_non_attacker_rejected():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1")]
    token = state.priority_token

    outbounds = combat.handle_declare_blockers(
        state, "player_2", DeclareBlockers(seq_num=token, blockers=[BlockerDeclaration(creature_id="wall_1", blocking_id="not_an_attacker")])
    )

    assert outbounds[0].pdu.code == "ILLEGAL_ACTION"
    assert state.blockers == {}


def test_ap_cannot_declare_blockers():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1")]
    token = state.priority_token

    outbounds = combat.handle_declare_blockers(
        state, "player_1", DeclareBlockers(seq_num=token, blockers=[])
    )

    assert outbounds[0].pdu.code == "NOT_YOUR_PRIORITY"


# --- unblocked damage: DECLARE_BLOCKERS -> COMBAT_DAMAGE directly -------------


def test_unblocked_attacker_deals_damage_to_defender_and_ends_combat():
    state = _at_declare_blockers()
    token = state.priority_token
    combat.handle_declare_blockers(state, "player_2", DeclareBlockers(seq_num=token, blockers=[]))

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")  # DECLARE_BLOCKERS -> no multi-block, no fs/ds -> COMBAT_DAMAGE -> END_OF_COMBAT

    assert state.players["bob"].life == 18  # goblin_1 power=2
    assert state.phase == Phase.END_OF_COMBAT
    result = next(o.pdu for o in outbounds if o.pdu.type == "COMBAT_DAMAGE_RESULT")
    assert result.damage_events[0].model_dump() == {"source": "goblin_1", "target": "bob", "amount": 2}
    assert result.life_totals == {"alice": 20, "bob": 18}
    assert result.creatures_died == []


def test_blocked_attacker_and_blocker_trade_damage_no_trample():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1", power=1, toughness=5)]
    token = state.priority_token
    combat.handle_declare_blockers(
        state, "player_2", DeclareBlockers(seq_num=token, blockers=[BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1")])
    )

    _pass(state, "player_1")
    _pass(state, "player_2")

    assert state.players["bob"].life == 20  # no trample: goblin_1 hits wall_1, not bob
    wall = next(p for p in state.players["bob"].battlefield if p.id == "wall_1")
    goblin = next(p for p in state.players["alice"].battlefield if p.id == "goblin_1")
    assert wall.damage == 2
    assert goblin.damage == 1


def test_lethal_combat_damage_moves_creature_to_graveyard():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1", power=1, toughness=1)]
    token = state.priority_token
    combat.handle_declare_blockers(
        state, "player_2", DeclareBlockers(seq_num=token, blockers=[BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1")])
    )

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert "wall_1" not in [p.id for p in state.players["bob"].battlefield]
    assert "wall_1" in state.players["bob"].graveyard
    result = next(o.pdu for o in outbounds if o.pdu.type == "COMBAT_DAMAGE_RESULT")
    assert result.creatures_died == ["wall_1"]


# --- multi-block damage order ---------------------------------------------------


def test_multi_block_routes_to_assign_damage_order():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1", power=1, toughness=5), _creature("wall_2", power=1, toughness=5)]
    token = state.priority_token
    combat.handle_declare_blockers(
        state,
        "player_2",
        DeclareBlockers(
            seq_num=token,
            blockers=[
                BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1"),
                BlockerDeclaration(creature_id="wall_2", blocking_id="goblin_1"),
            ],
        ),
    )

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.ASSIGN_DAMAGE_ORDER
    assert state.pending_damage_order == ["goblin_1"]
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"


def test_damage_order_splits_lethal_first_then_remainder_to_last():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1", power=1, toughness=1), _creature("wall_2", power=1, toughness=5)]
    goblin = next(p for p in state.players["alice"].battlefield if p.id == "goblin_1")
    goblin.power = 3
    token = state.priority_token
    combat.handle_declare_blockers(
        state,
        "player_2",
        DeclareBlockers(
            seq_num=token,
            blockers=[
                BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1"),
                BlockerDeclaration(creature_id="wall_2", blocking_id="goblin_1"),
            ],
        ),
    )
    _pass(state, "player_1")
    _pass(state, "player_2")
    assert state.phase == Phase.ASSIGN_DAMAGE_ORDER
    token = state.priority_token

    outbounds = combat.handle_assign_damage_order(
        state, "player_1", AssignDamageOrder(seq_num=token, attacker_id="goblin_1", blocker_order=["wall_1", "wall_2"])
    )

    assert state.damage_order == {"goblin_1": ["wall_1", "wall_2"]}
    assert state.pending_damage_order == []
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"

    _pass(state, "player_1")
    _pass(state, "player_2")

    assert "wall_1" in state.players["bob"].graveyard  # 1 damage, lethal (toughness 1)
    wall_2 = next(p for p in state.players["bob"].battlefield if p.id == "wall_2")
    assert wall_2.damage == 2  # remaining 3 - 1 lethal = 2 overkill, no trample to player


def test_assign_damage_order_for_unlisted_attacker_rejected():
    state = _at_declare_blockers()
    state.players["bob"].battlefield = [_creature("wall_1", power=1, toughness=1), _creature("wall_2", power=1, toughness=5)]
    token = state.priority_token
    combat.handle_declare_blockers(
        state,
        "player_2",
        DeclareBlockers(
            seq_num=token,
            blockers=[
                BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1"),
                BlockerDeclaration(creature_id="wall_2", blocking_id="goblin_1"),
            ],
        ),
    )
    _pass(state, "player_1")
    _pass(state, "player_2")
    token = state.priority_token

    outbounds = combat.handle_assign_damage_order(
        state, "player_1", AssignDamageOrder(seq_num=token, attacker_id="not_multiblocked", blocker_order=[])
    )

    assert outbounds[0].pdu.code == "ILLEGAL_ACTION"


# --- first strike / double strike ------------------------------------------------


def test_first_strike_attacker_kills_blocker_before_regular_damage_step():
    state = _at_declare_blockers()
    goblin = next(p for p in state.players["alice"].battlefield if p.id == "goblin_1")
    goblin.first_strike = True
    goblin.power = 3
    state.players["bob"].battlefield = [_creature("wall_1", power=1, toughness=2)]
    token = state.priority_token
    combat.handle_declare_blockers(
        state, "player_2", DeclareBlockers(seq_num=token, blockers=[BlockerDeclaration(creature_id="wall_1", blocking_id="goblin_1")])
    )

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")
    assert state.phase == Phase.FIRST_STRIKE_DAMAGE
    assert "wall_1" in state.players["bob"].graveyard
    assert goblin.damage == 0  # wall_1 (no first strike) never got to deal its damage back

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.END_OF_COMBAT
    assert state.players["bob"].life == 20  # wall_1 dead before regular step; goblin stays blocked, no trample
    result = next(o.pdu for o in outbounds if o.pdu.type == "COMBAT_DAMAGE_RESULT")
    assert result.damage_events == []


def test_double_strike_deals_damage_in_both_steps():
    state = _at_declare_blockers()
    goblin = next(p for p in state.players["alice"].battlefield if p.id == "goblin_1")
    goblin.double_strike = True
    token = state.priority_token
    combat.handle_declare_blockers(state, "player_2", DeclareBlockers(seq_num=token, blockers=[]))

    _pass(state, "player_1")
    _pass(state, "player_2")
    assert state.phase == Phase.FIRST_STRIKE_DAMAGE
    assert state.players["bob"].life == 18  # first hit

    _pass(state, "player_1")
    _pass(state, "player_2")

    assert state.players["bob"].life == 16  # second hit in COMBAT_DAMAGE


# --- end of combat ----------------------------------------------------------------


def test_end_of_combat_clears_state_and_hands_off_to_postcombat_main():
    state = _at_declare_blockers()
    token = state.priority_token
    combat.handle_declare_blockers(state, "player_2", DeclareBlockers(seq_num=token, blockers=[]))
    _pass(state, "player_1")
    _pass(state, "player_2")
    assert state.phase == Phase.END_OF_COMBAT

    goblin = next(p for p in state.players["alice"].battlefield if p.id == "goblin_1")
    assert goblin.damage == 0

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.POSTCOMBAT_MAIN
    assert state.attackers == {}
    assert state.blockers == {}
    assert state.damage_order == {}
    assert state.pending_damage_order == []
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"


def test_combat_damage_ending_the_game_skips_end_of_combat_window():
    state = _at_declare_blockers()
    state.players["bob"].life = 2
    token = state.priority_token
    combat.handle_declare_blockers(state, "player_2", DeclareBlockers(seq_num=token, blockers=[]))

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.lifecycle == Lifecycle.LOBBY  # enter_game_over resets to LOBBY
    game_over = next(o for o in outbounds if o.pdu.type == "GAME_OVER")
    assert game_over.pdu.winner_id == "alice"


# --- turn.py wiring -----------------------------------------------------------


def test_precombat_main_pass_pass_now_hands_off_to_combat_instead_of_crashing():
    state = _two_player_state(phase=Phase.PRECOMBAT_MAIN)
    priority.grant(state, "alice")
    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.BEGIN_COMBAT
    assert state.priority_holder == "alice"
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[-1].pdu.player_id == "alice"
