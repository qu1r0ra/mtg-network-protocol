"""Catalog wiring tests (Phase 0): 3-card subset (Lightning Bolt, Gravedigger,
Gray Merchant of Asphodel) per docs/agents/plan-effects-catalog-triggers.md.
"""

from __future__ import annotations

from mtgnp.protocol.catalog import base_id, load_catalog


def test_base_id_strips_numeric_instance_suffix():
    assert base_id("lightning_bolt_001") == "lightning_bolt"
    assert base_id("mountain_012") == "mountain"


def test_base_id_passes_through_already_base_ids():
    assert base_id("lightning_bolt") == "lightning_bolt"


def test_load_catalog_returns_phase_0_subset():
    catalog = load_catalog()
    assert set(catalog) == {"lightning_bolt", "gravedigger", "gray_merchant"}


def test_lightning_bolt_compiles_to_damage_primitive():
    bolt = load_catalog()["lightning_bolt"]
    assert bolt.name == "Lightning Bolt"
    assert bolt.card_type == "Instant"
    assert bolt.cmc == 1
    assert bolt.mana_cost == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "generic": 0}
    assert bolt.power is None
    assert bolt.toughness is None
    assert bolt.keywords == frozenset()
    assert bolt.effect == {"type": "DAMAGE", "amount": 3, "target_type": "any"}


def test_etb_creatures_have_no_primitive_effect():
    catalog = load_catalog()
    gravedigger = catalog["gravedigger"]
    assert gravedigger.card_type == "Creature"
    assert gravedigger.power == 2
    assert gravedigger.toughness == 2
    assert gravedigger.effect is None

    gray_merchant = catalog["gray_merchant"]
    assert gray_merchant.card_type == "Creature"
    assert gray_merchant.power == 2
    assert gray_merchant.toughness == 4
    assert gray_merchant.mana_cost == {"W": 0, "U": 0, "B": 2, "R": 0, "G": 0, "generic": 3}
    assert gray_merchant.effect is None
