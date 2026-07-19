"""Controller: turn human intent into action PDUs.

Prompts the player for the choice the server is currently asking for (cast / pass
/ play land / attack / block / mulligan / discard / trigger order/choice) and
builds the corresponding PDU, echoing the correct seq_num per RFC §5.4. A headless
variant reads actions from a script file instead of prompting — same interface —
enabling automated interop and E2E tests (used by tests/transport).
"""

from __future__ import annotations

# class InputController(Protocol):
#     async def next_action(self, visible_state, prompt) -> pdu: ...
#
# class CLIController(InputController): ...       # interactive prompt
# class ScriptController(InputController): ...    # reads --script FILE
