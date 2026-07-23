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
from mtgnp.protocol.catalog import base_id
from mtgnp.protocol.pdus import StackPush, StackResolve
from mtgnp.server import custom_effects
from mtgnp.server.effects import apply as apply_effect
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, StackItem, find_permanent


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


def _target_legal(state: GameState, target_id: str, allow_graveyard: bool, caster_id: str) -> bool:
    """Recheck at resolution time (RFC §8.4): the target must still be a
    player or a battlefield permanent. `allow_graveyard` additionally
    permits graveyard membership -- scoped to targeted custom triggers that
    target the graveyard by design (Gravedigger, ADR 0007), NOT to ordinary
    SPELL/ABILITY targeting (a dead creature must FIZZLE Lightning Bolt, not
    silently RESOLVE against a corpse)."""
    if target_id in state.players:
        return True
    permanent = find_permanent(state, target_id)
    if permanent is not None:
        # ADR 0012: a permanent protected by a Vines-style effect can only be
        # targeted by the player who cast the protecting spell.
        return permanent.protected_by is None or permanent.protected_by == caster_id
    # Unscoped by design (unlike allow_graveyard below): a resolving item's
    # target only ever holds another stack_item_id when it's a COUNTER spell
    # (cast.py only accepts a stack-id target for target_type == "spell"),
    # so no other resolving item can collide with this clause.
    if any(item.stack_item_id == target_id for item in state.stack):
        return True
    if not allow_graveyard:
        return False
    return any(target_id in player.graveyard for player in state.players.values())


def resolve_top(state: GameState) -> list[Outbound]:
    """RESOLVED | FIZZLE + GAME_STATE_UPDATE, then re-grant AP priority (RFC
    §8.4). Called from priority.handle_pass's non-empty-stack branch, so the
    returned list must include the re-grant itself."""
    item = state.stack.pop()
    spec = custom_effects.get(base_id(item.source_id)) if item.item_type != "SPELL" else None
    allow_graveyard = spec is not None and spec.requires_target
    legal = not item.targets or any(
        _target_legal(state, target, allow_graveyard, item.controller_id) for target in item.targets
    )

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
