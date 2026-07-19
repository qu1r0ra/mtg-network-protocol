"""The Stack — LIFO, server-owned (RFC §8.3-8.4).

Push spells/abilities/triggers (STACK_PUSH broadcast) and resolve the top item
when both players pass consecutively. On resolve: recheck target legality (all
illegal -> FIZZLE), else apply the effect via effects.py, broadcast STACK_RESOLVE
+ GAME_STATE_UPDATE, then grant AP priority. In the stack array, index 0 = bottom
(resolves last), last = top (resolves first).
"""

from __future__ import annotations

# push(state, item) -> list[Outbound]        # STACK_PUSH
# resolve_top(state) -> list[Outbound]        # RESOLVED | FIZZLE + GAME_STATE_UPDATE
