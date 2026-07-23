# mtg-network-protocol

A TCP-based client-server protocol for conducting two-player, simplified Magic: The Gathering card game sessions over a network. Created for CSNETWK (Introduction to Computer Networking).

## Known limitations / deviations from RFC 0001

- **`TRIGGER_ORDER` / `TRIGGER_ORDER_RESPONSE` (RFC §8.6.2) — not emitted.** The
  engine never asks a controller to order two simultaneous triggers; all
  drained triggers of a given kind are pushed in queue order. Reachable with
  the shipped catalog (e.g. two Goblin Guides attacking in the same combat),
  but outcome-neutral there — the triggers are identical, so their relative
  stack order doesn't change the result. `TRIGGER_ORDER_INVALID` is defined
  in `protocol/errors.py` but never raised.
- **`ACTIVATE_ABILITY` (RFC §10.2.8) — not dispatched.** `engine.handle` has
  no case for it (falls through as a no-op); flagged at `server/engine.py:74`.
  Unreachable with the shipped catalog — no card has a non-mana activated
  ability.

Both were scoped out deliberately (not oversights) during the engine-core
architecture pass: building either now would mean guessing at a shape no
shipped card exercises. Revisit if a future card set adds a card that needs
one.
