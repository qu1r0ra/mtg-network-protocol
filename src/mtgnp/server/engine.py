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

import json
import random
from dataclasses import dataclass
from enum import Enum
from typing import get_args

from pydantic import TypeAdapter, ValidationError

from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import AnyPDU, Error, GameStateUpdate, Ping, Pong
from mtgnp.server.state import GameState, Lifecycle as GameLifecycle


class Recipient(str, Enum):
    PLAYER_1 = "player_1"  # first-connected slot; transport resolves to a socket
    PLAYER_2 = "player_2"  # second-connected slot; transport resolves to a socket
    ALL = "ALL"  # byte-identical broadcasts only (never GAME_STATE_UPDATE)


@dataclass(frozen=True)
class Outbound:
    """A server-issued PDU addressed to one recipient, already seq-stamped and
    (for GAME_STATE_UPDATE) already visibility-filtered."""

    recipient: str  # a connection slot ("player_1"/"player_2", resolved to a
    # socket by transport at accept time), or "ALL" for a
    # byte-identical broadcast. NOT the client-chosen player_id
    # from PLAYER_READY — transport never parses PDUs, so it
    # can only route by the slot it already knows (lifecycle.py).
    pdu: object  # a pydantic PDU model instance


_PDU_ADAPTER = TypeAdapter(AnyPDU)

# The discriminator's Literal["..."] value for every PDU model in the AnyPDU
# union, e.g. {"PLAYER_READY", "CAST_SPELL", ...}. Derived from the union
# itself (not hand-maintained) so it can't drift as PDUs are added.
_KNOWN_PDU_TYPES = {
    get_args(model.model_fields["type"].annotation)[0]
    for model in get_args(get_args(AnyPDU)[0])
}

# PDU types with a wired handler as of Phase 3 (turn/priority/stack/combat/cast
# + lifecycle + TRIGGER_CHOICE_RESPONSE) plus PING (answered inline).
# ACTIVATE_ABILITY is not yet built; TRIGGER_ORDER_RESPONSE remains unwired
# (docs/agents/plan-effects-catalog-triggers.md). S->C/S->ALL-only types
# received inbound have no handler and fall through to a no-op.


class GameEngine:
    """Authoritative game state + rules. Synchronous. No I/O."""

    def __init__(self, rng=None) -> None:
        """rng is injected for deterministic shuffle + coin flip (seedable in
        tests, defaults to system random in production)."""
        self.state = GameState()
        self.rng = rng if rng is not None else random.Random()

    # --- primary seam (bytes in, Outbounds out) ---
    def handle(self, player_id: str, payload: bytes) -> list[Outbound]:
        """Validate+parse `payload`, dispatch by current (state, phase), return
        server-issued Outbounds. All ERRORs originate here.

        `player_id` here is the connection slot ("player_1"/"player_2")
        assigned by transport at accept time, NOT the client-chosen player_id
        claim inside PLAYER_READY (see Recipient docstring) -- every module
        handler already names this parameter `connection_id` for that reason.
        """
        connection_id = player_id

        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._reject(
                connection_id,
                ErrorCode.INVALID_JSON,
                "Payload is not valid JSON.",
                None,
            )

        try:
            pdu = _PDU_ADAPTER.validate_python(raw)
        except ValidationError:
            # `type` unrecognized -> UNKNOWN_TYPE; `type` known but some other
            # field fails validation -> INVALID_JSON (pdus.py's own docstring:
            # "Field-level validation ... parse failures map to INVALID_JSON").
            if not isinstance(raw, dict) or raw.get("type") not in _KNOWN_PDU_TYPES:
                return self._reject(
                    connection_id,
                    ErrorCode.UNKNOWN_TYPE,
                    "`type` matches no known PDU.",
                    raw if isinstance(raw, dict) else None,
                )
            return self._reject(
                connection_id,
                ErrorCode.INVALID_JSON,
                "PDU failed field validation.",
                raw,
            )

        return self._dispatch(connection_id, pdu)

    def _reject(
        self, connection_id: str, code: ErrorCode, message: str, rejected: dict | None
    ) -> list[Outbound]:
        self.state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=self.state.seq_num,
                    code=code.value,
                    message=message,
                    rejected_action=rejected,
                ),
            )
        ]

    def _dispatch(self, connection_id: str, pdu) -> list[Outbound]:
        # Local imports: lifecycle/priority/turn/combat import Outbound from
        # this module at their top level, so importing them at module scope
        # here would be a load-time cycle (same pattern turn.py/priority.py
        # already use to reach each other).
        import mtgnp.server.cast as cast
        import mtgnp.server.combat as combat
        import mtgnp.server.lifecycle as lifecycle
        import mtgnp.server.priority as priority
        import mtgnp.server.triggers as triggers
        import mtgnp.server.turn as turn

        state = self.state
        pdu_type = pdu.type

        if pdu_type == "PLAYER_READY":
            outbounds = lifecycle.handle_player_ready(state, connection_id, pdu)
            if state.lifecycle == GameLifecycle.GAME_SETUP:
                outbounds += lifecycle.run_game_setup(state, self.rng)
            return outbounds

        if pdu_type == "MULLIGAN_CHOICE":
            outbounds = lifecycle.handle_mulligan_choice(
                state, connection_id, pdu, self.rng
            )
            if state.lifecycle == GameLifecycle.IN_GAME and state.phase is None:
                outbounds += turn.begin_turn(state, "MULLIGAN")
            return outbounds

        if pdu_type == "PRIORITY_PASS":
            return priority.handle_pass(state, connection_id, pdu)

        if pdu_type == "CAST_SPELL":
            return cast.handle_cast_spell(state, connection_id, pdu)

        if pdu_type == "PLAY_LAND":
            return turn.handle_play_land(state, connection_id, pdu)

        if pdu_type == "DISCARD":
            return turn.handle_discard(state, connection_id, pdu)

        if pdu_type == "DECLARE_ATTACKERS":
            return combat.handle_declare_attackers(state, connection_id, pdu)

        if pdu_type == "DECLARE_BLOCKERS":
            return combat.handle_declare_blockers(state, connection_id, pdu)

        if pdu_type == "ASSIGN_DAMAGE_ORDER":
            return combat.handle_assign_damage_order(state, connection_id, pdu)

        if pdu_type == "TRIGGER_CHOICE_RESPONSE":
            return triggers.handle_trigger_choice_response(state, connection_id, pdu)

        if pdu_type == "CONCEDE":
            conceding_player = state.connections.get(connection_id)
            winner_id = next(pid for pid in state.players if pid != conceding_player)
            return lifecycle.enter_game_over(state, winner_id, "CONCEDE")

        if pdu_type == "PING":
            assert isinstance(pdu, Ping)
            return [
                Outbound(
                    recipient=connection_id,
                    pdu=Pong(seq_num=pdu.seq_num, timestamp=pdu.timestamp),
                )
            ]

        # No handler wired yet for this PDU type (Phase 2/3 territory, or an
        # S->C/S->ALL-only type received inbound) -- discard, no state change.
        return []

    # --- synthetic events from the shell (RFC §4.2, §4.3, §6.1) ---
    def on_priority_timeout(self, player_id: str) -> list[Outbound]:
        """Priority holder missed time_limit_ms => GAME_OVER(DISCONNECT) (§4.2)."""
        import mtgnp.server.lifecycle as lifecycle

        winner_id = next(pid for pid in self.state.players if pid != player_id)
        return lifecycle.enter_game_over(self.state, winner_id, "DISCONNECT")

    def on_disconnect(self, player_id: str) -> list[Outbound]:
        """TCP drop / heartbeat timeout; start reconnect timer or GAME_OVER (§6.1,
        ADR 0005).

        Call contract for the transport shell (which owns the actual
        RECONNECT_TIMEOUT_S timer -- the core never touches a clock, ADR 0002):
        call this ONCE when the drop/timeout is first detected (marks the player
        disconnected, holds their slot and state, no game-over yet); if
        `on_reconnect` doesn't fire before the timer elapses, call this AGAIN for
        the same player_id -- finding them already disconnected is how the core
        recognizes the window has expired, and it ends the game with reason
        DISCONNECT. This avoids adding a fifth synthetic-event method for
        "reconnect window expired" while keeping all timing in the shell.
        """
        import mtgnp.server.lifecycle as lifecycle

        player = self.state.players[player_id]
        if not player.connected:
            winner_id = next(pid for pid in self.state.players if pid != player_id)
            return lifecycle.enter_game_over(self.state, winner_id, "DISCONNECT")
        player.connected = False
        return []

    def on_reconnect(self, player_id: str) -> list[Outbound]:
        """player_id reclaim within the window => full state resync (ADR 0005)."""
        self.state.players[player_id].connected = True
        slot = next(
            s for s, claimed in self.state.connections.items() if claimed == player_id
        )
        self.state.seq_num += 1
        return [
            Outbound(
                recipient=slot,
                pdu=GameStateUpdate(
                    seq_num=self.state.seq_num, state=self.visible_state(player_id)
                ),
            )
        ]

    # --- shell queries ---
    def visible_state(self, player_id: str) -> dict:
        """Personalized GAME_STATE_UPDATE payload for one player (resync/render).
        Delegates to the same per-phase view builders lifecycle.py/turn.py use
        for ordinary broadcasts, so resync can never drift from normal play
        (ADR 0002, ADR 0005)."""
        import mtgnp.server.lifecycle as lifecycle
        import mtgnp.server.turn as turn

        state = self.state
        if state.lifecycle in (GameLifecycle.IN_GAME, GameLifecycle.GAME_OVER):
            return turn._in_game_view(state, player_id)
        if state.lifecycle == GameLifecycle.MULLIGAN:
            return lifecycle._mulligan_phase_view(state, player_id)

        # LOBBY / GAME_SETUP: no per-player game state yet, only lobby metadata.
        players_ready = sum(
            1 for claimed in state.connections.values() if claimed is not None
        )
        waiting_for = [
            claimed if claimed is not None else slot
            for slot, claimed in state.connections.items()
            if claimed != player_id
        ]
        return {
            "phase": state.lifecycle.value,
            "players_ready": players_ready,
            "waiting_for": waiting_for,
        }
