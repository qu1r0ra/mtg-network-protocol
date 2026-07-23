"""Priority window — reusable across every step that grants priority (RFC §8.1-8.2).

The AP receives priority first; a pass hands it to the opponent. Both pass with a
non-empty stack -> resolve top item (stack.py) then AP regains priority; both pass
with an empty stack -> step advances (turn.py). Issues PRIORITY_GRANT stamped with
a fresh seq_num which becomes the STALE_ACTION token.

seq_num validation (ADR 0006): an action PDU's echoed seq_num MUST equal the
current priority token, EXCEPT for the exemption whitelist — CONCEDE, PING,
PLAYER_READY are never validated against the token (RFC §5.4). Mismatch on a
non-exempt PDU -> ERROR STALE_ACTION and the current PRIORITY_GRANT is re-issued
with the same seq_num (RFC §11).

Imports turn/stack by module reference (`import ... as name`), not `from ...
import name` — turn.py imports this module too, and the `from` form would fail
at load time on the cycle.
"""

from __future__ import annotations

import mtgnp.server.sba as sba
import mtgnp.server.stack as stack
import mtgnp.server.turn as turn
from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import Error, PriorityGrant
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, Lifecycle

PRIORITY_ECHO_EXEMPT = {"CONCEDE", "PING", "PLAYER_READY"}
DEFAULT_TIME_LIMIT_MS = 60000


def _slot_for(state: GameState, player_id: str) -> str:
    return next(
        slot for slot, claimed in state.connections.items() if claimed == player_id
    )


def _other(state: GameState, player_id: str) -> str:
    return next(pid for pid in state.players if pid != player_id)


def grant(state: GameState, player_id: str) -> list[Outbound]:
    """Route through SBA (RFC §8.4, advisor R4), then open a priority window for
    `player_id`. If SBA ended the game, priority is never granted."""
    outbounds = sba.resolve(state)
    if state.lifecycle != Lifecycle.IN_GAME:
        # sba.resolve ended the game (enter_game_over resets straight to LOBBY,
        # RFC §6.6 — there is no separate GAME_OVER lifecycle value to check)
        return outbounds

    state.priority_holder = player_id
    state.last_passer = None
    state.seq_num += 1
    state.priority_token = state.seq_num
    outbounds.append(
        Outbound(
            recipient=_slot_for(state, player_id),
            pdu=PriorityGrant(
                seq_num=state.seq_num,
                player_id=player_id,
                time_limit_ms=DEFAULT_TIME_LIMIT_MS,
            ),
        )
    )
    return outbounds


def validate_priority(state: GameState, connection_id: str, pdu) -> list[Outbound]:
    """NOT_YOUR_PRIORITY / STALE_ACTION gate shared by every action PDU (RFC
    §5.4, §8.5). Exempt types skip both checks entirely. Returns [] when the
    action may proceed."""
    if pdu.type in PRIORITY_ECHO_EXEMPT:
        return []

    player_id = state.connections[connection_id]
    if player_id != state.priority_holder:
        state.seq_num += 1
        return [
            Outbound(
                recipient=connection_id,
                pdu=Error(
                    seq_num=state.seq_num,
                    code=ErrorCode.NOT_YOUR_PRIORITY.value,
                    message=f"'{player_id}' does not hold priority.",
                    rejected_action=pdu.model_dump(),
                ),
            )
        ]

    if pdu.seq_num != state.priority_token:
        state.seq_num += 1
        error = Outbound(
            recipient=connection_id,
            pdu=Error(
                seq_num=state.seq_num,
                code=ErrorCode.STALE_ACTION.value,
                message=(
                    f"Priority token mismatch. Expected seq_num {state.priority_token}, "
                    f"got {pdu.seq_num}."
                ),
                rejected_action=pdu.model_dump(),
            ),
        )
        regrant = Outbound(
            recipient=connection_id,
            pdu=PriorityGrant(
                seq_num=state.priority_token,
                player_id=player_id,
                time_limit_ms=DEFAULT_TIME_LIMIT_MS,
            ),
        )
        return [error, regrant]

    return []


def handle_pass(state: GameState, connection_id: str, pdu) -> list[Outbound]:
    """RFC §8.1 rules 4-6: hand priority to the opponent, or (both passed
    consecutively) resolve the stack top or advance the step."""
    errors = validate_priority(state, connection_id, pdu)
    if errors:
        return errors

    passer = state.priority_holder
    other_player = _other(state, passer)

    if state.last_passer == other_player:
        # both players have now passed consecutively (RFC §8.1 rules 5-6)
        state.last_passer = None
        if state.stack:
            return stack.resolve_top(state)
        import mtgnp.server.combat as combat

        if state.phase in combat.COMBAT_PHASES:
            return combat.advance_step(state)
        return turn.advance(state)

    outbounds = grant(state, other_player)  # resets last_passer; overwritten below
    state.last_passer = passer
    return outbounds
