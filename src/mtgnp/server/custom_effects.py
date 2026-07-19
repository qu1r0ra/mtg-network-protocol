"""Code escape hatch for cards that don't reduce to primitives (ADR 0004).

A registry keyed by card base_id for genuinely novel mechanics (e.g. Gray Merchant
of Asphodel — life drain by devotion to black, an optional "you may" trigger). The
engine checks this registry before falling back to the data-driven primitives, so
the common case stays pure data and only real complexity lands here.
"""

from __future__ import annotations

# CUSTOM: dict[str, Callable] = {}
#
# def register(base_id): ...   # decorator
# def get(base_id): ...        # -> handler | None
