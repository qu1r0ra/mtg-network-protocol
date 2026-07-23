# ADR 0007 — Targeted triggers pause before STACK_PUSH via `pending_trigger_choice`

Status: Accepted · Date: 2026-07-23

## Context
Phase 3's first slice (Gray Merchant of Asphodel) proved ETB → `pending_etb` →
`sba.resolve` drain → `STACK_PUSH` for untargeted, mandatory triggers, with zero
client interaction. Gravedigger ("return target creature card from your
graveyard to your hand") needs a target chosen from the controller's graveyard
before it can go on the stack. RFC §8.6.4 is explicit that target selection via
`TRIGGER_CHOICE`/`TRIGGER_CHOICE_RESPONSE` happens *before* `STACK_PUSH` is
broadcast — but `GameEngine` is a synchronous request/response PDU handler
(`handle()` returns per call); it cannot literally block mid-resolution to wait
for a client reply.

## Decision
- `custom_effects` registrations become a bundle (`requires_target: bool`,
  `legal_targets_fn(state, controller_id) -> list[str]`, `resolver`), not a bare
  resolver function, so `sba._drain_pending_etb` can decide whether to push
  immediately or hold before calling anything card-specific.
- `GameState.pending_trigger_choice: PendingTriggerChoice | None` is a single
  nullable field, not a queue. This 3-card subset never has two ETB triggers
  needing a target at once; `TRIGGER_ORDER` (simultaneous triggers) is a
  separate, unbuilt lift (plan doc bullet 4) and out of scope here.
- When a drained ETB's trigger requires a target: compute `legal_targets`; if
  empty, discard silently, per RFC §8.6.4 ("no legal targets → discarded
  immediately, no effect, no `STACK_PUSH`"). Otherwise set
  `pending_trigger_choice` and emit `TRIGGER_CHOICE` — deferring `STACK_PUSH`
  until the response arrives.
- New `server/triggers.py::handle_trigger_choice_response` resumes the flow:
  validates `trigger_id`, rejects `accept=False` as `TRIGGER_CHOICE_INVALID`
  for a mandatory trigger (Gravedigger has no "you may" — the empty-graveyard
  case is the only legitimate no-op path, already handled before
  `TRIGGER_CHOICE` is even sent), builds the `StackItem` with `chosen_target`,
  and calls `stack.push`.

## Consequences
"Pause mid-resolution" is modeled as "return control to the caller, park
resumption state on `GameState`, resume on the next matching inbound PDU" —
the same shape every future targeted trigger (and eventually `TRIGGER_ORDER`)
will need to follow. The singular `pending_trigger_choice` field will need to
become a queue if/when a card set requires two simultaneous targeted triggers;
that reshape is deferred, not designed against speculatively.

`stack.resolve_top`'s target-legality recheck (RFC §8.4 FIZZLE rule) now
accepts graveyard membership as legal, but **only** when the resolving item
is a registered custom trigger with `requires_target=True` (i.e. Gravedigger,
not ordinary SPELL/ABILITY targeting) — `stack.py::_target_legal`'s
`allow_graveyard` parameter is derived from `custom_effects.get(...)` per
resolution. Without this scoping, any spell whose target died and moved to a
graveyard before resolving would silently RESOLVE against it instead of
FIZZLE (e.g. Lightning Bolt hitting a corpse) — caught by `advisor()` review
and guarded by `test_resolve_top_fizzles_when_target_died_and_moved_to_graveyard`.

`priority.grant` is not gated by `pending_trigger_choice`: after
`TRIGGER_CHOICE` is emitted, the active player still gets a normal priority
window with a live token, and nothing stops them from `PRIORITY_PASS`ing
instead of responding. If both players pass, the stack is empty (nothing was
pushed) and `turn.advance` fires with `pending_trigger_choice` still set —
orphaned until a `TRIGGER_CHOICE_RESPONSE` eventually arrives for a trigger
whose window has, per real MTG rules, already closed. This is consistent
with "resume on next matching inbound PDU," but it means the engine
currently trusts the client to respond promptly rather than enforcing it.
Deferred: gating priority (or auto-passing) while a trigger choice is
pending is a new design question, not covered by this ADR's seams.
