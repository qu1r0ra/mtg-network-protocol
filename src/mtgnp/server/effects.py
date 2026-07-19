"""Primitive effect resolvers (ADR 0004).

The small closed vocabulary that most cards compile to. Each takes GameState + a
resolving StackItem and mutates state, returning the state_changes[] entries that
go into STACK_RESOLVE (RFC §8.4, §10.2.14). Cards declare their effect as data in
the catalog; the engine dispatches to the matching primitive here.

Primitives: DAMAGE, GAIN_LIFE, DESTROY, COUNTER, DRAW. Cards needing logic beyond
these register in custom_effects.py.
"""

from __future__ import annotations

# PRIMITIVES = {"DAMAGE": ..., "GAIN_LIFE": ..., "DESTROY": ..., "COUNTER": ..., "DRAW": ...}
# apply(state, item, effect_spec) -> list[state_change]
