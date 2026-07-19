"""Lifecycle state machine: LOBBY -> GAME_SETUP -> MULLIGAN -> IN_GAME -> GAME_OVER (RFC §6).

Handles PLAYER_READY validation (non-empty/unique player_id -> DUPLICATE_ID;
1-50 legal cards -> ILLEGAL_DECK), automatic GAME_SETUP (life=20, shuffle, deal 7,
coin flip), London Mulligan (RFC §6.4), and GAME_OVER -> return to LOBBY on the
same retained TCP connections (RFC §6.6). Pure functions over GameState returning
Outbounds; no I/O.
"""

from __future__ import annotations

# handle_player_ready(state, player_id, pdu) -> list[Outbound]     (§6.2)
# run_game_setup(state, rng) -> list[Outbound]                     (§6.3)
# handle_mulligan_choice(state, player_id, pdu) -> list[Outbound]  (§6.4)
# enter_game_over(state, winner_id, reason) -> list[Outbound]      (§6.6)
