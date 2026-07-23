"""TRIGGER_CHOICE_RESPONSE handler (ADR 0007): resumes a targeted ETB trigger
that `sba._drain_pending_etb` parked on `state.pending_trigger_choice`. This
is the "resume" half of the pause/resume pattern -- validate the response
against the pending choice, then push the StackItem `sba.py` deferred.
"""

from __future__ import annotations

import mtgnp.server.stack as stack
from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import Error, TriggerChoiceResponse
from mtgnp.server.engine import Outbound
from mtgnp.server.state import GameState, StackItem


def _invalid(state: GameState, connection_id: str, message: str, pdu: TriggerChoiceResponse) -> list[Outbound]:
    state.seq_num += 1
    return [
        Outbound(
            recipient=connection_id,
            pdu=Error(
                seq_num=state.seq_num,
                code=ErrorCode.TRIGGER_CHOICE_INVALID.value,
                message=message,
                rejected_action=pdu.model_dump(),
            ),
        )
    ]


def handle_trigger_choice_response(
    state: GameState, connection_id: str, pdu: TriggerChoiceResponse
) -> list[Outbound]:
    pending = state.pending_trigger_choice
    if pending is None or pdu.trigger_id != pending.trigger_id:
        return _invalid(state, connection_id, f"'{pdu.trigger_id}' is not a pending trigger choice.", pdu)

    if not pdu.accept:
        # Gravedigger has no "you may" -- the empty-graveyard no-op path is
        # already handled before TRIGGER_CHOICE is sent (ADR 0007), so a
        # mandatory trigger cannot be declined. Left in place for retry.
        return _invalid(state, connection_id, "This trigger is mandatory and cannot be declined.", pdu)

    if pdu.chosen_target not in pending.legal_targets:
        return _invalid(state, connection_id, f"'{pdu.chosen_target}' is not a legal target.", pdu)

    state.pending_trigger_choice = None
    item = StackItem(
        stack_item_id=pending.trigger_id,
        item_type="TRIGGER_ABILITY",
        source_id=pending.source_id,
        controller_id=pending.controller_id,
        targets=[pdu.chosen_target],
    )

    for controller_id, player in state.players.items():
        if any(permanent.id == pdu.chosen_target for permanent in player.battlefield):
            state.pending_targeted_trigger.append((pdu.chosen_target, controller_id))
            break

    return stack.push(state, item)
