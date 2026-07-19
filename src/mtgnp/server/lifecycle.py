"""Lifecycle state machine: LOBBY -> GAME_SETUP -> MULLIGAN -> IN_GAME -> GAME_OVER (RFC §6).

Handles PLAYER_READY validation (non-empty/unique player_id -> DUPLICATE_ID;
1-50 legal cards -> ILLEGAL_DECK), automatic GAME_SETUP (life=20, shuffle, deal 7,
coin flip), London Mulligan (RFC §6.4), and GAME_OVER -> return to LOBBY on the
same retained TCP connections (RFC §6.6). Pure functions over GameState returning
Outbounds; no I/O.
"""

from __future__ import annotations

from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import Error, GameOver, GameStateUpdate, PlayerReady
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, Lifecycle, PlayerState


def handle_player_ready(
    state: GameState, connection_id: str, pdu: PlayerReady
) -> list[Outbound]:
    """§6.2. `connection_id` is the stable slot ("player_1"/"player_2") assigned
    by transport at accept time — distinct from `pdu.player_id`, the client's
    freely-chosen claim string."""
    deck_size = len(pdu.deck_list)
    if deck_size == 0:
        message = "Deck contains 0 cards; must be 1-50."
    elif deck_size > 50:
        message = f"Deck contains {deck_size} cards; maximum is 50."
    else:
        message = None

    if message is not None:
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.ILLEGAL_DECK.value,
                    message=message,
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    other_claimed = next(
        (claimed for slot, claimed in state.connections.items() if slot != connection_id),
        None,
    )
    if other_claimed == pdu.player_id:
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.DUPLICATE_ID.value,
                    message=f"player_id '{pdu.player_id}' is already claimed by the other player",
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    prior_claim = state.connections[connection_id]
    if prior_claim is not None and prior_claim != pdu.player_id:
        del state.players[prior_claim]

    state.connections[connection_id] = pdu.player_id
    state.players[pdu.player_id] = PlayerState(
        player_id=pdu.player_id, life=0, library=list(pdu.deck_list)
    )

    players_ready = sum(1 for claimed in state.connections.values() if claimed is not None)

    if players_ready == len(state.connections):
        state.lifecycle = Lifecycle.GAME_SETUP
        state.seq_num += 1
        return [
            Outbound(
                recipient="ALL",
                pdu=GameStateUpdate(
                    seq_num=state.seq_num,
                    state={
                        "phase": "GAME_SETUP",
                        "players_ready": players_ready,
                        "waiting_for": [],
                    },
                ),
            )
        ]

    waiting_for = [
        claimed if claimed is not None else slot
        for slot, claimed in state.connections.items()
        if slot != connection_id
    ]
    state.seq_num += 1
    outbound = Outbound(
        recipient=connection_id,
        pdu=GameStateUpdate(
            seq_num=state.seq_num,
            state={
                "phase": "LOBBY",
                "players_ready": players_ready,
                "waiting_for": waiting_for,
            },
        ),
    )
    return [outbound]


def _mulligan_phase_view(state: GameState, player_id: str) -> dict:
    """Personalized MULLIGAN-phase GAME_STATE_UPDATE payload (own hand visible,
    opponent hand collapsed to a count — RFC §3 Visible State)."""
    player_ids = [claimed for claimed in state.connections.values() if claimed is not None]
    other_id = next(pid for pid in player_ids if pid != player_id)
    return {
        "turn": state.turn,
        "phase": "MULLIGAN",
        "active_player": state.active_player,
        "life_totals": {pid: state.players[pid].life for pid in player_ids},
        "hand": state.players[player_id].hand,
        "hand_counts": {other_id: len(state.players[other_id].hand)},
        "library_counts": {pid: len(state.players[pid].library) for pid in player_ids},
        "battlefield": {pid: [] for pid in player_ids},
        "graveyard": {pid: [] for pid in player_ids},
        "stack": [],
    }


def run_game_setup(state: GameState, rng) -> list[Outbound]:
    """§6.3. Automatic: life=20, shuffle, deal 7, coin flip. Slot order
    (connections dict insertion order) is fixed as player_1 then player_2 for
    shuffle/coin-flip determinism given a seeded rng."""
    slots = list(state.connections.items())
    player_ids = [claimed for _, claimed in slots]

    for player_id in player_ids:
        player = state.players[player_id]
        player.life = 20
        rng.shuffle(player.library)
        player.hand = player.library[:7]
        player.library = player.library[7:]

    state.active_player = player_ids[0] if rng.random() < 0.5 else player_ids[1]
    state.lifecycle = Lifecycle.MULLIGAN
    state.turn = 0

    outbounds = []
    for slot, player_id in slots:
        state.seq_num += 1
        outbounds.append(
            Outbound(
                recipient=slot,
                pdu=GameStateUpdate(
                    seq_num=state.seq_num,
                    state=_mulligan_phase_view(state, player_id),
                ),
            )
        )
    return outbounds


def handle_mulligan_choice(
    state: GameState, connection_id: str, pdu, rng
) -> list[Outbound]:
    """§6.4. London Mulligan: keep=false redraws (mulligan_count += 1) and
    notifies only that player; keep=true validates cards_to_bottom against
    mulligan_count, bottoms those cards, and — once both players have kept —
    transitions to IN_GAME (turn=1). Beginning the first turn itself is
    turn.py's job, wired in by the caller once this returns."""
    player_id = state.connections[connection_id]
    player = state.players[player_id]

    if not pdu.keep:
        player.library.extend(player.hand)
        rng.shuffle(player.library)
        player.hand = player.library[:7]
        player.library = player.library[7:]
        player.mulligan_count += 1

        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=GameStateUpdate(
                    seq_num=state.seq_num,
                    state=_mulligan_phase_view(state, player_id),
                ),
            )
        ]

    if len(pdu.cards_to_bottom) != player.mulligan_count or not set(
        pdu.cards_to_bottom
    ) <= set(player.hand):
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.ILLEGAL_ACTION.value,
                    message=(
                        f"cards_to_bottom must contain exactly {player.mulligan_count} "
                        f"card(s) from hand; got {len(pdu.cards_to_bottom)}"
                    ),
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    for card in pdu.cards_to_bottom:
        player.hand.remove(card)
        player.library.append(card)
    player.mulligan_kept = True

    if all(state.players[pid].mulligan_kept for pid in state.players):
        state.lifecycle = Lifecycle.IN_GAME
        state.turn = 1

    return []


def enter_game_over(state: GameState, winner_id: str, reason: str) -> list[Outbound]:
    """§6.6. Broadcast GAME_OVER, then return to LOBBY on the same retained
    connections. Player IDs reset (§6.2: "reused across games")."""
    loser_id = next(pid for pid in state.players if pid != winner_id)

    state.seq_num += 1
    outbound = Outbound(
        recipient="ALL",
        pdu=GameOver(
            seq_num=state.seq_num,
            winner_id=winner_id,
            loser_id=loser_id,
            reason=reason,
        ),
    )

    state.lifecycle = Lifecycle.LOBBY
    state.turn = 0
    state.phase = None
    state.active_player = None
    state.priority_holder = None
    state.players = {}
    state.connections = {slot: None for slot in state.connections}
    state.stack = []

    return [outbound]
