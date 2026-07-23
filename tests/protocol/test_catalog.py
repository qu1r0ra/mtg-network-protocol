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


def test_load_catalog_returns_full_58_card_set():
    catalog = load_catalog()
    assert len(catalog) == 58
    assert {"lightning_bolt", "gravedigger", "gray_merchant"} <= set(catalog)


def test_doom_blade_compiles_to_destroy_primitive():
    doom_blade = load_catalog()["doom_blade"]
    assert doom_blade.effect == {"type": "DESTROY", "target_type": "creature"}


def test_counterspell_compiles_to_counter_primitive():
    counterspell = load_catalog()["counterspell"]
    assert counterspell.effect == {"type": "COUNTER", "target_type": "spell"}


def test_negate_does_not_compile_its_noncreature_restriction():
    """"Counter target noncreature spell." isn't representable by the
    unrestricted COUNTER primitive -- stays effect=None rather than silently
    dropping the restriction (ADR 0004 escape hatch, unregistered so far)."""
    negate = load_catalog()["negate"]
    assert negate.effect is None


def test_ornithopter_is_an_artifact_creature_with_no_primitive_effect():
    """Card_type is the compound "Artifact Creature" text from the TSV, not
    a bare "Creature" -- effects.apply()'s creature-ETB check must still
    recognize it (card_type is space-split, not exact-matched)."""
    ornithopter = load_catalog()["ornithopter"]
    assert ornithopter.card_type == "Artifact Creature"
    assert ornithopter.effect is None


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


def test_goblin_bushwhacker_parses_kicker_cost_and_stays_customeffects_bound():
    """"Kicker {1}{R}." is a cast-time cost fact, orthogonal to ADR 0004's
    primitive vocabulary -- effect stays None (resolved in custom_effects.py)
    even though kicker_cost is populated."""
    bushwhacker = load_catalog()["goblin_bushwhacker"]
    assert bushwhacker.mana_cost == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "generic": 0}
    assert bushwhacker.kicker_cost == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "generic": 1}
    assert bushwhacker.effect is None


def test_non_kicker_card_has_no_kicker_cost():
    assert load_catalog()["lightning_bolt"].kicker_cost is None


def test_goblin_guide_parses_static_haste_keyword_and_stays_customeffects_bound():
    """"Haste. " is a leading keyword clause (ADR 0009), stripped the same
    way as the kicker clause -- effect stays None (the reveal-trigger
    resolves via custom_effects.py, not a compiled primitive)."""
    goblin_guide = load_catalog()["goblin_guide"]
    assert goblin_guide.keywords == frozenset({"Haste"})
    assert goblin_guide.effect is None


def test_monastery_swiftspear_also_parses_static_haste_keyword():
    """Confirms the keyword-clause stripper isn't Goblin-Guide-specific."""
    swiftspear = load_catalog()["monastery_swiftspear"]
    assert swiftspear.keywords == frozenset({"Haste"})


def test_vines_of_vastwood_compiles_to_protect_and_pump_primitive():
    """"Kicker {G}. " strips first (ADR 0008), then the targeting-restriction
    + conditional-pump text compiles to PROTECT_AND_PUMP (ADR 0012)."""
    vines = load_catalog()["vines_of_vastwood"]
    assert vines.kicker_cost == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "generic": 0}
    assert vines.effect == {
        "type": "PROTECT_AND_PUMP",
        "target_type": "creature",
        "power_bonus": 4,
        "toughness_bonus": 4,
    }


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
