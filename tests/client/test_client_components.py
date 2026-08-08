from __future__ import annotations

import asyncio

from mtgnp.client.connection import Connection
from mtgnp.client.controller import CLIController
from mtgnp.client.renderer import Renderer
from mtgnp.protocol.framing import encode_frame
from mtgnp.protocol.pdus import GameStateUpdate, MulliganChoice, CastSpell


def test_cli_controller_builds_mulligan_bottom_and_mana_payment():
    controller = CLIController()

    mulligan = asyncio.run(
        controller._parse_user_input(
            "keep shock_001", {}, 3, "Choose keep or mulligan"
        )
    )
    assert isinstance(mulligan, MulliganChoice)
    assert mulligan.cards_to_bottom == ["shock_001"]

    cast = asyncio.run(
        controller._parse_user_input(
            "cast lightning_bolt_001 player_2",
            {},
            15,
            "You hold priority",
        )
    )
    assert isinstance(cast, CastSpell)
    assert cast.targets == ["player_2"]
    assert cast.mana_payment["R"] == 1


def test_renderer_accepts_actual_server_visible_state_shape():
    rendered = Renderer().render(
        {
            "your_player_id": "Alice",
            "turn": 1,
            "phase": "PRECOMBAT_MAIN",
            "active_player": "Alice",
            "life_totals": {"Alice": 20, "Bob": 17},
            "battlefield": {
                "Alice": [{"id": "mountain_001", "tapped": False}],
                "Bob": [],
            },
            "hand": ["lightning_bolt_001"],
            "hand_counts": {"Bob": 5},
            "library_counts": {"Alice": 10, "Bob": 12},
            "graveyard": {"Alice": [], "Bob": ["shock_001"]},
            "stack": [],
        }
    )

    assert "Turn 1 | PRECOMBAT_MAIN" in rendered
    assert "Alice: 20 (YOU)" in rendered
    assert "Lightning Bolt" in rendered
    assert "Opponent hand: 5 card(s)" in rendered
    assert "UNKNOWN" not in rendered


def test_connection_parses_discriminated_pdu_union_over_real_tcp():
    async def scenario() -> None:
        async def server_handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            del reader
            pdu = GameStateUpdate(
                seq_num=1,
                state={
                    "phase": "LOBBY",
                    "players_ready": 1,
                    "waiting_for": ["player_2"],
                },
            )
            writer.write(encode_frame(pdu.model_dump_json().encode("utf-8")))
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(server_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        received = []
        connection = Connection("127.0.0.1", port)

        try:
            await connection.connect()
            await connection.recv_loop(received.append)
        finally:
            await connection.close()
            server.close()
            await server.wait_closed()

        assert len(received) == 1
        assert isinstance(received[0], GameStateUpdate)
        assert received[0].state["phase"] == "LOBBY"

    asyncio.run(scenario())
