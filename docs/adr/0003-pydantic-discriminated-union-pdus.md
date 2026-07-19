# ADR 0003 — PDUs as a pydantic v2 discriminated union

Status: Accepted · Date: 2026-07-19

## Context
25 PDU types (RFC §10) cross the wire as JSON with heavy validation rules (11
error codes, required fields, seq_num). Four contributors must agree on formats.

## Decision
Model each PDU as a pydantic v2 BaseModel with a literal `type`, unified in a
discriminated union (`AnyPDU`) keyed on `type`. Field validation encodes the RFC
rules; parse failures map to INVALID_JSON, unknown discriminator to UNKNOWN_TYPE.
This is the only third-party runtime dependency.

## Alternatives
- stdlib dataclasses + hand-written validators (25 validators, more code).
- plain dicts + a validator fn (stringly-typed, fragile across contributors).

## Consequences
Declarative schemas, structured parse errors mapping straight to error codes,
one-line dispatch. Lives in `mtgnp.protocol` — the shared firewall both server
and client import (see ADR 0002). seq_num semantics are NOT enforced here (ADR
0006).
