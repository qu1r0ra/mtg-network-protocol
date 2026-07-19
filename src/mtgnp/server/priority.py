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
"""

from __future__ import annotations

# PRIORITY_ECHO_EXEMPT = {"CONCEDE", "PING", "PLAYER_READY"}
#
# grant(state, player_id) -> list[Outbound]              # PRIORITY_GRANT, set token
# handle_pass(state, player_id, pdu) -> list[Outbound]   # advance the pass loop
# validate_token(state, pdu) -> Error | None             # STALE_ACTION check w/ exemptions
