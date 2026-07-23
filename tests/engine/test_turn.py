"""Turn/phase driver tests (RFC §7), tested directly against turn.py's pure
functions (not through engine.handle, which isn't wired yet). Two spines, split
at the BEGIN_COMBAT wall (combat.py is still a stub):

  * pre-combat: begin_turn -> UPKEEP -> DRAW -> PRECOMBAT_MAIN -> (combat wall)
  * post-combat: a GameState seeded already at POSTCOMBAT_MAIN -> END_STEP ->
    CLEANUP -> next turn's UNTAP/UPKEEP
"""

import pytest

from mtgnp.protocol.pdus import Discard, PlayLand, PriorityPass
from mtgnp.server import priority, turn
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, Lifecycle, Permanent, Phase, PlayerState


def _two_player_state(turn_no: int = 1, phase: Phase | None = None) -> GameState:
    state = GameState(lifecycle=Lifecycle.IN_GAME, turn=turn_no, phase=phase)
    state.connections = {"player_1": "alice", "player_2": "bob"}
    state.players = {
        "alice": PlayerState(player_id="alice", life=20, library=["lib_a1", "lib_a2"], hand=["hand_a1"]),
        "bob": PlayerState(player_id="bob", life=20, library=["lib_b1", "lib_b2"], hand=["hand_b1"]),
    }
    state.active_player = "alice"
    return state


def _pass(state: GameState, connection_id: str) -> list[Outbound]:
    pdu = PriorityPass(seq_num=state.priority_token)
    return priority.handle_pass(state, connection_id, pdu)


# --- begin_turn / UNTAP ------------------------------------------------------


def test_begin_turn_untaps_ap_permanents_and_resets_land_played():
    state = _two_player_state()
    state.players["alice"].battlefield = [Permanent(id="mountain_1", tapped=True)]
    state.land_played_this_turn = True

    turn.begin_turn(state, "MULLIGAN")

    assert state.players["alice"].battlefield[0].tapped is False
    assert state.land_played_this_turn is False


def test_begin_turn_broadcasts_untap_transition_then_state_then_upkeep_grant():
    state = _two_player_state()

    outbounds = turn.begin_turn(state, "MULLIGAN")

    assert outbounds[0].recipient == "ALL"
    assert outbounds[0].pdu.type == "PHASE_TRANSITION"
    assert outbounds[0].pdu.from_phase == "MULLIGAN"
    assert outbounds[0].pdu.to_phase == "UNTAP"

    gsu_recipients = {o.recipient for o in outbounds if o.pdu.type == "GAME_STATE_UPDATE"}
    assert gsu_recipients == {"player_1", "player_2"}

    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[1].from_phase == "UNTAP"
    assert transitions[1].to_phase == "UPKEEP"

    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert len(grants) == 1
    assert grants[0].pdu.player_id == "alice"
    assert state.phase == Phase.UPKEEP
    assert state.priority_holder == "alice"


def test_in_game_gsu_hides_opponent_hand_behind_a_count():
    state = _two_player_state()

    outbounds = turn.begin_turn(state, "MULLIGAN")

    alice_gsu = next(o for o in outbounds if o.recipient == "player_1" and o.pdu.type == "GAME_STATE_UPDATE")
    assert alice_gsu.pdu.state["hand"] == ["hand_a1"]
    assert alice_gsu.pdu.state["hand_counts"] == {"bob": 1}


# --- priority pass-through to DRAW/PRECOMBAT_MAIN ----------------------------


def test_both_pass_upkeep_advances_to_draw_and_draws_ap_card():
    state = _two_player_state(turn_no=2)
    turn.begin_turn(state, "CLEANUP")
    assert state.phase == Phase.UPKEEP

    _pass(state, "player_1")  # alice (AP) passes
    outbounds = _pass(state, "player_2")  # bob passes -> stack empty -> advance

    assert state.phase == Phase.DRAW
    assert state.players["alice"].hand == ["hand_a1", "lib_a1"]
    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[0].from_phase == "UPKEEP"
    assert transitions[0].to_phase == "DRAW"


def test_turn_one_skips_the_draw():
    state = _two_player_state(turn_no=1)
    turn.begin_turn(state, "MULLIGAN")

    _pass(state, "player_1")
    _pass(state, "player_2")

    assert state.phase == Phase.DRAW
    assert state.players["alice"].hand == ["hand_a1"]


def test_draw_from_empty_library_ends_the_game():
    state = _two_player_state(turn_no=2)
    state.players["alice"].library = []
    turn.begin_turn(state, "CLEANUP")

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.lifecycle == Lifecycle.LOBBY  # enter_game_over resets to LOBBY
    game_over = next(o for o in outbounds if o.pdu.type == "GAME_OVER")
    assert game_over.pdu.reason == "DECK_EMPTY"
    assert game_over.pdu.winner_id == "bob"


def test_draw_then_pass_pass_advances_to_precombat_main():
    state = _two_player_state(turn_no=2)
    turn.begin_turn(state, "CLEANUP")
    _pass(state, "player_1")
    _pass(state, "player_2")  # now in DRAW

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.PRECOMBAT_MAIN
    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[0].to_phase == "PRECOMBAT_MAIN"


# --- land play ----------------------------------------------------------------


def test_play_land_moves_card_to_battlefield_and_retains_ap_priority():
    state = _two_player_state()
    state.phase = Phase.PRECOMBAT_MAIN
    state.players["alice"].hand = ["mountain_1"]
    outbounds = priority.grant(state, "alice")
    token = state.priority_token

    outbounds = turn.handle_play_land(state, "player_1", PlayLand(seq_num=token, card_id="mountain_1"))

    assert state.players["alice"].hand == []
    assert [p.id for p in state.players["alice"].battlefield] == ["mountain_1"]
    assert state.land_played_this_turn is True
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[0].pdu.player_id == "alice"


def test_play_second_land_rejected_illegal_action():
    state = _two_player_state()
    state.phase = Phase.PRECOMBAT_MAIN
    state.players["alice"].hand = ["mountain_1", "mountain_2"]
    state.land_played_this_turn = True
    priority.grant(state, "alice")
    token = state.priority_token

    outbounds = turn.handle_play_land(state, "player_1", PlayLand(seq_num=token, card_id="mountain_2"))

    assert len(outbounds) == 1
    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == "ILLEGAL_ACTION"


def test_play_land_outside_main_phase_rejected_wrong_phase():
    state = _two_player_state()
    state.phase = Phase.UPKEEP
    state.players["alice"].hand = ["mountain_1"]
    priority.grant(state, "alice")
    token = state.priority_token

    outbounds = turn.handle_play_land(state, "player_1", PlayLand(seq_num=token, card_id="mountain_1"))

    assert outbounds[0].pdu.code == "WRONG_PHASE"


def test_nap_cannot_play_a_land():
    state = _two_player_state()
    state.phase = Phase.PRECOMBAT_MAIN
    state.players["bob"].hand = ["mountain_1"]
    priority.grant(state, "alice")
    priority.handle_pass(state, "player_1", PriorityPass(seq_num=state.priority_token))
    token = state.priority_token  # now bob holds priority

    outbounds = turn.handle_play_land(state, "player_2", PlayLand(seq_num=token, card_id="mountain_1"))

    assert outbounds[0].pdu.code == "ILLEGAL_ACTION"
    assert "mountain_1" in state.players["bob"].hand


# --- the combat hand-off ---------------------------------------------------
# See test_combat.py for the combat sub-state machine itself (RFC §9).


def test_precombat_main_pass_pass_enters_begin_combat():
    state = _two_player_state()
    state.phase = Phase.PRECOMBAT_MAIN
    priority.grant(state, "alice")
    priority.handle_pass(state, "player_1", PriorityPass(seq_num=state.priority_token))

    outbounds = priority.handle_pass(state, "player_2", PriorityPass(seq_num=state.priority_token))

    assert state.phase == Phase.BEGIN_COMBAT
    assert state.priority_holder == "alice"  # combat.begin_combat opened AP's window
    grants = [o for o in outbounds if o.pdu.type == "PRIORITY_GRANT"]
    assert grants[-1].pdu.player_id == "alice"


# --- post-combat spine: POSTCOMBAT_MAIN -> END_STEP -> CLEANUP -> next turn --


def test_postcombat_main_pass_pass_advances_to_end_step():
    state = _two_player_state()
    state.phase = Phase.POSTCOMBAT_MAIN
    priority.grant(state, "alice")

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.phase == Phase.END_STEP
    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[0].to_phase == "END_STEP"


def test_cleanup_with_legal_hand_size_advances_turn_and_swaps_ap():
    state = _two_player_state()
    state.phase = Phase.END_STEP
    priority.grant(state, "alice")

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")  # END_STEP -> CLEANUP -> auto-advance to turn 2

    assert state.turn == 2
    assert state.active_player == "bob"
    assert state.phase == Phase.UPKEEP  # begin_turn ran begin-to-end for turn 2
    transitions = [o.pdu for o in outbounds if o.pdu.type == "PHASE_TRANSITION"]
    assert transitions[0].from_phase == "END_STEP"
    assert transitions[0].to_phase == "CLEANUP"
    assert any(t.from_phase == "CLEANUP" and t.to_phase == "UNTAP" for t in transitions)


def test_cleanup_clears_temporary_power_toughness_and_haste():
    """Kicker/until-end-of-turn buffs (e.g. Goblin Bushwhacker) expire at the
    real Cleanup step, same point damage already gets cleared."""
    state = _two_player_state()
    state.phase = Phase.END_STEP
    state.players["alice"].battlefield = [
        Permanent(
            id="bear_001", power=2, toughness=2, power_bonus=1, toughness_bonus=1,
            temp_haste=True, protected_by="bob",
        )
    ]
    priority.grant(state, "alice")

    _pass(state, "player_1")
    _pass(state, "player_2")

    permanent = state.players["alice"].battlefield[0]
    assert permanent.power_bonus == 0
    assert permanent.toughness_bonus == 0
    assert permanent.temp_haste is False
    assert permanent.protected_by is None


def test_cleanup_with_too_many_cards_awaits_discard():
    state = _two_player_state()
    state.phase = Phase.END_STEP
    state.players["alice"].hand = [f"card_{i}" for i in range(9)]
    priority.grant(state, "alice")

    _pass(state, "player_1")
    outbounds = _pass(state, "player_2")

    assert state.turn == 1  # not yet advanced; awaiting DISCARD
    assert state.phase == Phase.CLEANUP
    gsu = next(o for o in outbounds if o.pdu.type == "GAME_STATE_UPDATE" and o.recipient == "player_1")
    assert len(gsu.pdu.state["hand"]) == 9


def test_discard_below_seven_finishes_cleanup():
    state = _two_player_state()
    state.phase = Phase.CLEANUP
    state.players["alice"].hand = [f"card_{i}" for i in range(9)]

    outbounds = turn.handle_discard(state, "player_1", Discard(seq_num=1, card_ids=["card_0", "card_1"]))

    assert state.players["alice"].hand == [f"card_{i}" for i in range(2, 9)]
    assert state.turn == 2
    assert state.active_player == "bob"
    assert outbounds[-1].pdu.type == "PRIORITY_GRANT"  # cleanup ran through to next turn's UPKEEP grant
    assert outbounds[-1].pdu.player_id == "bob"


def test_discard_still_above_seven_awaits_another_discard():
    state = _two_player_state()
    state.phase = Phase.CLEANUP
    state.players["alice"].hand = [f"card_{i}" for i in range(10)]

    outbounds = turn.handle_discard(state, "player_1", Discard(seq_num=1, card_ids=["card_0"]))

    assert len(state.players["alice"].hand) == 9
    assert state.turn == 1  # cleanup not finished yet
    assert all(o.pdu.type == "GAME_STATE_UPDATE" for o in outbounds)


def test_discard_unowned_card_rejected_illegal_action():
    state = _two_player_state()
    state.phase = Phase.CLEANUP
    state.players["alice"].hand = [f"card_{i}" for i in range(9)]

    outbounds = turn.handle_discard(state, "player_1", Discard(seq_num=1, card_ids=["not_in_hand"]))

    assert len(outbounds) == 1
    assert outbounds[0].recipient == "player_1"
    assert outbounds[0].pdu.type == "ERROR"
    assert outbounds[0].pdu.code == "ILLEGAL_ACTION"
    assert len(state.players["alice"].hand) == 9
