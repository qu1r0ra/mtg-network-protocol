# ADR 0008 — Kicker as an explicit `CastSpell.kicked` field, plus a minimal temporary-effects shape

Status: Accepted · Date: 2026-07-23

## Context
Phase 4's mechanical slice deliberately deferred Goblin Bushwhacker ("Kicker
{1}{R}. When this enters, if it was kicked, creatures you control get +1/+0
and gain haste until end of turn") because it needed a genuine `CastSpell`
wire-contract decision — the 25-PDU set was contract-frozen (memory S2198)
with `CastSpell` shaped as `card_id`, `targets`, `mana_payment` only, and
MTGNP has no separate "activate mana ability" PDU: mana is always paid as one
atomic lump (RFC §10.2.7). Kicker is an optional additional cost declared at
cast time, so representing it meant either extending the wire contract or
inferring it from payment size.

Bushwhacker's effect also exposed a second gap: nothing in the engine models
a temporary ("until end of turn") buff or keyword grant. `Permanent` only had
permanent flags (`first_strike`, `double_strike`, `summoning_sick`); no card
before this one needed a buff that expires automatically. Vines of Vastwood
(also `Kicker {G}`, in the same 58-card set) confirmed kicker cost-payment
itself isn't Bushwhacker-specific, even though its own effect — a targeted
+4/+4 plus a targeting-restriction clause — needs infrastructure this ADR
does not build, and stays deferred.

## Decision

**Kicker cost-payment.**
- `CastSpell` gains `kicked: bool = False`. Rejected the alternative
  (inferring "kicked" from whether `mana_payment` covers base+kicker cost):
  `cast.py` only ever checks `paid >= required` per color key and never
  rejects overpayment, so "paid enough for kicker" and "coincidentally
  overpaid" are indistinguishable without an explicit signal. This also
  matches the project's existing convention for optional/declared actions —
  `TriggerChoiceResponse.accept` (ADR 0007) already models a "did the
  controller choose the optional thing" fact as an explicit boolean, not an
  inference.
- `Card` gains `kicker_cost: dict[str, int] | None`, parsed in
  `build_catalog.py` by stripping a leading `Kicker {..}. ` clause before the
  remainder falls through to `_compile_effect` as before. Kept as a field
  separate from `effect` (ADR 0004's closed primitive vocabulary): kicker
  cost is a cast-time cost fact, orthogonal to what the spell *does* when it
  resolves, and folding it into `effect` would break the `effect is None` ⇒
  "resolve via custom_effects" signal the rest of the pipeline relies on.
- `cast.py` requires `mana_cost` alone when not kicked, or `mana_cost +
  kicker_cost` (summed per key) when kicked; `kicked=True` on a card with no
  `kicker_cost` is `ILLEGAL_ACTION`.
- `kicked` threads through `StackItem.kicked` → the `pending_etb` tuple
  (widened from `(permanent_id, controller_id)` to `(permanent_id,
  controller_id, kicked)`) → the `TRIGGER_ABILITY` StackItem
  `sba._drain_pending_etb` builds. Considered storing `kicked` as a
  persistent field on `Permanent` instead (mirroring how Gray Merchant's
  devotion count reads permanents already in play) — rejected because
  "kicked" isn't a characteristic of the permanent in MTG rules, only a
  cast-time fact relevant to exactly one ETB trigger's resolution; threading
  it through the StackItem chain keeps it transient and reuses the existing
  "StackItem carries resolution data" pattern `targets` already establishes
  for Gravedigger, rather than introducing a second mechanism.
- "If it was kicked" is an intervening-if clause: `TriggerSpec` gains
  `kicker_gated: bool = False`; `sba._drain_pending_etb` discards the
  trigger silently (no `STACK_PUSH`) when `kicker_gated and not kicked`,
  mirroring the existing empty-`legal_targets` discard idiom (RFC §8.6.4)
  exactly. Goblin Bushwhacker's resolver in `custom_effects.py` therefore
  only ever runs already knowing it was kicked.

**Temporary effects (minimal, scoped to what Bushwhacker needs).**
- `Permanent` gains `power_bonus: int = 0`, `toughness_bonus: int = 0`,
  `temp_haste: bool = False` — flat counters, not a list of timed effects
  with per-source expiry, since everything in this card set expires at the
  same Cleanup point regardless of source, and simultaneous +N/+N effects
  correctly just add. Deliberately *not* built as a fully general framework
  for every future temporary-effect card (Giant Growth, Monastery
  Swiftspear's prowess, Mother of Runes) — those are separate future design
  sessions; this ADR only commits to the shape "temporary numeric/boolean
  modifiers live on `Permanent`, cleared at Cleanup."
- Cleared in `turn.py::_finish_cleanup`, alongside the existing damage-reset
  loop (the natural, already-existing "expire at turn end" hook).
- Wired into every place power/toughness or attack-legality already read
  the base stat: `combat.py`'s attacker/blocker power in `_apply_combat_damage`
  and the lethal-order calculation, `sba.py`'s lethal-toughness sweep, and
  `turn.py::_permanent_view`'s reported `power`/`toughness` (so GSU reflects
  live buffed values). `combat.py`'s attack-legality check gates on
  `summoning_sick and not temp_haste` rather than `summoning_sick` alone.

**Explicitly not done:** wiring the *static* `Haste` keyword (Goblin
Guide/Monastery Swiftspear already carry "Haste" in their card text) into
attack legality. `tools/build_catalog.py` hardcodes `"keywords": []` for
every card — no keyword-text parsing exists at all yet — so a
`"haste" in card.keywords` check would be dead code for a scenario the
catalog cannot currently produce. That gap is pre-existing and orthogonal to
kicker; closing it is a separate, future piece of work.

## Consequences
`CastSpell` is no longer exactly the frozen 3-field shape from the contract
freeze (memory S2198) — `kicked` is the first addition since. Any client
implementation written against the original frozen contract needs to add
this field (defaults `False`, so existing non-kicker casts are unaffected).

Vines of Vastwood's `kicker_cost` now parses for free via the same
`build_catalog.py` regex, but its own effect (targeted +4/+4, plus a
targeting-restriction clause) is still `effect: null` / unregistered —
implementing it needs targeted-buff and targeting-restriction
infrastructure this ADR doesn't build. Not a card left broken by this
change; it was already dormant before this slice.

The next temporary-effect card (Giant Growth is the simplest next case — a
targeted, single-permanent +3/+3 with no ETB/trigger funnel involved at all)
should extend `power_bonus`/`toughness_bonus` rather than re-deriving a
buff mechanism; if a future card needs a duration other than "until end of
turn" or per-source expiry (e.g. "until end of turn" stacking distinctly
from a permanent's other buffs), the flat-counter shape will need to become
a list, same kind of reshape ADR 0007 anticipated for
`pending_trigger_choice`.
