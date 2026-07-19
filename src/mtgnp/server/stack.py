"""The Stack — LIFO, server-owned (RFC §8.3-8.4).

Push spells/abilities/triggers (STACK_PUSH broadcast) and resolve the top item
when both players pass consecutively. On resolve: recheck target legality (all
illegal -> FIZZLE), else apply the effect via effects.py, broadcast STACK_RESOLVE
+ GAME_STATE_UPDATE, then grant AP priority. In the stack array, index 0 = bottom
(resolves last), last = top (resolves first).

Imports priority/turn by module reference (`import ... as name`): priority.py
imports this module at top level, so the `from ... import` form would fail at
load time on the cycle (see priority.py's docstring).
"""

from __future__ import annotations

import mtgnp.server.priority as priority
import mtgnp.server.turn as turn
from mtgnp.protocol.pdus import StackPush, StackResolve
from mtgnp.server.effects import apply as apply_effect
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, StackItem


def push(state: GameState, item: StackItem) -> list[Outbound]:
    """STACK_PUSH (RFC §8.3). Does not grant/retain priority itself — the caller
    (e.g. a future CAST_SPELL handler) owns that, since the RFC example shows the
    caster retaining priority, not stack.py re-granting it generically."""
    state.stack.append(item)
    state.seq_num += 1
    return [
        Outbound(
            recipient="ALL",
            pdu=StackPush(
                seq_num=state.seq_num,
                stack_item_id=item.stack_item_id,
                item_type=item.item_type,
                source=item.source_id,
                targets=item.targets,
                controller=item.controller_id,
            ),
        )
    ]


def _target_legal(state: GameState, target_id: str) -> bool:
    if target_id in state.players:
        return True
    return any(
        any(permanent.id == target_id for permanent in player.battlefield)
        for player in state.players.values()
    )


def resolve_top(state: GameState) -> list[Outbound]:
    """RESOLVED | FIZZLE + GAME_STATE_UPDATE, then re-grant AP priority (RFC
    §8.4). Called from priority.handle_pass's non-empty-stack branch, so the
    returned list must include the re-grant itself."""
    item = state.stack.pop()
    legal = not item.targets or any(_target_legal(state, target) for target in item.targets)

    state.seq_num += 1
    if not legal:
        outbounds = [
            Outbound(
                recipient="ALL",
                pdu=StackResolve(
                    seq_num=state.seq_num,
                    stack_item_id=item.stack_item_id,
                    result="FIZZLE",
                    state_changes=[],
                ),
            )
        ]
    else:
        state_changes = apply_effect(state, item)
        outbounds = [
            Outbound(
                recipient="ALL",
                pdu=StackResolve(
                    seq_num=state.seq_num,
                    stack_item_id=item.stack_item_id,
                    result="RESOLVED",
                    state_changes=state_changes,
                ),
            )
        ]
        outbounds += turn.broadcast_state(state)

    outbounds += priority.grant(state, state.active_player)
    return outbounds
