"""Golden-transcript tests (Q7, advisor R3).

Replay the docs/references/examples.md exchanges (LOBBY -> GAME_OVER) through the
engine and assert PDU TYPE + SHAPE + ORDER. Do NOT assert server-issued seq_nums
exactly: examples.md conflicts with the RFC on seq_num and self-declares a turn-1
draw deviation ([^8]). The RFC is the oracle; write the turn-1-no-draw case from
§7.4, not from the example.
"""


def test_scaffold_placeholder():
    assert True
