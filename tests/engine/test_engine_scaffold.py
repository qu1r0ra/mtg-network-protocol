"""Engine unit tests (Q7): feed a PDU payload to engine.handle, assert the
returned Outbounds + resulting state. Every RFC section and every ErrorCode gets
coverage here — no networking involved.

Suggested first cases:
  * PLAYER_READY: valid; ILLEGAL_DECK (empty/>50/unknown); DUPLICATE_ID.
  * handle(bytes): INVALID_JSON (bad bytes); UNKNOWN_TYPE (bogus `type`).
  * priority: STALE_ACTION on wrong token; CONCEDE exempt from the token.
  * personalized GAME_STATE_UPDATE: opponent hand hidden -> count only.
"""


def test_scaffold_placeholder():
    assert True
