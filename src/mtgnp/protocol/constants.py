"""Wire-level and rule constants (RFC 0001).

Single source of truth for numeric limits and timeouts shared by server and
client. Nothing here is a decision the game logic makes at runtime.
"""

from __future__ import annotations

from typing import Final

# --- Transport (RFC §5) ---
DEFAULT_PORT: Final[int] = 4444
"""Default server TCP port (RFC §5.1)."""

LENGTH_PREFIX_BYTES: Final[int] = 4
"""4-byte big-endian unsigned length prefix on every frame (RFC §5.2)."""

MAX_PDU_BYTES: Final[int] = 65_535
"""A PDU MUST NOT exceed this many bytes (RFC §5.2)."""

MAX_PLAYERS: Final[int] = 2
"""Exactly two clients per game (RFC §5.1); further connects refused."""

# --- Rules (RFC §6) ---
STARTING_LIFE: Final[int] = 20
OPENING_HAND_SIZE: Final[int] = 7
MAX_HAND_SIZE: Final[int] = 7  # cleanup discard threshold (RFC §7.8)
MIN_DECK_SIZE: Final[int] = 1
MAX_DECK_SIZE: Final[int] = 50

# --- Timeouts (implementation-defined; RFC §4.2, §4.3, §12) ---
DEFAULT_PRIORITY_TIME_LIMIT_MS: Final[int] = 60_000
"""Advertised in each PRIORITY_GRANT; miss => GAME_OVER(DISCONNECT) (RFC §4.2)."""

HEARTBEAT_INTERVAL_S: Final[float] = 30.0
"""Client PING cadence (RFC §4.3, RECOMMENDED)."""

HEARTBEAT_TIMEOUT_S: Final[float] = 10.0
"""No PONG within this window => client disconnects (RFC §4.3, RECOMMENDED)."""

RECONNECT_TIMEOUT_S: Final[float] = 30.0
"""Slot held for a dropped player_id this long before GAME_OVER (ADR 0005)."""
