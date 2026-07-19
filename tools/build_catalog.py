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


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
