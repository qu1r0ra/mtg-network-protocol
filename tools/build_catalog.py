"""Generate src/mtgnp/protocol/cards.json from the reference TSVs.

Reads docs/references/master_card_list.tsv (+ card_instances.tsv) and emits the
packaged card catalog consumed by mtgnp.protocol.catalog. Run whenever the card
set changes:

    uv run python tools/build_catalog.py

The "Simplified Effect" column is compiled into the primitive effect vocabulary
(DAMAGE / GAIN_LIFE / DESTROY / COUNTER / DRAW) per ADR 0004; rows that do not
map cleanly are emitted with effect=null and handled via the code escape hatch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MASTER_CARD_LIST = REPO_ROOT / "docs/references/master_card_list.tsv"
CATALOG_OUT = REPO_ROOT / "src/mtgnp/protocol/cards.json"

# Phase 0 subset (docs/agents/plan-effects-catalog-triggers.md): Lightning Bolt
# proves the DAMAGE primitive path; Gravedigger/Gray Merchant are the ETB cards
# Phase 3's trigger funnel needs. Full ~57-card parse is a Phase 4 fast-follow.
PHASE_0_BASE_IDS = {"lightning_bolt", "gravedigger", "gray_merchant"}

_DAMAGE_RE = re.compile(r"deals (\d+) damage to (any target|target player|target creature)")

_TARGET_TYPE = {
    "any target": "any",
    "target player": "player",
    "target creature": "creature",
}


def _compile_effect(effect_text: str) -> dict | None:
    """Compile the "Simplified Effect" column into the primitive vocabulary
    (ADR 0004). Rows that don't map cleanly get effect=None (resolved via
    server/custom_effects.py instead)."""
    match = _DAMAGE_RE.search(effect_text)
    if match:
        amount, target_phrase = match.groups()
        return {
            "type": "DAMAGE",
            "amount": int(amount),
            "target_type": _TARGET_TYPE[target_phrase],
        }
    return None


def _parse_row(row: str) -> tuple[str, dict] | None:
    fields = row.split("\t")
    if len(fields) != 16:
        return None
    (
        card_id,
        name,
        card_type,
        _subtype,
        colors,
        cmc,
        w,
        u,
        b,
        r,
        g,
        generic,
        power,
        toughness,
        _copies,
        effect_text,
    ) = fields
    if card_id not in PHASE_0_BASE_IDS:
        return None
    return card_id, {
        "name": name,
        "card_type": card_type,
        "colors": colors,
        "cmc": int(cmc),
        "mana_cost": {
            "W": int(w),
            "U": int(u),
            "B": int(b),
            "R": int(r),
            "G": int(g),
            "generic": int(generic),
        },
        "power": None if power == "-" else int(power),
        "toughness": None if toughness == "-" else int(toughness),
        "keywords": [],
        "effect": _compile_effect(effect_text),
    }


def main() -> None:
    lines = MASTER_CARD_LIST.read_text(encoding="utf-8").splitlines()
    cards: dict[str, dict] = {}
    for row in lines[2:]:  # skip title line + header line
        parsed = _parse_row(row)
        if parsed is not None:
            card_id, entry = parsed
            cards[card_id] = entry
    CATALOG_OUT.write_text(json.dumps(cards, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
