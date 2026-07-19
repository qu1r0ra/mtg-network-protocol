# ADR 0001 — Concurrency model: single asyncio event loop

Status: Accepted · Date: 2026-07-19

## Context
The server services two client sockets, enforces per-priority `time_limit_ms`
deadlines, and runs PING/PONG heartbeats — all mutating one authoritative game
state (RFC §4.2, §4.3).

## Decision
Use a single asyncio event loop. Each client is a coroutine; timers are asyncio
tasks. Single-threaded, so no locks and all state mutation happens in one place.

## Alternatives
- **thread-per-client** — needs locks around shared GameState; race-prone.
- **select/selectors loop** — no locks but hand-rolled buffering + timer wheel.

## Consequences
Trivial timers (`wait_for`/`call_later`); one owner of state matches the
"server is sole authority" model. Client stays simple; the async layer is the
only concurrency surface. See ADR 0002 for keeping game logic out of it.
