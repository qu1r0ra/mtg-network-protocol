# ADR 0011 — Targeted-trigger hook and sacrifice-on-target

Status: Accepted · Date: 2026-07-23

## Context

Phantasmal Bear (`docs/references/master_card_list.tsv:29`, simplified effect
text): "Illusion. When Phantasmal Bear becomes the target of a spell or
ability, sacrifice it." This project's own simplified card list omits real
Phantasmal Bear's "can't be blocked except by artifact creatures" clause
entirely — confirmed by grepping the TSV row and the already-generated
`cards.json` entry (`effect: null, keywords: []`, nothing to parse a blocking
restriction from). Scope for this card is the sacrifice trigger only; no
blocking-restriction concept is introduced.

This is the third non-ETB trigger source, after ADR 0009's attack-trigger and
ADR 0010's cast-trigger. Two facts drove its shape:

- **Where "becomes the target" is observable.** `StackItem.targets` is set at
  exactly two call sites today: `cast.py:94` (CAST_SPELL) and
  `triggers.py:48` (`handle_trigger_choice_response`, ADR 0007's
  pause/resume resume-half). No `handle_activate_ability` exists yet. Rather
  than extracting a shared "target-assignment" chokepoint ahead of a second
  real caller, both sites are hooked directly (matching this project's
  general bias against premature generalization) — extraction is the right
  move once a third targeting path actually appears.
- **The queued entity IS the trigger source**, unlike ADR 0010's cast-trigger
  (where the caster is queued but the resolver lives on a different
  permanent). Here, the permanent that got targeted is exactly the permanent
  whose resolver should fire — so this hook is a structural twin of
  `_drain_pending_etb`/`_drain_pending_attack_trigger`, not of the
  battlefield-scanning cast-trigger drain.

Sacrifice has no prior implementation anywhere in the engine (confirmed by
grep). The closest existing shape is `_apply_destroy` (`effects.py:50-58`):
battlefield removal + graveyard append. That primitive is spell-targeted and
lives in the frozen `DESTROY` PDU-effect vocabulary; Phantasmal Bear's
sacrifice is not spell-targeted at all — it's the direct, choice-free
consequence of a custom resolver firing. No new primitive is added to the
frozen effects vocabulary for this.

## Decision

**Registry `kind` gains a fourth value.**
- `TriggerKind = Literal["etb", "attack", "cast", "targeted"]`.
- `@register("phantasmal_bear", kind="targeted")`.

**Targeted-trigger hook.**
- `GameState.pending_targeted_trigger: list[tuple[str, str]]` —
  `(target_id, controller_id)`, mirroring `pending_attack_trigger`'s
  `(attacker_id, controller_id)` shape exactly. The controller is already
  known at the point the target is assigned (whichever player's battlefield
  it's found on), so it's captured then rather than re-derived by a
  battlefield rescan at drain time.
- Append happens at both existing target-assignment sites, filtered to
  permanent targets only (player-id and stack-item/spell targets are not
  "a permanent became the target of a spell or ability" and must not queue):
  - `cast.py::handle_cast_spell`, right after the `StackItem` is built, for
    each id in `pdu.targets` that resolves to a permanent on some player's
    battlefield.
  - `triggers.py::handle_trigger_choice_response`, same check against
    `pdu.chosen_target`, after the pending choice is validated and before
    `stack.push`.
- `sba._drain_pending_targeted_trigger`: twin of `_drain_pending_attack_trigger`
  — for each queued `(target_id, controller_id)`, look up
  `custom_effects.get(base_id(target_id))`; skip if unregistered or
  `spec.kind != "targeted"`. If found, push a `TRIGGER_ABILITY` `StackItem`
  with `source_id` = the targeted permanent, `controller_id` from the queue
  entry, no targets. The resolver itself (not the drain) is what re-reads the
  battlefield at resolution time and no-ops if the permanent is already gone
  (e.g. destroyed by an unrelated effect before its own trigger resolves off
  the stack) — same idiom Goblin Guide/Swiftspear already established.
- Wired into `sba.resolve()` alongside the other three drains.

**Sacrifice resolver.**
- `@register("phantasmal_bear", kind="targeted")` resolver: finds
  `item.source_id` on `state.players[item.controller_id].battlefield` (reread
  at resolution time, not closed over at drain time — same reasoning as
  Swiftspear: something could remove the Bear between drain and this trigger
  actually resolving off the stack), removes it from the battlefield, appends
  its id to that controller's graveyard, and emits a `{"type": "SACRIFICE",
  "target": ...}` state_change. No-ops (returns `[]`) if the permanent is
  already gone. This directly mirrors `_apply_destroy`'s mutation shape
  without adding a new PDU-level primitive — sacrifice-on-target is not
  driven by the effects-primitive dispatch table at all, only by this
  registry.

## Consequences

Targeting Phantasmal Bear with *any* spell or ability that legally targets a
creature (removal, a pump spell, even your own trick) queues the sacrifice —
matching the real trigger condition ("becomes the target," not "becomes the
target of an opponent's spell"). Casting a spell that targets some other,
unrelated permanent never touches `pending_targeted_trigger` for the Bear at
all, since the queue only ever holds the ids that were actually targeted.

The real Phantasmal Bear's "can't be blocked except by artifact creatures"
clause is deliberately not implemented — this project's simplified card list
never specified it, and no blocking-restriction concept is introduced by this
ADR. If a future card in the set needs an evasion/blocking-restriction
ability, that is a new design question, not something this ADR answers
speculatively.

The next targeted-trigger card (none currently planned) reuses
`pending_targeted_trigger`/`_drain_pending_targeted_trigger` directly if its
trigger source is likewise "the permanent that was targeted, resolved at
drain time." A trigger that instead cares about *who* targeted it, or what
spell/ability did the targeting, would need a richer queue payload —
deferred, not designed against speculatively (same stance ADR 0010 took for
its own next-card gap).
