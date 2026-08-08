"""Deterministic end-to-end gameplay smoke test over real TCP.

The test uses seeded shuffling and seven-card decks so card IDs are guaranteed to
be in hand. It verifies lobby/setup/mulligan, priority passing, land play, spell
casting, stack resolution, authoritative life updates, and CONCEDE/GAME_OVER.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import random

from mtgnp.client.__main__ import run_client
from mtgnp.server.engine import GameEngine
from mtgnp.server.transport import TransportServer


def test_land_cast_resolve_and_concede_over_real_tcp(tmp_path):
    alice_script = tmp_path / "alice_full.json"
    bob_script = tmp_path / "bob_full.json"

    alice_script.write_text(
        json.dumps(
            [
                {
                    "action": "PLAYER_READY",
                    "player_id": "Alice",
                    "deck": [
                        "mountain_001",
                        "mountain_002",
                        "mountain_003",
                        "mountain_004",
                        "shock_001",
                        "goblin_guide_001",
                        "lightning_bolt_001",
                    ],
                },
                {"action": "MULLIGAN_CHOICE", "keep": True},
                {"action": "PASS_PRIORITY"},
                {"action": "PASS_PRIORITY"},
                {"action": "PLAY_LAND", "card_id": "mountain_001"},
                {
                    "action": "CAST_SPELL",
                    "card_id": "shock_001",
                    "targets": ["Bob"],
                    "mana_payment": {"R": 1},
                },
                {"action": "PASS_PRIORITY"},
                {"action": "CONCEDE", "player_id": "Alice"},
            ]
        ),
        encoding="utf-8",
    )

    bob_script.write_text(
        json.dumps(
            [
                {
                    "action": "PLAYER_READY",
                    "player_id": "Bob",
                    "deck": [
                        "forest_001",
                        "forest_002",
                        "forest_003",
                        "forest_004",
                        "llanowar_elves_001",
                        "grizzly_bears_001",
                        "giant_growth_001",
                    ],
                },
                {"action": "MULLIGAN_CHOICE", "keep": True},
                {"action": "PASS_PRIORITY"},
                {"action": "PASS_PRIORITY"},
                {"action": "PASS_PRIORITY"},
            ]
        ),
        encoding="utf-8",
    )

    async def scenario() -> None:
        transport = TransportServer(engine=GameEngine(rng=random.Random(7)))
        server = await transport.start("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        clients = [
            asyncio.create_task(
                run_client("127.0.0.1", port, True, str(alice_script))
            ),
            asyncio.create_task(
                run_client("127.0.0.1", port, True, str(bob_script))
            ),
        ]

        try:
            await asyncio.wait_for(asyncio.gather(*clients), timeout=5)
        finally:
            for task in clients:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*clients, return_exceptions=True)
            await transport.close()

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        asyncio.run(scenario())

    output = captured.getvalue()
    assert "[STACK PUSH]" in output
    assert "[STACK RESOLVED]" in output
    assert "Bob: 18" in output
    assert "Reason: CONCEDE" in output
