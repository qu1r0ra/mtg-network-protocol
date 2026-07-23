"""ADR 0007 pause/resume, both halves: `pause_for_choice` parks a targeted ETB
trigger on `state.pending_trigger_choice` and emits TRIGGER_CHOICE (called
from sba.py's drain, since that's where the ETB event that might need a
choice is detected); `handle_trigger_choice_response` is the TRIGGER_CHOICE_
RESPONSE PDU handler that resumes it -- validate the response against the
pending choice, then push the StackItem the pause half deferred. Card G of
the pre-handoff architecture review: previously the pause half lived inline
in sba.py with only the shared PendingTriggerChoice dataclass and convention
tying it to this file's resume half; co-locating both here keeps one ADR's
protocol in one module, with sba.py calling in rather than reimplementing it.
"""

from __future__ import annotations

import mtgnp.server.stack as stack
from mtgnp.protocol.catalog import base_id
from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import Error, TriggerChoice, TriggerChoiceResponse
from mtgnp.server.engine import Outbound
from mtgnp.server.state import (
    GameState,
    PendingTriggerChoice,
    StackItem,
    find_permanent_owner,
)


def _slot_for(state: GameState, player_id: str) -> str:
    return next(
        slot for slot, claimed in state.connections.items() if claimed == player_id
    )


def pause_for_choice(
    state: GameState, source_id: str, controller_id: str, legal_targets: list[str]
) -> list[Outbound]:
    """Pause half (ADR 0007): park a targeted ETB trigger on
    `state.pending_trigger_choice` and emit TRIGGER_CHOICE instead of pushing
    it immediately. Caller (sba.py's `_drain_pending_etb`) has already
    confirmed `legal_targets` is non-empty -- RFC §8.6.4's empty-targets
    silent discard happens before this is called, not here."""
    state.seq_num += 1
    trigger_id = f"{source_id}_trigger_{state.seq_num}"
    state.pending_trigger_choice = PendingTriggerChoice(
        trigger_id=trigger_id,
        source_id=source_id,
        controller_id=controller_id,
        legal_targets=legal_targets,
    )
    return [
        Outbound(
            recipient=_slot_for(state, controller_id),
            pdu=TriggerChoice(
                seq_num=state.seq_num,
                trigger_id=trigger_id,
                source_id=source_id,
                effect_summary=base_id(source_id),
                requires_target=True,
                legal_targets=legal_targets,
            ),
        )
    ]


def _invalid(
    state: GameState, connection_id: str, message: str, pdu: TriggerChoiceResponse
) -> list[Outbound]:
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
        return _invalid(
            state,
            connection_id,
            f"'{pdu.trigger_id}' is not a pending trigger choice.",
            pdu,
        )

    if not pdu.accept:
        # Gravedigger has no "you may" -- the empty-graveyard no-op path is
        # already handled before TRIGGER_CHOICE is sent (ADR 0007), so a
        # mandatory trigger cannot be declined. Left in place for retry.
        return _invalid(
            state,
            connection_id,
            "This trigger is mandatory and cannot be declined.",
            pdu,
        )

    if pdu.chosen_target not in pending.legal_targets:
        return _invalid(
            state, connection_id, f"'{pdu.chosen_target}' is not a legal target.", pdu
        )

    state.pending_trigger_choice = None
    item = StackItem(
        stack_item_id=pending.trigger_id,
        item_type="TRIGGER_ABILITY",
        source_id=pending.source_id,
        controller_id=pending.controller_id,
        targets=[pdu.chosen_target],
    )

    found = find_permanent_owner(state, pdu.chosen_target)
    if found is not None:
        controller_id, _ = found
        state.pending_targeted_trigger.append((pdu.chosen_target, controller_id))

    return stack.push(state, item)
