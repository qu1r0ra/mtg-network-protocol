"""Async client connection: framing + heartbeat + receive loop (RFC §4.3, §5.2).

Owns the socket. Sends PING every ~30s (client-maintained seq_num counter,
independent of the priority token, RFC §5.4/§10.2.24) and disconnects if no PONG
within ~10s. Receives frames (4-byte prefix -> exactly N bytes -> parse) and hands
parsed PDUs to the renderer/controller. Verbose mode logs every inbound/outbound
PDU (mandatory for the demo).
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable

from mtgnp.protocol.constants import (
    HEARTBEAT_INTERVAL_S,
    HEARTBEAT_TIMEOUT_S,
    LENGTH_PREFIX_BYTES,
    MAX_PDU_BYTES,
)
from mtgnp.protocol.framing import decode_length_prefix, encode_frame
from mtgnp.protocol.pdus import AnyPDU, Ping, Pong


class Connection:
    """Manages TCP connection, framing, heartbeat, and PDU I/O with the server."""

    def __init__(self, host: str, port: int, verbose: bool = False):
        self.host = host
        self.port = port
        self.verbose = verbose
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._seq_num = 0  # Client-side heartbeat counter
        self._pong_received = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Establish TCP connection to the server."""
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            if self.verbose:
                print(f"[CONNECTED] Connected to {self.host}:{self.port}")
        except (ConnectionError, OSError) as e:
            raise ConnectionError(f"Failed to connect to {self.host}:{self.port}") from e

    async def send(self, pdu: AnyPDU) -> None:
        """Send a PDU to the server (frame + write + verbose log)."""
        if self.writer is None or self.writer.is_closing():
            raise ConnectionError("Connection not established or closed")

        payload = pdu.model_dump_json().encode("utf-8")
        frame = encode_frame(payload)

        self._log("C->S", payload)

        try:
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, OSError) as e:
            raise ConnectionError("Failed to send PDU") from e

    async def recv_loop(self, on_pdu: Callable[[AnyPDU], None]) -> None:
        """Receive loop: read frames -> parse PDUs -> invoke on_pdu callback.
        
        Runs until connection closes or exception occurs.
        """
        if self.reader is None:
            raise ConnectionError("Connection not established")

        try:
            while True:
                payload = await self._read_frame()
                self._log("S->C", payload)

                try:
                    pdu_dict = json.loads(payload.decode("utf-8"))
                    pdu = AnyPDU.model_validate(pdu_dict)
                    on_pdu(pdu)
                except (json.JSONDecodeError, ValueError) as e:
                    if self.verbose:
                        print(f"[PARSE ERROR] {e}")
                    # Continue receiving; malformed PDUs are logged but not fatal
        except asyncio.IncompleteReadError:
            if self.verbose:
                print("[DISCONNECTED] Server closed connection")
        except (ConnectionError, OSError) as e:
            if self.verbose:
                print(f"[CONNECTION ERROR] {e}")

    async def _read_frame(self) -> bytes:
        """Read a single frame: 4-byte length prefix + exactly N bytes of payload."""
        if self.reader is None:
            raise ConnectionError("Reader not established")

        prefix = await self.reader.readexactly(LENGTH_PREFIX_BYTES)
        length = decode_length_prefix(prefix)

        if length > MAX_PDU_BYTES:
            raise ValueError(f"Frame length {length} exceeds MAX_PDU_BYTES ({MAX_PDU_BYTES})")

        return await self.reader.readexactly(length)

    async def heartbeat_loop(self) -> None:
        """Send PING every ~30s; disconnect if no PONG within ~10s (RFC §4.3)."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                self._seq_num += 1
                ping = Ping(seq_num=self._seq_num, timestamp=int(asyncio.get_event_loop().time() * 1000))

                self._pong_received = False
                await self.send(ping)

                # Wait for PONG with timeout
                try:
                    await asyncio.wait_for(
                        self._wait_for_pong(), timeout=HEARTBEAT_TIMEOUT_S
                    )
                except asyncio.TimeoutError:
                    if self.verbose:
                        print("[HEARTBEAT TIMEOUT] No PONG received, disconnecting")
                    self.close()
                    break

        except asyncio.CancelledError:
            pass

    async def _wait_for_pong(self) -> None:
        """Block until a PONG is received (set by on_pdu callback)."""
        while not self._pong_received:
            await asyncio.sleep(0.1)

    def on_pong_received(self) -> None:
        """Called by the orchestrator when a PONG is received."""
        self._pong_received = True

    def close(self) -> None:
        """Close the connection and cancel background tasks."""
        if self.writer is not None and not self.writer.is_closing():
            self.writer.close()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        if self._receive_task is not None:
            self._receive_task.cancel()

    def _log(self, direction: str, payload: bytes) -> None:
        """Log PDU in verbose mode (RFC §4.3)."""
        if not self.verbose:
            return
        try:
            rendered = json.dumps(json.loads(payload), separators=(",", ":"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            rendered = repr(payload)
        print(f"[{direction}] {rendered}")
