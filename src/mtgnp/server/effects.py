"""Primitive effect resolvers (ADR 0004).

The small closed vocabulary that most cards compile to. Each takes GameState + a
resolving StackItem and mutates state, returning the state_changes[] entries that
go into STACK_RESOLVE (RFC §8.4, §10.2.14). Cards declare their effect as data in
the catalog; the engine dispatches to the matching primitive here.

Primitives: DAMAGE, GAIN_LIFE, DESTROY, COUNTER, DRAW. Cards needing logic beyond
these register in custom_effects.py.
"""

from __future__ import annotations

from mtgnp.server.state import GameState, StackItem

# PRIMITIVES = {"DAMAGE": ..., "GAIN_LIFE": ..., "DESTROY": ..., "COUNTER": ..., "DRAW": ...}


def apply(state: GameState, item: StackItem) -> list[dict]:
    """Dispatch to the primitive matching `item`'s card data (ADR 0004). No card
    carries an effect spec yet — that lands with catalog wiring (issue #5) — so
    every resolution is currently a no-op. This seam exists so stack.py's
    resolution control flow (fizzle/resolve/re-grant) is real and testable ahead
    of that."""
    return []
