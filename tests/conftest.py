"""Shared pytest fixtures.

Provides a GameEngine factory with a SEEDED rng so shuffle + coin flip are
deterministic — every engine unit and golden-transcript test is reproducible
(Q7). Production uses system random; tests inject a fixed seed.
"""

from __future__ import annotations

import random

import pytest


@pytest.fixture
def make_engine():
    """Return a factory: make_engine(seed=0) -> GameEngine with seeded rng."""

    def _factory(seed: int = 0):
        from mtgnp.server.engine import GameEngine

        rng = random.Random(seed)
        return GameEngine(rng=rng)

    return _factory
