# ADR 0010 — Cast-declared trigger hook, with a `kind`-tagged registry

Status: Accepted · Date: 2026-07-23

## Context
Monastery Swiftspear ("Haste. Prowess (Whenever you cast a noncreature spell,
this creature gets +1/+1 until end of turn.)") is the first card in the
58-card set whose trigger fires off `CAST_SPELL` rather than an ETB or a
declared attack. `cast.py::handle_cast_spell` has no "a spell was cast"
observation point today (confirmed in ADR 0009, which explicitly deferred
this card for that reason).

Unlike the ETB (ADR 0007) and attack-trigger (ADR 0009) hooks, prowess cannot
be a structural twin of `_drain_pending_etb`/`_drain_pending_attack_trigger`.
Both existing drains look up `custom_effects.get(base_id(queued_entity))`
where the queued entity *is* the trigger source (the permanent that entered,
the creature that attacked). Prowess breaks this: the queued event is the
*spell being cast* (e.g. an opponent's or ally's Lightning Bolt), but the
effect must buff a *different*, already-battlefield-resident permanent
(Swiftspear). A drain keyed by the cast spell's own `base_id` would never
find Swiftspear's resolver.

This also surfaces a latent gap in `custom_effects._REGISTRY`: it's a flat
`base_id → TriggerSpec` dict with no notion of *which* pending-queue a
resolver belongs to, because ETB/attack drains only ever look up the one
entity that just triggered the event — any hit is correct by construction.
A cast-trigger drain must instead scan the *entire* caster's battlefield and
ask "does this permanent have a registered resolver?" — which would also
match e.g. Goblin Guide (registered for its attack-trigger) sitting on that
battlefield, incorrectly firing its reveal ability on an unrelated cast.

## Decision

**Registry `kind` tag.**
- `TriggerSpec` gains `kind: Literal["etb", "attack", "cast"]`; `register()`
  takes `kind` as a required keyword argument. Existing registrations are
  retrofitted: `goblin_guide` → `kind="attack"`, all ETB-resolved cards
  (Gray Merchant, Gravedigger, Goblin Bushwhacker) → `kind="etb"`.
- Same single dict, not a second registry — avoids two registries drifting
  out of sync, and documents each resolver's trigger source inline at its
  `@register` call site.
- ETB/attack drains gain a `spec.kind == "..."` guard alongside their
  existing `spec is None` check. This is not merely hygiene: casting Goblin
  Guide makes it ETB into `pending_etb` like any creature, and pre-guard the
  ETB drain would fire its `kind="attack"` resolver, which reads
  `state.attackers[item.source_id]` and raises `KeyError` since Goblin Guide
  was never declared as an attacker — a reachable crash this ADR closes,
  not a hypothetical one.

**Cast-trigger hook.**
- `GameState.pending_cast_trigger: list[tuple[str, bool]]` —
  `(caster_id, is_noncreature)`. `is_noncreature` is computed once in
  `cast.py::handle_cast_spell` (`"Creature" not in card.card_type.split()`,
  matching the existing compound-type convention Goblin Guide's land-check
  established) and queued directly, rather than re-derived at drain time —
  the card is already loaded there, and re-deriving downstream would mean
  reaching back into stack state to find "what was just cast."
- `handle_cast_spell` appends to this queue before its existing trailing
  `priority.grant(state, player_id)` call, the same seam
  `handle_declare_attackers` uses for `pending_attack_trigger` — no new
  `sba.resolve()` call site needed, since `priority.grant` already routes
  through it unconditionally.
- `sba._drain_pending_cast_trigger`: for each queued entry where
  `is_noncreature`, scans `state.players[caster_id].battlefield` and, for
  each permanent whose `base_id` is registered with `kind="cast"`, pushes a
  `TRIGGER_ABILITY` StackItem (`source_id=permanent.id`,
  `controller_id=caster_id`, no targets — prowess needs none). This is the
  one place this ADR's shape genuinely diverges from the ETB/attack twin
  pattern: drain-by-battlefield-scan instead of drain-by-queued-entity-id.
- `@register("monastery_swiftspear", kind="cast")` resolver: increments
  `permanent.power_bonus`/`toughness_bonus` by 1 each (reusing ADR 0008's
  flat counters, cleared at Cleanup for free — no new cleanup wiring), emits
  a `{"type": "PUMP", ...}` state_change entry, same untyped
  `StackResolve.state_changes` vessel Bushwhacker's PUMP entries already
  ride in. No new PDU. Re-reads `item.source_id` off the caster's
  battlefield at resolution time rather than closing over the `Permanent`
  found at drain time — Swiftspear can leave the battlefield (e.g. killed in
  response, before its own trigger resolves) in the gap between push and
  resolution, and the resolver no-ops in that case rather than crashing,
  matching Goblin Guide's already-established "read state at resolution
  time, no-op if it's not there" idiom (advisor caught the crashing version,
  a bare `next(...)` with no default, before commit).

## Consequences
Multiple noncreature spells cast before a drain simply queue multiple
`(caster_id, True)` entries; each drains independently and re-scans the
battlefield, so `power_bonus` accumulates correctly per cast (not per spell
resolution — prowess triggers off *casting*, not resolving, matching the
card's actual text).

**Known gap, not fixed here:** if a controller has two prowess creatures and
casts one noncreature spell, both push `TRIGGER_ABILITY` items with no
`TRIGGER_ORDER` prompt, in whatever order `battlefield` iterates them —
the same deferred gap ADR 0007/0009 already carry for simultaneous triggers.
Not a new gap; this set has exactly one prowess card, so it can't yet be
observed with two.

The next cast-triggered card (none currently planned) reuses
`pending_cast_trigger`/`_drain_pending_cast_trigger` directly if its trigger
source is likewise "a permanent already on the battlefield, not the cast
spell itself." A trigger that instead cares about the cast spell's own
identity (e.g. "whenever you cast a spell with power > 4") would need a
different queue payload — deferred, not designed against speculatively.
