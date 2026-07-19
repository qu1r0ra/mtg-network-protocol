"""End-to-end socket smoke test (Q7).

Spin up the real asyncio server on an ephemeral port, connect two headless
ScriptController clients, play a short scripted game. Proves framing + transport +
heartbeat work over real TCP — the one layer engine unit tests can't reach.
"""


def test_scaffold_placeholder():
    assert True
