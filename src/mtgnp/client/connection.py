"""Async client connection: framing + heartbeat + receive loop (RFC §4.3, §5.2).

Owns the socket. Sends PING every ~30s (client-maintained seq_num counter,
independent of the priority token, RFC §5.4/§10.2.24) and disconnects if no PONG
within ~10s. Receives frames (4-byte prefix -> exactly N bytes -> parse) and hands
parsed PDUs to the renderer/controller. Verbose mode logs every inbound/outbound
PDU (mandatory for the demo).
"""

from __future__ import annotations

# class Connection:
#     async def connect(host, port) -> None: ...
#     async def send(pdu) -> None: ...            # frame + write (+ verbose log)
#     async def recv_loop(on_pdu) -> None: ...    # read frames -> on_pdu
#     async def _heartbeat(self) -> None: ...     # PING cadence + PONG timeout
