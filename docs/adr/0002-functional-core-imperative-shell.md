# ADR 0002 — Functional core + imperative shell

Status: Accepted · Date: 2026-07-19

## Context
The engine has nested state machines (lifecycle ⊃ 14-phase turn ⊃ priority window
⊃ combat sub-FSM ⊃ stack). It must also support reconnect/resync (RFC §6.1) and
"any-time" interrupts (CONCEDE, priority timeout, disconnect). A linear
`await`-script buries state in a call stack that cannot be snapshotted.

## Decision
Split the server in two:
- **Engine core (synchronous):** `GameEngine.handle(player_id, payload: bytes)
  -> list[Outbound]`. All state is plain data. No sockets, no `await`. Explicit
  phase/step handling with reusable PriorityWindow and Stack components.
- **Transport shell (asyncio):** sockets, framing, timers, reconnect, verbose
  logging. Feeds bytes + synthetic events into the core; writes returned
  Outbounds. Never inspects game state.

`handle` takes RAW BYTES (not a parsed PDU) so INVALID_JSON / UNKNOWN_TYPE and
ALL error emission live in the core with the seq_num counter (see ADR 0006).

## Consequences
Reconnect/snapshot is free (`visible_state(player)`); interrupts are uniform
synthetic events; the entire RFC is testable without networking; verbose mode is
one boundary. Cost: an `Outbound` type and discipline to keep `await` out of the
core.
