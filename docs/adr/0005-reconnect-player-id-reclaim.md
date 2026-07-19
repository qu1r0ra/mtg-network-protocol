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
