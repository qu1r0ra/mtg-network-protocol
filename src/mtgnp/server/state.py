"""Authoritative game state as plain data (ADR 0002).

All state is inspectable data structures — never buried in a call stack — so
reconnect/resync (`engine.visible_state`) and snapshotting are trivial, and the
engine stays unit-testable. GAME_STATE_UPDATE payloads are projected from here
with per-player hidden-info filtering (opponent hand -> count only, RFC §3
Visible State).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Lifecycle(str, Enum):
    LOBBY = "LOBBY"
    GAME_SETUP = "GAME_SETUP"
    MULLIGAN = "MULLIGAN"
    IN_GAME = "IN_GAME"
    GAME_OVER = "GAME_OVER"


class Phase(str, Enum):
    """Turn phases/steps in order (RFC §7.1, §10.2.4)."""

    UNTAP = "UNTAP"
    UPKEEP = "UPKEEP"
    DRAW = "DRAW"
    PRECOMBAT_MAIN = "PRECOMBAT_MAIN"
    BEGIN_COMBAT = "BEGIN_COMBAT"
    DECLARE_ATTACKERS = "DECLARE_ATTACKERS"
    DECLARE_BLOCKERS = "DECLARE_BLOCKERS"
    ASSIGN_DAMAGE_ORDER = "ASSIGN_DAMAGE_ORDER"
    FIRST_STRIKE_DAMAGE = "FIRST_STRIKE_DAMAGE"  # optional (RFC §9.6)
    COMBAT_DAMAGE = "COMBAT_DAMAGE"
    END_OF_COMBAT = "END_OF_COMBAT"
    POSTCOMBAT_MAIN = "POSTCOMBAT_MAIN"
    END_STEP = "END_STEP"
    CLEANUP = "CLEANUP"


@dataclass
class Permanent:
    """A permanent on the battlefield. Non-creatures use id/tapped only;
    creatures add damage/power/toughness/summoning_sick (RFC §10.2.2)."""

    id: str
    tapped: bool = False
    damage: int | None = None
    power: int | None = None
    toughness: int | None = None
    summoning_sick: bool | None = None


@dataclass
class PlayerState:
    player_id: str
    life: int
    library: list[str] = field(default_factory=list)
    hand: list[str] = field(default_factory=list)
    battlefield: list[Permanent] = field(default_factory=list)
    graveyard: list[str] = field(default_factory=list)
    mulligan_count: int = 0
    mulligan_kept: bool = False
    connected: bool = True


@dataclass
class StackItem:
    """LIFO stack entry (RFC §8.3). index 0 = bottom, last = top."""

    stack_item_id: str
    item_type: str          # SPELL | ABILITY | TRIGGER_ABILITY
    source_id: str
    controller_id: str
    targets: list[str] = field(default_factory=list)


@dataclass
class GameState:
    """The complete authoritative Game State (RFC §3)."""

    lifecycle: Lifecycle = Lifecycle.LOBBY
    turn: int = 0
    phase: Phase | None = None
    active_player: str | None = None
    priority_holder: str | None = None  # null during UNTAP/CLEANUP
    players: dict[str, PlayerState] = field(default_factory=dict)
    connections: dict[str, str | None] = field(
        default_factory=lambda: {"player_1": None, "player_2": None}
    )  # connection slot (assigned by transport at accept time) -> claimed player_id
    stack: list[StackItem] = field(default_factory=list)
    land_played_this_turn: bool = False
    seq_num: int = 0                    # server monotonic counter (ADR 0006)
    priority_token: int | None = None  # current PRIORITY_GRANT seq_num (STALE_ACTION)
