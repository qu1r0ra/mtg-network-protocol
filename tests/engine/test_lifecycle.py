"""Lifecycle state machine tests (RFC §6): LOBBY -> GAME_SETUP -> MULLIGAN ->
IN_GAME -> GAME_OVER, tested directly against lifecycle.py's pure functions
(not through engine.handle, which isn't wired yet)."""

from mtgnp.protocol.pdus import PlayerReady
from mtgnp.server import lifecycle
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState


def _deck(n: int) -> list[str]:
    return [f"mountain_{i:03d}" for i in range(1, n + 1)]


def test_player_ready_valid_first_player_gets_lobby_ack():
    state = GameState()
    pdu = PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8))

    outbounds = lifecycle.handle_player_ready(state, "player_1", pdu)

    assert outbounds == [
        Outbound(
            recipient="player_1",
            pdu=_gsu(1, {"phase": "LOBBY", "players_ready": 1, "waiting_for": ["player_2"]}),
        )
    ]
    assert state.players["player_1"].library == _deck(8)
    assert state.connections["player_1"] == "player_1"


def _gsu(seq_num: int, state: dict):
    from mtgnp.protocol.pdus import GameStateUpdate

    return GameStateUpdate(seq_num=seq_num, state=state)


def test_player_ready_duplicate_id_rejected():
    from mtgnp.protocol.errors import ErrorCode
    from mtgnp.protocol.pdus import Error

    state = GameState()
    lifecycle.handle_player_ready(state, "player_1", PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8)))

    pdu2 = PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8))
    outbounds = lifecycle.handle_player_ready(state, "player_2", pdu2)

    assert outbounds == [
        Outbound(
            recipient="player_2",
            pdu=Error(
                seq_num=2,
                code=ErrorCode.DUPLICATE_ID.value,
                message="player_id 'player_1' is already claimed by the other player",
                rejected_action=pdu2.model_dump(),
            ),
        )
    ]


def test_player_ready_illegal_deck_too_many_cards_rejected():
    from mtgnp.protocol.errors import ErrorCode
    from mtgnp.protocol.pdus import Error

    state = GameState()
    pdu = PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(51))

    outbounds = lifecycle.handle_player_ready(state, "player_1", pdu)

    assert outbounds == [
        Outbound(
            recipient="player_1",
            pdu=Error(
                seq_num=1,
                code=ErrorCode.ILLEGAL_DECK.value,
                message="Deck contains 51 cards; maximum is 50.",
                rejected_action=pdu.model_dump(),
            ),
        )
    ]
    assert "player_1" not in state.players


def test_player_ready_illegal_deck_empty_rejected():
    from mtgnp.protocol.errors import ErrorCode
    from mtgnp.protocol.pdus import Error

    state = GameState()
    pdu = PlayerReady(seq_num=1, player_id="player_1", deck_list=[])

    outbounds = lifecycle.handle_player_ready(state, "player_1", pdu)

    assert outbounds == [
        Outbound(
            recipient="player_1",
            pdu=Error(
                seq_num=1,
                code=ErrorCode.ILLEGAL_DECK.value,
                message="Deck contains 0 cards; must be 1-50.",
                rejected_action=pdu.model_dump(),
            ),
        )
    ]


def test_player_ready_both_ready_transitions_to_game_setup():
    from mtgnp.server.state import Lifecycle

    state = GameState()
    lifecycle.handle_player_ready(state, "player_1", PlayerReady(seq_num=1, player_id="player_1", deck_list=_deck(8)))

    outbounds = lifecycle.handle_player_ready(
        state, "player_2", PlayerReady(seq_num=1, player_id="player_2", deck_list=_deck(8))
    )

    assert outbounds == [
        Outbound(
            recipient="ALL",
            pdu=_gsu(2, {"phase": "GAME_SETUP", "players_ready": 2, "waiting_for": []}),
        )
    ]
    assert state.lifecycle == Lifecycle.GAME_SETUP


def test_run_game_setup_shuffles_deals_and_flips_coin():
    import random

    from mtgnp.server.state import Lifecycle, PlayerState

    deck1 = [f"card_p1_{i:02d}" for i in range(1, 9)]
    deck2 = [f"card_p2_{i:02d}" for i in range(1, 9)]
    state = GameState(
        lifecycle=Lifecycle.GAME_SETUP,
        connections={"player_1": "player_1", "player_2": "player_2"},
        players={
            "player_1": PlayerState(player_id="player_1", life=0, library=list(deck1)),
            "player_2": PlayerState(player_id="player_2", life=0, library=list(deck2)),
        },
    )
    rng = random.Random(42)

    outbounds = lifecycle.run_game_setup(state, rng)

    # Ground truth: random.Random(42) shuffling deck1 then deck2, then one
    # rng.random() call for the coin flip (computed by actually running
    # Python's random module, not re-derived by the implementation's logic).
    shuffled1 = [
        "card_p1_04", "card_p1_05", "card_p1_07", "card_p1_08",
        "card_p1_03", "card_p1_06", "card_p1_01", "card_p1_02",
    ]
    shuffled2 = [
        "card_p2_04", "card_p2_08", "card_p2_03", "card_p2_01",
        "card_p2_05", "card_p2_07", "card_p2_06", "card_p2_02",
    ]

    common = {
        "turn": 0,
        "phase": "MULLIGAN",
        "active_player": "player_1",
        "life_totals": {"player_1": 20, "player_2": 20},
        "library_counts": {"player_1": 1, "player_2": 1},
        "battlefield": {"player_1": [], "player_2": []},
        "graveyard": {"player_1": [], "player_2": []},
        "stack": [],
    }
    assert outbounds == [
        Outbound(
            recipient="player_1",
            pdu=_gsu(1, {**common, "hand": shuffled1[:7], "hand_counts": {"player_2": 7}}),
        ),
        Outbound(
            recipient="player_2",
            pdu=_gsu(2, {**common, "hand": shuffled2[:7], "hand_counts": {"player_1": 7}}),
        ),
    ]
    assert state.lifecycle == Lifecycle.MULLIGAN
    assert state.active_player == "player_1"
    assert state.players["player_1"].life == 20
    assert state.players["player_1"].hand == shuffled1[:7]
    assert state.players["player_1"].library == shuffled1[7:]
    assert state.players["player_2"].library == shuffled2[7:]


def _setup_state(*, mulligan_count_p1: int = 0) -> GameState:
    from mtgnp.server.state import Lifecycle, PlayerState

    return GameState(
        lifecycle=Lifecycle.MULLIGAN,
        turn=0,
        active_player="player_1",
        connections={"player_1": "player_1", "player_2": "player_2"},
        players={
            "player_1": PlayerState(
                player_id="player_1", life=20,
                hand=[f"h{i}" for i in range(1, 8)], library=["l1"],
                mulligan_count=mulligan_count_p1,
            ),
            "player_2": PlayerState(
                player_id="player_2", life=20,
                hand=[f"p2h{i}" for i in range(1, 8)], library=["p2l1"],
            ),
        },
    )


def test_mulligan_choice_keep_false_redraws_and_sends_only_to_that_player():
    import random

    from mtgnp.protocol.pdus import MulliganChoice

    state = _setup_state()
    rng = random.Random(7)
    pdu = MulliganChoice(seq_num=3, keep=False, cards_to_bottom=[])

    outbounds = lifecycle.handle_mulligan_choice(state, "player_1", pdu, rng)

    new_hand = ["h6", "h7", "h2", "h4", "l1", "h3", "h1"]
    new_library = ["h5"]
    assert outbounds == [
        Outbound(
            recipient="player_1",
            pdu=_gsu(1, {
                "turn": 0,
                "phase": "MULLIGAN",
                "active_player": "player_1",
                "life_totals": {"player_1": 20, "player_2": 20},
                "hand": new_hand,
                "hand_counts": {"player_2": 7},
                "library_counts": {"player_1": 1, "player_2": 1},
                "battlefield": {"player_1": [], "player_2": []},
                "graveyard": {"player_1": [], "player_2": []},
                "stack": [],
            }),
        )
    ]
    assert state.players["player_1"].hand == new_hand
    assert state.players["player_1"].library == new_library
    assert state.players["player_1"].mulligan_count == 1


def test_mulligan_choice_keep_true_wrong_bottom_count_is_illegal_action():
    import random

    from mtgnp.protocol.errors import ErrorCode
    from mtgnp.protocol.pdus import Error, MulliganChoice

    state = _setup_state(mulligan_count_p1=1)
    rng = random.Random(7)
    pdu = MulliganChoice(seq_num=4, keep=True, cards_to_bottom=[])

    outbounds = lifecycle.handle_mulligan_choice(state, "player_1", pdu, rng)

    assert outbounds == [
        Outbound(
            recipient="player_1",
            pdu=Error(
                seq_num=1,
                code=ErrorCode.ILLEGAL_ACTION.value,
                message="cards_to_bottom must contain exactly 1 card(s) from hand; got 0",
                rejected_action=pdu.model_dump(),
            ),
        )
    ]
    assert state.players["player_1"].mulligan_count == 1


def test_mulligan_choice_keep_true_one_player_only_no_transition():
    import random

    from mtgnp.protocol.pdus import MulliganChoice
    from mtgnp.server.state import Lifecycle

    state = _setup_state(mulligan_count_p1=1)
    rng = random.Random(7)
    pdu = MulliganChoice(seq_num=4, keep=True, cards_to_bottom=["h1"])

    outbounds = lifecycle.handle_mulligan_choice(state, "player_1", pdu, rng)

    assert outbounds == []
    assert state.players["player_1"].hand == ["h2", "h3", "h4", "h5", "h6", "h7"]
    assert state.players["player_1"].library == ["l1", "h1"]
    assert state.lifecycle == Lifecycle.MULLIGAN


def test_mulligan_choice_keep_true_both_players_transitions_to_in_game():
    import random

    from mtgnp.protocol.pdus import MulliganChoice
    from mtgnp.server.state import Lifecycle

    state = _setup_state()
    rng = random.Random(7)
    lifecycle.handle_mulligan_choice(
        state, "player_1", MulliganChoice(seq_num=3, keep=True, cards_to_bottom=[]), rng
    )

    outbounds = lifecycle.handle_mulligan_choice(
        state, "player_2", MulliganChoice(seq_num=3, keep=True, cards_to_bottom=[]), rng
    )

    assert outbounds == []
    assert state.lifecycle == Lifecycle.IN_GAME
    assert state.turn == 1


def test_enter_game_over_broadcasts_and_resets_to_lobby():
    from mtgnp.protocol.pdus import GameOver
    from mtgnp.server.state import Lifecycle, PlayerState

    state = GameState(
        lifecycle=Lifecycle.IN_GAME,
        turn=5,
        active_player="player_1",
        connections={"player_1": "player_1", "player_2": "player_2"},
        players={
            "player_1": PlayerState(player_id="player_1", life=20),
            "player_2": PlayerState(player_id="player_2", life=0),
        },
    )

    outbounds = lifecycle.enter_game_over(state, winner_id="player_1", reason="LIFE_ZERO")

    assert outbounds == [
        Outbound(
            recipient="ALL",
            pdu=GameOver(seq_num=1, winner_id="player_1", loser_id="player_2", reason="LIFE_ZERO"),
        )
    ]
    assert state.lifecycle == Lifecycle.LOBBY
    assert state.players == {}
    assert state.connections == {"player_1": None, "player_2": None}
    assert state.active_player is None
    assert state.turn == 0
