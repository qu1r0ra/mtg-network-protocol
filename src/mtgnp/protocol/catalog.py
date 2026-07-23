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

import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_CATALOG_PATH = Path(__file__).with_name("cards.json")


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
    target = Path(path) if path is not None else _DEFAULT_CATALOG_PATH
    entries = json.loads(target.read_text(encoding="utf-8"))
    return {
        card_id: Card(
            base_id=card_id,
            name=entry["name"],
            card_type=entry["card_type"],
            colors=entry["colors"],
            cmc=entry["cmc"],
            mana_cost=entry["mana_cost"],
            power=entry["power"],
            toughness=entry["toughness"],
            keywords=frozenset(entry["keywords"]),
            effect=entry["effect"],
        )
        for card_id, entry in entries.items()
    }


def base_id(instance_id: str) -> str:
    """Strip the numeric instance suffix: "lightning_bolt_001" -> "lightning_bolt"."""
    stem, _, suffix = instance_id.rpartition("_")
    if stem and suffix.isdigit():
        return stem
    return instance_id
