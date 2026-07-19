# ADR 0004 — Data-driven card effects + primitive resolvers

Status: Accepted · Date: 2026-07-19

## Context
Rubric: ≥5 card effects for full points, bonus for ALL effects. The RFC already
treats cards as catalog keys pre-loaded out-of-band (RFC §1 NOTE); the reference
TSVs include a "Simplified Effect" column.

## Decision
Cards are DATA in a generated `cards.json` (from the TSVs via
tools/build_catalog.py), shipped inside `mtgnp.protocol` so server and client load
identical data. Most effects compile to a small primitive vocabulary — DAMAGE,
GAIN_LIFE, DESTROY, COUNTER, DRAW — resolved by `server/effects.py`. Keyword
abilities (first_strike, double_strike, haste, summoning_sick) are FLAGS on the
permanent read by the combat/priority engine, NOT effects. Cards needing real
logic register in `server/custom_effects.py` (escape hatch).

## Consequences
90% of cards are pure data; the path from "5 effects" to "all effects" is cheap.
Effect logic stays out of the phase FSM. One shared catalog is the source of truth
for rendering (client) and resolution (server).
