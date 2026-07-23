"""Unit tests for state.py's zone-lookup and cleanup primitives (Card A/B of
the pre-handoff architecture review): find_permanent, find_permanent_owner,
reset_end_of_turn."""

from __future__ import annotations

from mtgnp.server.state import (
    GameState,
    Permanent,
    PlayerState,
    find_permanent,
    find_permanent_owner,
    reset_end_of_turn,
)


def _state_with_permanent(owner_id: str, permanent: Permanent) -> GameState:
    other_id = "player_2" if owner_id == "player_1" else "player_1"
    state = GameState()
    state.players[owner_id] = PlayerState(player_id=owner_id, life=20, battlefield=[permanent])
    state.players[other_id] = PlayerState(player_id=other_id, life=20)
    return state


def test_find_permanent_returns_match_from_either_battlefield():
    permanent = Permanent(id="bear_1")
    state = _state_with_permanent("player_2", permanent)

    assert find_permanent(state, "bear_1") is permanent


def test_find_permanent_returns_none_when_absent():
    state = _state_with_permanent("player_1", Permanent(id="bear_1"))

    assert find_permanent(state, "missing") is None


def test_find_permanent_owner_returns_owner_and_permanent():
    permanent = Permanent(id="bear_1")
    state = _state_with_permanent("player_2", permanent)

    found = find_permanent_owner(state, "bear_1")

    assert found == ("player_2", permanent)


def test_find_permanent_owner_returns_none_when_absent():
    state = _state_with_permanent("player_1", Permanent(id="bear_1"))

    assert find_permanent_owner(state, "missing") is None


def test_reset_end_of_turn_full_clear():
    permanent = Permanent(
        id="bear_1",
        damage=3,
        power_bonus=2,
        toughness_bonus=2,
        temp_haste=True,
        protected_by="player_1",
    )

    reset_end_of_turn(permanent)

    assert permanent.damage == 0
    assert permanent.power_bonus == 0
    assert permanent.toughness_bonus == 0
    assert permanent.temp_haste is False
    assert permanent.protected_by is None


def test_reset_end_of_turn_damage_only_leaves_other_temp_fields():
    permanent = Permanent(
        id="bear_1",
        damage=3,
        power_bonus=2,
        toughness_bonus=2,
        temp_haste=True,
        protected_by="player_1",
    )

    reset_end_of_turn(permanent, damage_only=True)

    assert permanent.damage == 0
    assert permanent.power_bonus == 2
    assert permanent.toughness_bonus == 2
    assert permanent.temp_haste is True
    assert permanent.protected_by == "player_1"


def test_reset_end_of_turn_leaves_non_creature_damage_none():
    """Non-creature permanents (e.g. lands) have damage=None; it must stay
    None, not become 0 (turn.py's _permanent_view only surfaces damage for
    creatures, and the original inline clears preserved this guard)."""
    land = Permanent(id="forest_1")

    reset_end_of_turn(land)

    assert land.damage is None
