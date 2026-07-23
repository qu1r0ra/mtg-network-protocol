"""Generate src/mtgnp/protocol/cards.json from the reference TSVs.

Reads docs/references/master_card_list.tsv (+ card_instances.tsv) and emits the
packaged card catalog consumed by mtgnp.protocol.catalog. Run whenever the card
set changes:

    uv run python tools/build_catalog.py

The "Simplified Effect" column is compiled into the primitive effect vocabulary
(DAMAGE / DESTROY / COUNTER so far; GAIN_LIFE/DRAW have handlers in effects.py
but no card in this set compiles to them standalone) per ADR 0004; rows that do
not map cleanly are emitted with effect=null and handled via the code escape
hatch, or left dormant (keyword/activated-ability text the engine doesn't act
on yet).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MASTER_CARD_LIST = REPO_ROOT / "docs/references/master_card_list.tsv"
CATALOG_OUT = REPO_ROOT / "src/mtgnp/protocol/cards.json"

_DAMAGE_RE = re.compile(r"deals (\d+) damage to (any target|target player|target creature)")

_TARGET_TYPE = {
    "any target": "any",
    "target player": "player",
    "target creature": "creature",
}

_DESTROY_RE = re.compile(r"^Destroy target ([^.]+)\.")
_COUNTER_TEXT = "Counter target spell."

_KICKER_RE = re.compile(r"^Kicker ((?:\{[^}]+\})+)\.\s*")
_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_KEYWORD_RE = re.compile(r"^(Haste)\.\s*")


def _parse_mana_symbols(cost_str: str) -> dict:
    cost = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "generic": 0}
    for symbol in _MANA_SYMBOL_RE.findall(cost_str):
        if symbol.isdigit():
            cost["generic"] += int(symbol)
        else:
            cost[symbol] += 1
    return cost


def _split_kicker(effect_text: str) -> tuple[dict | None, str]:
    """Strip a leading "Kicker {1}{R}. " clause (a cast-time cost-payment
    fact, orthogonal to ADR 0004's primitive vocabulary) and return
    (kicker_cost, remaining_text) for _compile_effect to parse as usual."""
    match = _KICKER_RE.match(effect_text)
    if match is None:
        return None, effect_text
    return _parse_mana_symbols(match.group(1)), effect_text[match.end():]


def _split_keywords(effect_text: str) -> tuple[list[str], str]:
    """Strip a leading recognized keyword clause (e.g. "Haste. ") and return
    (keywords, remaining_text) for _compile_effect to parse as usual. Only
    Haste is recognized so far -- extend _KEYWORD_RE as future cards need
    more (ADR 0009)."""
    match = _KEYWORD_RE.match(effect_text)
    if match is None:
        return [], effect_text
    return [match.group(1)], effect_text[match.end():]


def _compile_effect(effect_text: str) -> dict | None:
    """Compile the "Simplified Effect" column into the primitive vocabulary
    (ADR 0004). Rows that don't map cleanly get effect=None (resolved via
    server/custom_effects.py, or left dormant for keyword/activated-ability
    text the engine doesn't act on yet)."""
    match = _DAMAGE_RE.search(effect_text)
    if match:
        amount, target_phrase = match.groups()
        return {
            "type": "DAMAGE",
            "amount": int(amount),
            "target_type": _TARGET_TYPE[target_phrase],
        }

    match = _DESTROY_RE.match(effect_text)
    if match and "creature" in match.group(1):
        # Restriction text (e.g. "nonblack creature") isn't modeled -- target
        # legality here is already coarse-grained (cast.py/stack.py), same as
        # DAMAGE's "any target" not enforcing further restrictions.
        return {"type": "DESTROY", "target_type": "creature"}

    if effect_text.strip() == _COUNTER_TEXT:
        return {"type": "COUNTER", "target_type": "spell"}

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
    kicker_cost, remaining_text = _split_kicker(effect_text)
    keywords, remaining_text = _split_keywords(remaining_text)
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
        "keywords": keywords,
        "effect": _compile_effect(remaining_text),
        "kicker_cost": kicker_cost,
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
