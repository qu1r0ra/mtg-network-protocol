"""State-based actions + trigger funnel — the single post-event pipeline (RFC §8.4, §8.6).

CRITICAL (advisor R4): after EVERY game event, before ANY priority is granted:
  1. Apply state-based actions repeatedly until none remain:
       * life <= 0 -> that player loses (GAME_OVER LIFE_ZERO; simultaneous -> NAP wins)
       * creature toughness <= 0 -> graveyard
       * creature damage >= toughness -> destroyed -> graveyard
  2. Detect triggered abilities from those events and place them on the stack,
     ordered AP-first (bottom) then NAP (top); a controller with >=2 simultaneous
     triggers is asked via TRIGGER_ORDER; optional "you may" triggers via
     TRIGGER_CHOICE; targeted triggers pick a target before STACK_PUSH.
  3. Only then grant priority.

Every action handler in the engine routes through resolve() before returning, so
this ordering is enforced in exactly one place rather than scattered per phase.

This session only reaches step 1's life check: nothing yet produces permanents
with lethal damage or triggered abilities (no CAST_SPELL/combat wired), so
toughness/trigger handling is deferred to the stack.py/combat.py sessions.
"""

from __future__ import annotations

import mtgnp.server.lifecycle as lifecycle
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState


def resolve(state: GameState) -> list[Outbound]:
    """SBA loop -> trigger placement; may end the game (RFC §8.4)."""
    dead = [player_id for player_id, player in state.players.items() if player.life <= 0]
    if not dead:
        return []

    if len(dead) == len(state.players):
        winner_id = next(pid for pid in state.players if pid != state.active_player)
    else:
        loser_id = dead[0]
        winner_id = next(pid for pid in state.players if pid != loser_id)

    return lifecycle.enter_game_over(state, winner_id, "LIFE_ZERO")
