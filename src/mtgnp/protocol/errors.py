"""MTGNP error codes (RFC §11).

The complete enumeration of ERROR `code` values. The server emits ERROR PDUs
carrying one of these; the game continues and the rejected action is discarded
(RFC §11). Disconnection MUST NOT occur merely because of an illegal action.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    INVALID_JSON = "INVALID_JSON"  # bytes not valid UTF-8 JSON
    ILLEGAL_DECK = "ILLEGAL_DECK"  # empty / >50 / unknown cards
    UNKNOWN_TYPE = "UNKNOWN_TYPE"  # `type` matches no known PDU
    STALE_ACTION = "STALE_ACTION"  # seq_num != current priority token
    NOT_YOUR_PRIORITY = "NOT_YOUR_PRIORITY"  # action while not holding priority
    ILLEGAL_ACTION = "ILLEGAL_ACTION"  # valid syntax, breaks a game rule
    ILLEGAL_TARGET = "ILLEGAL_TARGET"  # target not legal
    TRIGGER_ORDER_INVALID = "TRIGGER_ORDER_INVALID"
    TRIGGER_CHOICE_INVALID = "TRIGGER_CHOICE_INVALID"
    INSUFFICIENT_MANA = "INSUFFICIENT_MANA"
    WRONG_PHASE = "WRONG_PHASE"  # action illegal in current phase
    DUPLICATE_ID = "DUPLICATE_ID"  # player_id already claimed in lobby
