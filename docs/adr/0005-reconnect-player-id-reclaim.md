# ADR 0005 — Reconnect via player_id reclaim

Status: Accepted · Date: 2026-07-19

## Context
The RFC repeatedly allows a player to "reconnect within the implementation-defined
timeout" (§4.2, §6.1, §6.6) but never defines HOW a reconnecting TCP client
re-claims its slot — there is no session token and §12 explicitly punts auth. We
must fill this gap.

## Decision
On disconnect, hold the player's slot and live game state for
`RECONNECT_TIMEOUT_S`. A fresh TCP connection presenting the matching `player_id`
reattaches to the running game and receives a full GAME_STATE_UPDATE resync
(trivial via `engine.visible_state(player)`, per ADR 0002). If the timer expires
first, transition to GAME_OVER(DISCONNECT), retain the surviving player's
connection, return to LOBBY (RFC §4.2, §6.6).

## Alternatives
- No mid-game reconnect (timeout → GAME_OVER only) — simplest; valid fallback.
- Opaque session tokens — most robust but invents protocol the RFC lacks; risks
  "you added things not in the spec" at the demo.

## Consequences
Minimal mechanism that makes "reconnect" meaningful without inventing token
machinery. Spoofing is possible (a client could present another's player_id);
documented as a limitation in README §deviations, consistent with §12 (auth out
of scope). This is the one place we fill a genuine spec gap — defend it here.

## Addendum (2026-07-23): on_disconnect call contract
The frozen `GameEngine` interface (ADR 0002) has exactly four synthetic-event
methods: `on_priority_timeout`, `on_disconnect`, `on_reconnect`, `visible_state`.
There is no fifth "reconnect window expired" method, and the core never owns a
clock, so the RECONNECT_TIMEOUT_S timer itself lives entirely in the transport
shell. The engine distinguishes "just disconnected" from "window expired"
by call count, not by a separate signal: transport calls `on_disconnect`
once when the drop/heartbeat-timeout is first detected (marks the player's
`PlayerState.connected = False`, holds their slot and state, returns no
Outbounds), and — only if `on_reconnect` doesn't fire first — calls
`on_disconnect` again for the same `player_id` once its own timer elapses. A
disconnect call that finds the player already disconnected is exactly the
"window expired" signal, and the engine ends the game with reason DISCONNECT
(§4.2, §6.1). This keeps the engine stateless with respect to time while still
giving transport a single, simple call to make in both cases.

**Transport MUST cancel its RECONNECT_TIMEOUT_S timer inside its `on_reconnect`
call path**, before or as part of calling `engine.on_reconnect`. If the timer
is left running and fires after a successful reconnect, it will call
`on_disconnect` on a player the core now believes is connected again, which
the core cannot distinguish from a genuine fresh drop — it cannot see wall-clock
time, only call sequence.
