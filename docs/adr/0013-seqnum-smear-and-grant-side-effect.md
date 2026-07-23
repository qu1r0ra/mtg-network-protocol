# ADR 0013 — seq_num increment smear and `priority.grant`'s embedded SBA pass (Card F, not implemented)

Status: Accepted (recorded, no code change) · Date: 2026-07-23

## Context
The pre-handoff architecture review (Card F) flagged two related observations:

1. `state.seq_num += 1` is inlined at 27 call sites across 8 modules
   (`cast.py`, `combat.py`, `stack.py`, `lifecycle.py`, `priority.py`,
   `engine.py`, `turn.py`, `triggers.py`), each followed by using
   `state.seq_num` to stamp the outbound PDU being built. `sba.py`'s
   `_push_trigger` (ADR-numbered elsewhere, this session) relies on the
   fragile-by-inspection idiom `stack_item_id = f"..._{state.seq_num + 1}"` —
   correct only because the reader can confirm `stack.push` increments
   `seq_num` exactly once, immediately after, with nothing in between.
2. `priority.grant` runs the *entire* SBA + trigger-drain pipeline
   (`sba.resolve`) as its first line, before doing anything that looks like
   "grant priority." Nothing in the function's name or call sites signals
   that calling it may sweep lethal creatures, push triggers, or end the
   game.

Card F was tiered 🔴 RECORD AS ADR / Speculative in the review, not 🟢 SAFE NOW
or 🟡 DESIGN ONLY — this ADR is that record, not a plan to implement.

## Decision — do not refactor either concern now

**(1) seq_num increments stay inlined.** A `next_seq(state) -> int` helper
was considered. It would touch all 27 sites across all 8 engine modules —
strictly larger blast radius than any of Cards A/B/C/E/G, and unlike those,
the duplication here is a two-token idiom (`state.seq_num += 1` then read
`state.seq_num`), not real repeated logic. The deletion test fails: removing
the helper wouldn't cause complexity to reappear elsewhere, because there's
no complexity concentrated in the repetition — it's just the shape of "every
outbound gets a fresh stamp," which ADR 0006 already governs as a semantic
rule. Sweeping every emission site in the engine, right as the interface
freezes for groupmates building against it (issues #3/#4/#5), is the wrong
trade for a cosmetic win. The one concrete risk item — `stack_item_id =
seq_num + 1` being correct only by convention — is narrow enough to fix
locally if it ever causes a bug; it hasn't (209/209 tests, including direct
stack-item-id assertions).

**(2) `priority.grant`'s SBA call stays embedded, undocumented-as-a-flaw.**
This is not an accident to fix — it is RFC-mandated ordering, and `sba.py`'s
own module docstring already flags it as CRITICAL (advisor R4): state-based
actions and the trigger funnel MUST run after every game event and before
ANY priority is granted (RFC §8.4, §8.6). `priority.grant` is the only choke
point every action handler routes through before granting the next window,
so embedding the call there — rather than trusting every one of ~15 call
sites to remember to call `sba.resolve` first — is the safer design, not a
leaky one. Decoupling them (e.g. requiring callers to call `sba.resolve`
then `priority.grant` separately) would reintroduce exactly the bug class
this centralization prevents: a handler that grants priority without
running SBAs first, silently violating RFC §8.4. The "hidden side effect"
reads as a flaw only if you expect `grant` to do just one thing; given the
RFC's ordering requirement, doing both *is* the one thing this function is
responsible for.

## Consequences
No code changes from this ADR. Future engine work should keep treating
`priority.grant` as the SBA+trigger-funnel+grant bottleneck (already true of
every existing call site) rather than hand-rolling `sba.resolve()` calls
elsewhere. If a future card set needs `next_seq`-style centralization (e.g.
because a new seq_num-adjacent bug actually appears), re-open this as a
Tier-1-style pure move at that point — the case for it will be concrete
rather than speculative.
