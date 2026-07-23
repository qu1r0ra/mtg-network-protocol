# ADR 0012 — Targeting-restriction protection field and Vines of Vastwood's `PROTECT_AND_PUMP` primitive

Status: Accepted · Date: 2026-07-23

## Context
Vines of Vastwood (`Kicker {G}. Target creature can't be the target of
spells or abilities your opponents control this turn. If this spell was
kicked, that creature gets +4/+4 until end of turn.`) is the last card on
the original stretch-bonus roadmap. Its `kicker_cost` already parses for
free via ADR 0008's `_split_kicker`, but its effect was left `effect: null`
— deferred because it needs two things nothing in the engine has: a
targeting-restriction concept, and a targeted (not ETB/attack/cast-trigger)
kicker-conditional effect.

A repo-wide grep for `hexproof|protection from|can't be the target`
confirms no evasion/protection concept exists anywhere. ADR 0011's
targeted-trigger hook only *detects* that a permanent became a target; it
does not *prevent* targeting. This ADR is the first to add a restriction.

The engine is strictly 2-player (`combat.py::_other`), so "your opponents"
always resolves to "the other player" — there is no N-player scoping
question to solve.

## Decision

**Protection field.** `Permanent` gains `protected_by: str | None = None`
— the player_id of whoever cast the protecting spell (Vines' caster), not a
bool. Storing the caster's id rather than a bare
`cant_be_targeted_by_opponents: bool` matters for the (rare but legal) case
of casting Vines on an opponent's own creature: the restriction is scoped
to "opponents of the caster," which is not always the same player as "the
permanent's own controller." A bool inferred from the permanent's
controller would get that case backwards. Cleared in
`turn.py::_finish_cleanup`, in the same loop that already clears
`temp_haste`/`power_bonus`/`toughness_bonus` — no new expiry mechanism
needed, this reuses ADR 0008's existing Cleanup hook.

**Target-legality check.** Both `cast.py::_target_legal` and
`stack.py::_target_legal` gain a `caster_id: str` parameter (already in
scope at both call sites as `player_id` in `handle_cast_spell` and
`item.controller_id` in `resolve_top`). A permanent target is illegal if
`permanent.protected_by is not None and permanent.protected_by !=
caster_id`. This is a same-shape twin of the existing "does this id still
exist" checks both functions already do — one more clause, not a new
mechanism.

**Effect primitive.** `PROTECT_AND_PUMP` is added to
`effects.py::_EFFECT_HANDLERS` (ordinary `SPELL` dispatch, ADR 0004's
existing seam) rather than `custom_effects.py`'s registry — Vines is a
plain instant with no trigger/ETB involved, and
`effects.py::apply`:112-114 already restricts the `custom_effects`
registry to `item_type != "SPELL"`. Carving an exception into that
invariant for one card was rejected in favor of following the pattern
`DAMAGE`/`DESTROY`/`COUNTER` already establish.

One resolver, not two. `_apply_protect_and_pump` always sets
`protected_by = item.controller_id` on the target, then additionally adds
`power_bonus`/`toughness_bonus` (reusing ADR 0008's existing counters, no
new buff field) only `if item.kicked`. Protection and the conditional pump
are two clauses of one card's one resolution, not two independently
triggerable effects — splitting them into separate primitives would imply
they can occur independently, which they never do (there's no unkicked
"pump only" or "protect only" variant to compose differently).

**Catalog parsing.** `build_catalog.py::_compile_effect` gains a regex
matching Vines' post-kicker-strip text verbatim (this is the only card
with this exact wording; no attempt at generalizing beyond it), emitting
`{"type": "PROTECT_AND_PUMP", "target_type": "creature", "power_bonus": 4,
"toughness_bonus": 4}`. Regenerating `cards.json` turns
`vines_of_vastwood`'s `effect` from `null` into this dict — no hand-editing
of the generated catalog, following the existing tool-regenerates-the-JSON
convention.

**Scope note: "abilities" targeting a protected permanent.** The check is
only wired at `cast.py`/`stack.py`'s `_target_legal` (spells), not at
`triggers.py::handle_trigger_choice_response` (targeted custom abilities)
— but `resolve_top`'s resolution-time recheck runs against every stack
item with targets regardless of source, so any such ability would still
FIZZLE correctly rather than resolve against a protected permanent. No
selection-time rejection was added for that path because no card in the
58-card set needs it: `gravedigger` is the only `requires_target=True`
custom ability in the registry, and it targets the graveyard, not a
battlefield permanent. If a future card adds a targeted ability aiming at
permanents, wire the same `protected_by` check into
`handle_trigger_choice_response`'s legal-targets filter at that point.

## Consequences
`protected_by` is the first `Permanent` field whose *meaning* depends on
who else is looking at it (a restriction on other players' actions, not a
property of the permanent itself) — every prior temp-effect field
(`power_bonus`, `temp_haste`) affected only the permanent's own stats.
Future protection-style cards (e.g. a hypothetical "protection from red")
should extend this field's semantics (or add a sibling field) rather than
re-deriving a targeting-restriction mechanism from scratch, but a
same-shape generalization (e.g. "can't be targeted by a color" instead of
"can't be targeted by a player") is a separate future design question this
ADR does not attempt to anticipate.

This closes the original stretch-bonus roadmap
(`handoff-engine-core-required-rows-done.md`) — no other required rubric
rows remain after this card.
