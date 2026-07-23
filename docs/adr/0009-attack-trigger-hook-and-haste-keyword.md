# ADR 0009 — Attack-declared trigger hook, reusing the ETB drain/registry shape

Status: Accepted · Date: 2026-07-23

## Context
Goblin Guide ("Haste. Whenever Goblin Guide attacks, defending player reveals
top card of library. If it's a land, that player puts it into their hand.")
is the first card in the 58-card set whose trigger fires off `DECLARE_ATTACKERS`
rather than an ETB. `custom_effects.py`'s registry and `sba._drain_pending_etb`
(ADR 0007) are the only trigger-detection path that exists; both are wired
specifically to `pending_etb`. Static `Haste` (as opposed to `Permanent.temp_haste`,
a temporary grant added by ADR 0008) also has no representation yet —
`build_catalog.py` hardcodes `"keywords": []` for every card, a gap ADR 0008
explicitly flagged as pre-existing and out of scope at the time.

## Decision

**Attack-trigger hook.**
- `GameState.pending_attack_trigger: list[tuple[str, str]]` — `(attacker_id,
  controller_id)`, queuing every declared attacker (registered or not),
  mirroring `pending_etb`'s "queue everything, filter at drain time" shape.
  No `kicked` slot: attack declarations have no kicker-payment concept.
- `combat.handle_declare_attackers` appends to this queue for each validated
  attacker, alongside the existing `state.attackers[...] = target` bookkeeping.
  No new drain call site is needed: the handler's existing trailing
  `priority.grant(state, ap)` already routes through `sba.resolve` (RFC §8.4
  bottleneck, unconditionally, per `sba.py`'s own docstring), so queuing
  before that call is sufficient.
- `sba._drain_pending_attack_trigger`, a structural twin of
  `_drain_pending_etb` minus the `kicked`/`kicker_gated` branch (N/A to
  attack triggers): pops the queue, looks up `custom_effects.get(base_id(
  attacker_id))`, drops unregistered entries (every vanilla attacker), else
  pushes a `TRIGGER_ABILITY` StackItem. Wired into `sba.resolve()` alongside
  the ETB drain.
- **No second registry.** `custom_effects._REGISTRY` is reused as-is:
  `effects.apply()`'s dispatch for a resolving `TRIGGER_ABILITY`/`ABILITY`
  item (`spec = custom_effects.get(base_id(item.source_id))`) was already
  agnostic to which pending-queue produced the StackItem — it only cares
  about the resolving item's base_id. Goblin Guide's resolver looks up its
  defending player via `state.attackers[item.source_id]` (still populated;
  cleared only at `END_OF_COMBAT`), the same "read already-live state at
  resolution time" pattern Gray Merchant's devotion count and Gravedigger's
  `item.controller_id` already establish.
- **No new PDU.** `StackResolve.state_changes` is an untyped `list[dict]`
  broadcast S→ALL (documented in `pdus.py` as intentionally loose, engine-owned
  shape) — the same vessel Gray Merchant's `DRAIN`/`GAIN_LIFE` and
  Bushwhacker's `PUMP` entries already ride in. Goblin Guide's reveal is a
  `{"type": "REVEAL", ...}` entry in that same list; MTG's "reveals" is
  inherently public information, and this list is already broadcast to both
  players, so no wire-contract change is needed here (unlike ADR 0008's
  `CastSpell.kicked`, which had no existing carrier).

**Static Haste keyword.**
- `build_catalog.py` gains `_KEYWORD_RE` stripping a leading `"Haste. "`
  clause (same shape as the existing kicker-clause stripper), populating
  `"keywords": ["Haste"]` instead of the hardcoded `[]`. Scoped to `Haste`
  only — `first_strike`/`double_strike` parsing remains unwired (no card in
  this set exercises it as a static keyword; those `Permanent` fields exist
  as prior scaffolding, not something this ADR extends).
- `Permanent.haste: bool = False` — a static, permanent flag distinct from
  `temp_haste` (which expires at Cleanup). Set once at `_enter_battlefield`
  from `"Haste" in card.keywords`, never cleared.
- Combat's summoning-sickness gate (`handle_declare_attackers`) becomes
  `permanent.summoning_sick and not (permanent.temp_haste or permanent.haste)`.

## Consequences
The next attack-triggered card (none currently planned in this set beyond
Goblin Guide) reuses `pending_attack_trigger`/`_drain_pending_attack_trigger`
directly — no reshape anticipated, since the shape is already a direct copy
of the proven ETB path. If a future card needs a *targeted* attack trigger
(picking a target before `STACK_PUSH`, ADR 0007-style), `_drain_pending_attack_trigger`
will need the same `requires_target`/`legal_targets_fn` branch
`_drain_pending_etb` already has — deferred, not designed against
speculatively, since Goblin Guide doesn't need it.

**Known gap, not fixed here:** two Goblin Guides attacking in the same combat
push two `TRIGGER_ABILITY` items with no `TRIGGER_ORDER` prompt (RFC §8.6's
"controller with >=2 simultaneous triggers is asked" is unbuilt everywhere,
same deferral ADR 0007 made). ADR 0007 justified skipping it because its
3-card subset could never produce two simultaneous triggers for one
controller; that justification does NOT carry over here, since a deck can
run up to 4 copies of Goblin Guide and declare several as attackers in one
combat. Order ends up implementation-defined (whatever order `pdu.attackers`
lists them) rather than controller-chosen. Fixing this is the same
`TRIGGER_ORDER` lift ADR 0007 already flagged as a future, non-speculative
piece of work — not reintroduced as a new gap by this ADR.

Monastery Swiftspear's prowess (a cast-trigger, not an attack-trigger) is
explicitly NOT covered by this ADR despite sharing the "Haste. " leading
clause — it needs a different hook (`cast.py` has no "spell was cast" event
yet) and is deferred to its own future design session, per the existing
handoff roadmap.
