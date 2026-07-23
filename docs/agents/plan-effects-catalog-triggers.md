# Handoff plan: catalog wiring → CAST_SPELL → effects → trigger funnel

Status: **IN PROGRESS** — Phases 0-2 implemented and committed 2026-07-23
(TDD, all green). Phase 3's Gray Merchant slice (handoff bullet 3: ETB ->
`pending_etb` -> `sba.resolve` places a TRIGGER_ABILITY -> resolves via
`custom_effects.py`, zero client interaction) is now implemented and green,
proved end-to-end through `GameEngine.handle` in
`tests/engine/test_triggers.py`. Gravedigger — the harder slice needing
`TRIGGER_CHOICE`/`TRIGGER_CHOICE_RESPONSE` (handoff bullet 4) — has not
started; grill its pause/resume state shape before writing that code, per
the plan's own sequencing. Part of issue #2 (Engine core).

## Branch state (2026-07-23, stacked — rebase-clean per-phase, not parallel)

- `feat/catalog-wiring` (off `main`, commit `cbe1459`): Phase 0 only. Clean
  standalone diff, PR-able now.
- `feat/engine-dispatch` (off `main`, commit `d027aae`): Phase 1 only. Clean
  standalone diff, PR-able now.
- `feat/cast-spell` (off `feat/engine-dispatch`, merges in `feat/catalog-wiring`,
  then Phase 2 commits `815f8bd` + `b1bd80d`): Phase 2 + two review fixes.
  Its diff-against-main currently includes all three phases because neither
  earlier branch has merged yet — **once `catalog-wiring` and `engine-dispatch`
  merge to `main`, rebase `feat/cast-spell` onto `main` and the merge commit
  collapses to just Phase 2's diff.** Branch Phase 3 off `feat/cast-spell`
  (or its post-rebase equivalent) the same way — base each new phase on the
  previous phase's tip, not on `main`, until the chain is merged.
- 102 tests passing on `feat/cast-spell`'s tip.

## Phase 3 handoff — read before writing code

An advisor review after Phase 2 landed caught one bug (fixed, see commit
`b1bd80d`) and gave Phase 3-specific design guidance that isn't in the
"Resolved design decisions" section below because it postdates that
grilling session. Treat this as higher-priority than the original Phase 3
bullet under "Build order" if the two seem to conflict.

1. **Detection must be event-gated, not a re-scan.** `sba.resolve` runs on
   _every_ `priority.grant` call (every step, every combat step, every
   resolution) — if trigger detection diffs the battlefield or re-scans
   state each time, it will re-fire on unrelated grants. Record the ETB
   explicitly: have `effects._enter_battlefield` append to
   `state.pending_etb` (a new GameState field, list of `(permanent_id,
controller_id)` — captured as a tuple at append time, since
   `_enter_battlefield` already has `item.controller_id` in scope there;
   don't re-derive the controller later by scanning battlefields), and
   have `sba.resolve` drain it after the SBA sweep, before priority. Empty
   on the vast majority of grants → no spurious triggers. The `{"type":
"ETB", ...}` entry in `state_changes` is a broadcast annotation only —
   don't wire the funnel to read it.

   **Drain ordering, confirmed via grilling 2026-07-23:** drain
   `pending_etb` inside the existing `if not dead:` branch — i.e. replace
   that branch's bare `return []` with "drain pending_etb, build the
   `STACK_PUSH` outbounds via `stack.push`, return those" — rather than
   draining before the `dead` check. Triggers are only ever placed when
   the game is still going; a game-ending SBA sweep this same tick leaves
   `pending_etb` un-drained (harmless — nothing reads it again once the
   game's over). For this 3-card subset the two paths never actually
   collide (Gray Merchant's life-loss happens later, when its _trigger_
   resolves via a separate `sba.resolve` call, not from its own ETB), but
   this is the invariant to hold as more cards land.

2. **Place-then-resolve, not auto-resolve.** The "Build order" bullet below
   says triggers "resolve... before any PRIORITY_GRANT" — that phrasing is
   imprecise. Only SBAs _resolve_ before priority. Triggers get _placed_ on
   the stack (STACK_PUSH, item_type="TRIGGER_ABILITY") before priority is
   granted, then resolve through the normal pass/priority cycle like any
   other stack item — so a player can respond to an ETB trigger before it
   resolves. `sba.py`'s own module docstring already has this right
   ("place them on the stack... then grant priority"); follow that, not the
   loose summary in this file's Build order section.

3. **Sequence within Phase 3: Gray Merchant of Asphodel first, alone.** It's
   untargeted, mandatory, and deterministic (devotion counts the
   battlefield) — it proves the whole ETB → `sba.resolve` drains
   `pending_etb` → place TRIGGER_ABILITY → resolve via `custom_effects.py`
   skeleton with **zero client interaction**. Prove that end-to-end first
   (a card entering, its trigger being placed, and resolving to drain each
   opponent's life by devotion-to-black), then commit it as its own slice
   before touching Gravedigger.

4. **Gravedigger is a separate, harder slice — do not bundle it with Gray
   Merchant.** Its trigger needs a target chosen from the controller's own
   graveyard, which means implementing `TRIGGER_CHOICE`/
   `TRIGGER_CHOICE_RESPONSE` (schemas already exist in `protocol/pdus.py`,
   unhandled) — a genuinely new control-flow shape: pause mid-resolution,
   wait for a client response, then resume. None of the currently-shipped
   handlers (turn/priority/combat/cast) do this; they're all
   synchronous-return. `TRIGGER_ORDER`/`TRIGGER_ORDER_RESPONSE` (2+
   simultaneous triggers for one controller) is a third, separate lift not
   needed for either of these two cards individually — don't build it
   speculatively; Phase 3 only ever has one ETB trigger pending at a time
   with this 3-card subset. `TRIGGER_ORDER_RESPONSE`/`TRIGGER_CHOICE_RESPONSE`
   currently fall through to `GameEngine._dispatch`'s no-op branch — that's
   where the resume handler for Gravedigger's choice lands.

   **Pause/resume shape, confirmed via grilling 2026-07-23 (see ADR 0007):**
   `custom_effects` registrations become a bundle (`requires_target`,
   `legal_targets_fn`, `resolver`) instead of a bare resolver, so
   `sba._drain_pending_etb` can decide push-immediately (Gray Merchant) vs.
   hold-for-target (Gravedigger) without calling card-specific logic first.
   `GameState.pending_trigger_choice: PendingTriggerChoice | None` is a
   single nullable field (trigger_id, source_id, controller_id) — not a
   queue, since this subset never has two targeted triggers pending at
   once. RFC §8.6.4 settles two sub-questions with no design decision
   needed: target selection happens before `STACK_PUSH`, and an empty
   `legal_targets` means the trigger is discarded immediately with no
   `TRIGGER_CHOICE` sent at all. Gravedigger is mandatory (no "you may" in
   its TSV text), so its `TRIGGER_CHOICE_RESPONSE` handler
   (`server/triggers.py::handle_trigger_choice_response`, newly wired into
   `engine._dispatch`) rejects `accept=False` as `TRIGGER_CHOICE_INVALID`
   rather than silently ignoring it.

## Why this plan exists

Issue #2's remaining work was assumed to be "effects.py + trigger funnel."
Investigation this session found the actual gap is three unbuilt layers, not
one, and that the trigger funnel's real driver is ETB (enters-the-battlefield),
not combat:

- `GameEngine.__init__`/`handle()` in `server/engine.py` are still
  `raise NotImplementedError` — there is no top-level PDU dispatcher. Every
  existing test (turn/priority/stack/combat) calls module functions directly,
  bypassing `GameEngine` entirely.
- There is no `CAST_SPELL` handler anywhere in `server/`. Nothing currently
  puts a spell on the stack or creates a `Permanent` on the battlefield via
  gameplay — `push()` is only ever called by tests directly constructing a
  `StackItem`. (The `CastSpell` PDU itself — `card_id`, `targets`,
  `mana_payment` — already exists in `protocol/pdus.py`; only the handler is
  missing.)
- `server/effects.py` (`apply()`) is a confirmed no-op stub;
  `server/custom_effects.py` is empty; `protocol/catalog.py`
  (`load_catalog`/`base_id`) and `tools/build_catalog.py` are stub
  (`raise NotImplementedError`) — nominally issue #5's file, but `effects.py`
  can't dispatch on real card data without it.
- Checked the actual fixed card set
  (`docs/references/master_card_list.tsv`) against every trigger-worthy event
  in RFC §8.6.1. **No card in this set triggers on combat damage or death.**
  The only combat-sourced trigger is Goblin Guide ("whenever ~ attacks",
  fires at DECLARE_ATTACKERS) and its effect is custom, not a primitive.
  The triggers that actually matter are ETB: Goblin Bushwhacker, Gray
  Merchant of Asphodel, Gravedigger. Building the funnel around combat's
  damage/death events would solve a problem this card set doesn't have —
  don't do that.

## Scope decision made this session

Wire a **minimal real `load_catalog`/`build_catalog`** as part of this work,
rather than hand-stubbing `Card` objects in tests indefinitely. Rationale:
`effects.apply(state, item)` only receives a `StackItem` (source_id, no
effect spec) — it needs a real path to card data, and hand-stubbing would
just be redone by issue #5 shortly after. This nominally touches a file
issue #5 owns; flag that overlap to the teammate when this lands (short
PR description note, not a blocker).

## Resolved design decisions

Resolved via a grilling session on 2026-07-23. Facts cited below were
confirmed against the codebase at that time.

1. **Plan/implementation PR bundling.** This plan merges standalone, ahead
   of implementation, so issue #5's owner has an explicit checkpoint to
   react to the catalog-scope overlap before any code exists.

2. **Phase 0 catalog subset.** `Lightning Bolt`, `Gravedigger`, `Gray
Merchant of Asphodel` only. Lightning Bolt proves the primitive
   (DAMAGE) path; the other two are the ETB cards Phase 3 needs to prove
   the trigger funnel. **Goblin Bushwhacker is dropped from Phase 0** — its
   effect is kicker-conditional ("if it was kicked"), and `CastSpell`'s PDU
   shape (`card_id`, `targets`, `mana_payment`) has no kicker field. Adding
   it now would force a kicker-PDU design decision as a side effect of
   catalog parsing; it moves to Phase 4 with the other custom-logic cards,
   where kicker can be designed deliberately. Full 57-card parse remains a
   Phase 4 fast-follow.

3. **Trigger declaration mechanism: no `Card.trigger` schema change.**
   `Card` (protocol/catalog.py) stays as-is (`effect: dict | None` for the
   primitive vocabulary only, per ADR 0004). Trigger detection lives
   entirely as a hardcoded lookup in `custom_effects.py` (e.g. a dict keyed
   by `base_id` → event type + resolver). Rejected the alternative
   (`Card.trigger: dict | None`, event type + effect spec) because: (a) the
   TSV has no structured "trigger event" column, so the mapping is
   hand-maintained either way — moving it into the schema doesn't create a
   real single source of truth, it just relocates the same manual work; (b)
   every trigger card in the actual set (Gravedigger, Gray Merchant, Goblin
   Guide, Bushwhacker) resolves through `custom_effects.py` regardless —
   none are primitive-triggerable, so the field would carry zero cards
   whose resolution it actually drives; (c) it would mean designing an
   event-type taxonomy (ETB, ATTACK, DIES, LEAVES_BATTLEFIELD, DRAW, per RFC
   §8.6.1) on a frozen dataclass with no cards to validate the shape
   against.

4. **`GameEngine.handle()` dispatch scope: full table now.** Wire every
   existing PDU type (turn/priority/stack/combat — everything the ~1300
   lines of module-level tests already exercise) through `handle()`, as its
   own mechanical PR **separate from** the CAST_SPELL feature work, with
   per-PDU-type dispatch tests. Rejected the minimal (CAST_SPELL-only)
   alternative: since `GameEngine` is a complete stub today with zero
   dependents, this is the cheapest point to close the facade gap in one
   pass; doing it later would mean revisiting `handle()` PDU-type by
   PDU-type across every subsequent phase. Keeping it as an isolated PR
   (reusing already-tested module functions, not adding new behavior)
   contains the regression risk to "was this wired correctly," not mixed
   with feature risk.

5. **Goblin Guide attack-trigger / Monastery Swiftspear prowess: deferred
   to Phase 4.** Neither is ETB-based; combat already ships without them
   (PR #10). `combat.py` has zero attack-trigger hooks today. Building
   these now would mean designing two more hook points (attack-declared,
   spell-cast) before Phase 3 has proven the ETB funnel works once.

6. **CAST_SPELL handler location: new `server/cast.py` module.** Not
   folded into `stack.py`. `stack.py` is a narrow "stack mechanics" module
   (push/resolve/fizzle) with its own focused test file; casting is a
   different responsibility (validate mana payment, validate targets,
   resolve `card_id` → `Card` via catalog, construct a `StackItem`) that
   would blur `stack.py`'s scope and muddy its existing tests if merged in.
   `cast.py` depends on `stack.py` (calls `stack.push()` as its last step),
   not the reverse.

## Build order (vertical slices, TDD per project convention)

**Phase 0 — Catalog wiring (3-card subset)**

- `tools/build_catalog.py`: parse `docs/references/master_card_list.tsv` (+
  `card_instances.tsv`) for **Lightning Bolt, Gravedigger, Gray Merchant of
  Asphodel** only; compile Lightning Bolt's "Simplified Effect" into the
  primitive vocabulary (DAMAGE) per ADR 0004; Gravedigger/Gray Merchant get
  `effect: null` (they resolve via `custom_effects.py`, Phase 3). Emit
  `cards.json`.
- `protocol/catalog.py`: implement `load_catalog()` (defaults to the
  packaged `cards.json`) and `base_id()` (strip numeric instance suffix).
- Full-set parsing (remaining ~54 cards, including Goblin Bushwhacker) is a
  Phase 4 fast-follow, not part of this slice.

**Phase 1 — GameEngine dispatch (full table)**

- Implement `GameEngine.__init__(rng)`: construct `GameState`, load catalog.
- Implement `handle(player_id, payload)`: parse bytes → PDU (INVALID_JSON /
  UNKNOWN_TYPE live here per engine.py's docstring), dispatch **every**
  existing PDU type to the existing module functions (turn/priority/stack/
  combat). Wire `tests/conftest.py`'s commented-out `GameEngine(rng=rng)`
  fixture. Implement `test_engine_scaffold.py`'s suggested first cases
  (PLAYER_READY validation, INVALID_JSON/UNKNOWN_TYPE, priority
  STALE_ACTION/CONCEDE exemption, personalized GAME_STATE_UPDATE).
- Ship as its own PR, separate from Phase 2's CAST_SPELL handler — this is
  mechanical re-plumbing of already-tested behavior, not new functionality.
  CAST_SPELL routing is added to the table in Phase 2 once `cast.py` exists.

**Phase 2 — CAST_SPELL → effects primitives (vertical slice: Lightning Bolt)**

- New module `server/cast.py`: validates mana payment (`mana_payment` on
  the `CastSpell` PDU) and targets, resolves `card_id` → `Card` via
  catalog, constructs `StackItem`, calls `stack.push`. Wired into
  `GameEngine.handle()`'s CAST_SPELL route.
- `effects.py` `apply()`: dispatch on the resolved card's `effect` dict
  (DAMAGE primitive first; GAIN_LIFE/DESTROY/COUNTER/DRAW follow as more of
  the catalog is wired), mutate `GameState`, return `state_changes[]` for
  `STACK_RESOLVE`.
- Resolving a creature spell must create a `Permanent` and append it to
  `player.battlefield` — this is the ETB event Phase 3 depends on.
- Prove this slice with Lightning Bolt (DAMAGE only, no triggers involved) —
  reuses the existing fizzle/resolve path in `stack.resolve_top` untouched.

**Phase 3 — Trigger funnel (RFC §8.6), driven by ETB**

- Detect the ETB event when Phase 2's CAST_SPELL resolution adds a
  `Permanent` to a battlefield.
- Trigger detection: a lookup in `custom_effects.py` keyed by `base_id`
  (per resolved decision 3, no `Card` schema change). Implement ordering
  (§8.6.2, AP-first/NAP-second, `TRIGGER_ORDER`/`TRIGGER_ORDER_RESPONSE`
  when a controller has ≥2 simultaneous — PDU schemas already exist in
  `protocol/pdus.py`, unhandled) and optional "you may" triggers (§8.6.3,
  `TRIGGER_CHOICE`/`TRIGGER_CHOICE_RESPONSE`, PDU schemas also already
  exist).
- Wire so triggers are placed on the stack and SBAs/triggers both resolve
  before any `PRIORITY_GRANT`, per §8.4/§8.6.1 ("after every game event").
- Prove this slice with Gravedigger and Gray Merchant (both ETB, both land
  in `custom_effects.py` — Gray Merchant's life-drain is devotion-based
  math, Gravedigger needs a graveyard target choice).

**Phase 4 — Remaining primitives + custom effects + full catalog**

- Fill in GAIN_LIFE/DESTROY/COUNTER/DRAW primitives against more of the
  catalog.
- Full-set `build_catalog.py` parse (remaining ~54 cards).
- Register Goblin Bushwhacker (kicker — design the `CastSpell`/cost-payment
  extension needed for a kicker flag here, not earlier), Goblin Guide's
  attack-trigger, Monastery Swiftspear's prowess, and any other genuinely
  novel cards (Phantasmal Bear's "becomes the target → sacrifice") in
  `custom_effects.py`.

## Testing

Follow the `tdd` skill (test-first). New/extended suites:
`tests/engine/test_catalog.py` (or under `tests/protocol/`),
`tests/engine/test_engine_scaffold.py` (Phase 1 dispatch — file already
exists as a placeholder), `tests/engine/test_cast_spell.py` (or extend
`test_stack.py`), `tests/engine/test_effects.py`,
`tests/engine/test_triggers.py`. Existing combat/turn/priority/stack/sba
tests should be unaffected — Phase 1 wires them behind `GameEngine.handle()`
without changing their behavior; Phase 2 adds a new pipeline (CAST_SPELL-in),
it doesn't change the pass/priority/combat control flow already shipped in
`ff95605`.
