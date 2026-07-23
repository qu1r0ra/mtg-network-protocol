# CONTEXT — MTGNP domain glossary

Ubiquitous language for the MTGNP implementation. Terms mirror RFC 0001 §3; use
these exact names in code and PDUs. See `docs/references/rfc.md` for the normative
spec and `docs/adr/` for architectural decisions.

## Roles & turn
- **Active Player (AP)** — the player whose turn it is.
- **Non-Active Player (NAP)** — the other player.
- **Turn** — a fixed sequence of phases/steps (RFC §7). Turn counter starts at 1
  when IN_GAME begins; incremented at Cleanup before the next Untap.
- **Phase / Step** — major division / subdivision of a turn (14 total, see
  `server/state.py::Phase`). Some open a priority window; UNTAP and CLEANUP do not.

## Priority & stack
- **Priority** — the right to take a game action; only its holder may cast/activate.
- **Priority window** — AP gets priority first; passing hands it over. Both pass
  with a non-empty stack → resolve top; both pass empty → step advances.
- **The Stack** — server-owned LIFO of spells/abilities/triggers. Index 0 = bottom
  (resolves last); last = top (resolves first).
- **State-Based Actions (SBA)** — checks applied after every event, repeatedly,
  before any priority: life ≤ 0 loses, toughness ≤ 0 or lethal damage → graveyard
  (RFC §8.4). Triggers are placed AFTER SBAs settle. Single funnel: `server/sba.py`.
- **Priority token** — the seq_num of the current PRIORITY_GRANT; action PDUs echo
  it or get STALE_ACTION (ADR 0006).
- **Triggered Ability** — an ability that fires off a game event (ETB, attack
  declared, ...) rather than being cast/activated. Detected in `server/sba.py`,
  placed on the stack (`STACK_PUSH`, `item_type="TRIGGER_ABILITY"`) *after* SBAs
  settle, then resolves through the normal pass/priority cycle like any other
  stack item — it is placed, not auto-resolved.
- **ETB (enters the battlefield)** — the event of a permanent being added to a
  battlefield (e.g. a creature spell resolving). Recorded in
  `state.pending_etb` when it happens, drained by `server/sba.py::resolve()`
  into trigger placement — SBA detection is event-gated off this list, not a
  battlefield re-scan.
- **Trigger Choice** — the pause between a targeted trigger being detected and
  its `STACK_PUSH`: the server holds `state.pending_trigger_choice`, sends
  `TRIGGER_CHOICE`, and resumes (pushing the trigger with the chosen target)
  on the matching `TRIGGER_CHOICE_RESPONSE` (RFC §8.6.4, ADR 0007). Distinct
  from a trigger's "you may" *optional* semantics (RFC §8.6.3), which reuses
  the same PDU pair but for accept/decline rather than target selection.

## State & messaging
- **Game State** — complete authoritative info (all zones, life, turn, phase).
- **Visible State** — the per-player subset; opponent hand hidden (count only).
- **PDU** — one MTGNP message (25 types, RFC §10). Every PDU has `type` + `seq_num`.
- **seq_num** — server monotonic counter (issuance) / priority echo token
  (validation); see ADR 0006 for all cases and exemptions.

## Cards
- **Catalog** — shared out-of-band card data (`cards.json`); PDU card ids are keys
  into it. Instance id (`lightning_bolt_001`) → base id (`lightning_bolt`).
- **Effect** — a card's resolution behavior, mostly a data-declared primitive
  (DAMAGE/GAIN_LIFE/DESTROY/COUNTER/DRAW); novel ones use the code escape hatch.
- **Keyword** — a FLAG on a permanent (first_strike, double_strike, haste,
  summoning_sick) read by the engine — not an effect (ADR 0004).

## Lifecycle
LOBBY → GAME_SETUP → MULLIGAN → IN_GAME → GAME_OVER → (back to) LOBBY on the same
retained TCP connections (RFC §6).
