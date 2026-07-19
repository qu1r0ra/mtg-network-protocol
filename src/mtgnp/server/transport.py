"""Transport shell — the ONLY async code on the server (ADR 0001, 0002).

Responsibilities (and nothing else — no game logic):
  * asyncio TCP server on port 4444; accept exactly 2 clients, refuse the rest
    (RFC §5.1); retain connections across GAME_OVER (RFC §6.6).
  * Frame I/O: read 4-byte prefix -> read exactly N bytes -> pass raw payload to
    engine.handle(player_id, payload); write returned Outbounds (resolving
    recipient -> socket(s)).
  * Timers: per-priority time_limit_ms deadline -> engine.on_priority_timeout;
    heartbeat -> answer PING with PONG DIRECTLY (echo seq_num+timestamp, bypassing
    the engine's monotonic counter, RFC §10.2.25 / ADR 0006); no PONG / TCP drop
    -> engine.on_disconnect; reconnect handshake -> engine.on_reconnect.
  * Verbose mode: log EVERY inbound and outbound PDU here, at this one seam, both
    directions, clearly labelled (mandatory demo prerequisite, rubric).

The shell never inspects game state: Outbounds arrive already seq-stamped and
visibility-filtered from the core.
"""

from __future__ import annotations

# async def serve(host, port, *, verbose: bool) -> None: ...
# async def _read_frame(reader) -> bytes: ...           # prefix then exactly N bytes
# async def _write_outbound(writers, outbound) -> None: ...
# def _log(direction: str, player_id: str, pdu) -> None: ...  # verbose seam
