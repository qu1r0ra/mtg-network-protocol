"""GameEngine — the authoritative functional core (ADR 0002).

The engine is a synchronous state machine. It never touches a socket and never
awaits. The async shell (transport.py) drives it by feeding raw payload bytes and
synthetic events, and writes back the Outbounds it returns.

Load-bearing interface (see advisor refinements):

    handle(player_id, payload: bytes) -> list[Outbound]

`handle` takes RAW BYTES, not a parsed PDU, on purpose: INVALID_JSON and
UNKNOWN_TYPE only exist pre-parse, and ALL ERROR emission must live in the one
place that owns the seq_num counter. Internally: parse(bytes) -> PDU | Error,
then dispatch(PDU). Phase handlers are model-typed; only this public seam sees
bytes.

The engine OWNS (ADR 0006, Q8):
  * the server's monotonic seq_num counter (stamps every server-issued Outbound,
    DISTINCT per outbound — including the two personalized GAME_STATE_UPDATEs);
  * the current priority-grant seq_num (the STALE_ACTION token) and the
    priority-echo EXEMPTION whitelist (CONCEDE, PING, PLAYER_READY are never
    validated against the token);
  * hidden-information filtering — it produces already-personalized payloads so
    the shell never inspects game state.

Outbound = (recipients, pdu). recipient ALL is legal ONLY for byte-identical
broadcasts; GAME_STATE_UPDATE is ALWAYS emitted as N per-recipient Outbounds
with per-recipient payloads (advisor R1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Recipient(str, Enum):
    PLAYER_1 = "player_1"  # resolved to actual player_ids at runtime
    PLAYER_2 = "player_2"
    ALL = "ALL"            # byte-identical broadcasts only (never GAME_STATE_UPDATE)


@dataclass(frozen=True)
class Outbound:
    """A server-issued PDU addressed to one recipient, already seq-stamped and
    (for GAME_STATE_UPDATE) already visibility-filtered."""

    recipient: str  # a concrete player_id, or "ALL"
    pdu: object     # a pydantic PDU model instance


class GameEngine:
    """Authoritative game state + rules. Synchronous. No I/O."""

    def __init__(self, rng=None) -> None:
        """rng is injected for deterministic shuffle + coin flip (seedable in
        tests, defaults to system random in production)."""
        raise NotImplementedError

    # --- primary seam (bytes in, Outbounds out) ---
    def handle(self, player_id: str, payload: bytes) -> list[Outbound]:
        """Validate+parse `payload`, dispatch by current (state, phase), return
        server-issued Outbounds. All ERRORs originate here."""
        raise NotImplementedError

    # --- synthetic events from the shell (RFC §4.2, §4.3, §6.1) ---
    def on_priority_timeout(self, player_id: str) -> list[Outbound]:
        """Priority holder missed time_limit_ms => GAME_OVER(DISCONNECT) (§4.2)."""
        raise NotImplementedError

    def on_disconnect(self, player_id: str) -> list[Outbound]:
        """TCP drop / heartbeat timeout; start reconnect timer or GAME_OVER (§6.1)."""
        raise NotImplementedError

    def on_reconnect(self, player_id: str) -> list[Outbound]:
        """player_id reclaim within the window => full state resync (ADR 0005)."""
        raise NotImplementedError

    # --- shell queries ---
    def visible_state(self, player_id: str) -> object:
        """Personalized GAME_STATE_UPDATE payload for one player (resync/render)."""
        raise NotImplementedError
