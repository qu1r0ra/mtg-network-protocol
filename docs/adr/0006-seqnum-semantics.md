# ADR 0006 — seq_num semantics (all cases)

Status: Accepted · Date: 2026-07-19

## Context
seq_num (RFC §5.4) has more special-cases than a single rule captures, and every
one surfaces at the engine boundary. Sources also conflict, so we pin all of it in
one demo-defendable place. The engine owns the counter and all validation.

## Decision

**Server issuance — monotonic, distinct per outbound.** The server increments its
counter with each PDU it *sends* (§5.4). Each outbound gets a DISTINCT seq_num —
including the two personalized GAME_STATE_UPDATEs sent to P1 and P2. Sources
conflict here: examples.md Steps 5/6 reuse one seq_num for the pair, but RFC §9.7
(28 then 29) and the normative §5.4 text give distinct numbers. We follow the RFC:
DISTINCT. (examples.md is illustrative, not normative — see advisor R3 / ADR note
below.)

**Priority echo (client→server).** Priority-bearing action PDUs MUST echo the
seq_num of the most recent PRIORITY_GRANT / corresponding server request PDU; the
engine validates against this token and rejects mismatches with STALE_ACTION.

**Echo cases.** PONG echoes the PING's seq_num + timestamp (§10.2.25) — it does
NOT draw from the server's monotonic counter, so PONG is answered in the transport
shell, bypassing the engine stamp.

**Exemption whitelist (never validated against the priority token).**
`CONCEDE`, `PING`, `PLAYER_READY` (§5.4) — the engine's priority validation MUST
skip these or it will wrongly STALE_ACTION a CONCEDE. PLAYER_READY and PING use
client-maintained counters; CONCEDE echoes the most recent server PDU of any type.

## Consequences
All seq_num behavior lives in the engine (issuance + validation) except the PONG
echo (shell). Golden transcripts assert PDU shape/order, NOT exact server-issued
seq_nums, because of the examples.md conflict above.
