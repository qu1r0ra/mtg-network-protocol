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
"""

from __future__ import annotations

# resolve(state) -> list[Outbound]   # SBA loop -> trigger placement; may end game
