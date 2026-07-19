"""The Stack — LIFO, server-owned (RFC §8.3-8.4).

Push spells/abilities/triggers (STACK_PUSH broadcast) and resolve the top item
when both players pass consecutively. On resolve: recheck target legality (all
illegal -> FIZZLE), else apply the effect via effects.py, broadcast STACK_RESOLVE
+ GAME_STATE_UPDATE, then grant AP priority. In the stack array, index 0 = bottom
(resolves last), last = top (resolves first).
"""

from __future__ import annotations

from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, StackItem


def push(state: GameState, item: StackItem) -> list[Outbound]:
    """STACK_PUSH. Not reachable yet: nothing produces stack items until
    CAST_SPELL/ACTIVATE_ABILITY are wired."""
    raise NotImplementedError


def resolve_top(state: GameState) -> list[Outbound]:
    """RESOLVED | FIZZLE + GAME_STATE_UPDATE (RFC §8.4). Not reachable yet: the
    stack is always empty until push() exists."""
    raise NotImplementedError
