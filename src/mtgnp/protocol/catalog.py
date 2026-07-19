"""Card catalog — shared out-of-band card data (RFC §1 NOTE).

MTGNP 1.0 does not transfer card data over the wire; card IDs in PDUs are keys
into this shared catalog, pre-loaded identically by server and client. The
catalog is generated from the reference TSVs by tools/build_catalog.py into
`cards.json`, which ships inside this package so both sides load byte-identical
data.

Design (ADR 0004): cards are DATA. Most effects compile to a small primitive
vocabulary (DAMAGE, GAIN_LIFE, DESTROY, COUNTER, DRAW) resolved by the engine.
Keyword abilities (first_strike, double_strike, haste, ...) are FLAGS read by the
combat/priority engine, not effects. Genuinely novel cards use the code escape
hatch in server/custom_effects.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Card:
    """A card definition keyed by its base id (e.g. "lightning_bolt").

    Instance ids in PDUs (e.g. "lightning_bolt_001") strip their numeric suffix
    to look up the base definition here.
    """

    base_id: str
    name: str
    card_type: str            # Land | Creature | Instant | Sorcery | ...
    colors: str               # subset of "WUBRG" ("" for colorless)
    cmc: int
    mana_cost: dict[str, int] # {"W":.., "U":.., "B":.., "R":.., "G":.., "generic":..}
    power: int | None         # creatures only
    toughness: int | None     # creatures only
    keywords: frozenset[str]  # first_strike, double_strike, haste, ...
    effect: dict | None       # primitive spec, or None for vanilla/land/custom


def load_catalog(path: str | None = None) -> dict[str, Card]:
    """Load cards.json into {base_id: Card}. Defaults to the packaged file."""
    raise NotImplementedError


def base_id(instance_id: str) -> str:
    """Strip the numeric instance suffix: "lightning_bolt_001" -> "lightning_bolt"."""
    raise NotImplementedError
