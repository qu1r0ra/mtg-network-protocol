"""Message framing codec (RFC §5.2) — transport-agnostic.

A frame is a 4-byte big-endian unsigned length prefix followed by exactly that
many bytes of UTF-8 JSON payload. This module is pure byte manipulation with no
socket or asyncio dependency, so it is unit-testable in isolation and reusable by
both the async server shell and the async client connection.

The async read side lives in the transport/connection layers, which call
`read_frame` with their stream's read primitive. This keeps I/O out of the codec.
"""

from __future__ import annotations

from .constants import LENGTH_PREFIX_BYTES, MAX_PDU_BYTES


def encode_frame(payload: bytes) -> bytes:
    """Prefix `payload` with its 4-byte big-endian length. Raises if too large."""
    if len(payload) > MAX_PDU_BYTES:
        raise ValueError(
            f"payload of {len(payload)} bytes exceeds MAX_PDU_BYTES ({MAX_PDU_BYTES})"
        )
    return len(payload).to_bytes(LENGTH_PREFIX_BYTES, "big", signed=False) + payload


def decode_length_prefix(prefix: bytes) -> int:
    """Parse the 4-byte big-endian length prefix into an int."""
    if len(prefix) != LENGTH_PREFIX_BYTES:
        raise ValueError(
            f"expected {LENGTH_PREFIX_BYTES}-byte prefix, got {len(prefix)}"
        )
    return int.from_bytes(prefix, "big", signed=False)


# Note: the streaming read (read prefix -> read exactly N bytes) is implemented in
# transport.py / connection.py against their async stream. Receivers MUST read
# exactly N bytes before attempting JSON parsing (RFC §5.2).
