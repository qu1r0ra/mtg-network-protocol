"""Async client connection: framing, heartbeat, and receive loop.

The connection object owns the TCP stream. It applies the RFC's 4-byte
big-endian frame format, parses the discriminated PDU union, logs all traffic
when verbose mode is enabled, and maintains the PING/PONG heartbeat.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable

from pydantic import TypeAdapter, ValidationError

from mtgnp.protocol.constants import (
    HEARTBEAT_INTERVAL_S,
    HEARTBEAT_TIMEOUT_S,
    LENGTH_PREFIX_BYTES,
    MAX_PDU_BYTES,
)
from mtgnp.protocol.framing import decode_length_prefix, encode_frame
from mtgnp.protocol.pdus import AnyPDU, Ping, Pong

_PDU_ADAPTER = TypeAdapter(AnyPDU)
PDUCallback = Callable[[AnyPDU], Awaitable[None] | None]


class Connection:
    """Manage one TCP connection to the authoritative server."""

    def __init__(self, host: str, port: int, verbose: bool = False):
        self.host = host
        self.port = port
        self.verbose = verbose
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        self._heartbeat_seq_num = 0
        self._pending_ping: tuple[int, int] | None = None
        self._pong_event = asyncio.Event()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._closed_event = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    async def connect(self) -> None:
        """Establish the TCP connection."""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
        except (ConnectionError, OSError) as exc:
            raise ConnectionError(
                f"Failed to connect to {self.host}:{self.port}"
            ) from exc

        self._closed_event.clear()
        if self.verbose:
            print(f"[CONNECTED] Connected to {self.host}:{self.port}")

    def start(self, on_pdu: PDUCallback) -> None:
        """Start the receive and heartbeat background tasks.

        ``connect()`` must be called first. Calling ``start`` more than once is
        an error because two receive loops must never read the same stream.
        """
        if not self.connected:
            raise ConnectionError("Connection not established")
        if self._receive_task is not None and not self._receive_task.done():
            raise RuntimeError("Connection background tasks are already running")

        self._receive_task = asyncio.create_task(
            self.recv_loop(on_pdu), name="mtgnp-client-receive"
        )
        self._heartbeat_task = asyncio.create_task(
            self.heartbeat_loop(), name="mtgnp-client-heartbeat"
        )

    async def send(self, pdu: AnyPDU) -> None:
        """Serialize, frame, and send one PDU."""
        if not self.connected or self.writer is None:
            raise ConnectionError("Connection not established or closed")

        payload = pdu.model_dump_json().encode("utf-8")
        frame = encode_frame(payload)
        self._log("C->S", payload)

        try:
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, OSError) as exc:
            raise ConnectionError("Failed to send PDU") from exc

    async def recv_loop(self, on_pdu: PDUCallback) -> None:
        """Read framed PDUs until the server closes the stream."""
        if self.reader is None:
            raise ConnectionError("Connection not established")

        try:
            while True:
                payload = await self._read_frame()
                self._log("S->C", payload)

                try:
                    pdu = _PDU_ADAPTER.validate_json(payload)
                except ValidationError as exc:
                    if self.verbose:
                        print(f"[PARSE ERROR] {exc}")
                    continue

                if isinstance(pdu, Pong):
                    self.on_pong_received(pdu)

                callback_result = on_pdu(pdu)
                if inspect.isawaitable(callback_result):
                    await callback_result
        except asyncio.IncompleteReadError:
            if self.verbose:
                print("[DISCONNECTED] Server closed connection")
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError, ValueError) as exc:
            if self.verbose:
                print(f"[CONNECTION ERROR] {exc}")
        finally:
            self._closed_event.set()

    async def _read_frame(self) -> bytes:
        """Read one complete 4-byte-length-prefixed JSON payload."""
        if self.reader is None:
            raise ConnectionError("Reader not established")

        prefix = await self.reader.readexactly(LENGTH_PREFIX_BYTES)
        length = decode_length_prefix(prefix)
        if length > MAX_PDU_BYTES:
            raise ValueError(
                f"Frame length {length} exceeds MAX_PDU_BYTES ({MAX_PDU_BYTES})"
            )
        return await self.reader.readexactly(length)

    async def heartbeat_loop(self) -> None:
        """Send PING periodically and close on a missing matching PONG."""
        try:
            while self.connected:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                if not self.connected:
                    break

                self._heartbeat_seq_num += 1
                timestamp = int(time.time() * 1000)
                ping = Ping(
                    seq_num=self._heartbeat_seq_num,
                    timestamp=timestamp,
                )

                self._pending_ping = (ping.seq_num, ping.timestamp)
                self._pong_event.clear()
                await self.send(ping)

                try:
                    await asyncio.wait_for(
                        self._pong_event.wait(), timeout=HEARTBEAT_TIMEOUT_S
                    )
                except asyncio.TimeoutError:
                    if self.verbose:
                        print(
                            "[HEARTBEAT TIMEOUT] No matching PONG received; "
                            "disconnecting"
                        )
                    await self.close()
                    return
                finally:
                    self._pending_ping = None
        except asyncio.CancelledError:
            raise

    def on_pong_received(self, pong: Pong) -> None:
        """Accept only the PONG matching the currently outstanding PING."""
        if self._pending_ping == (pong.seq_num, pong.timestamp):
            self._pong_event.set()
        elif self.verbose:
            print(
                "[HEARTBEAT] Ignored unmatched PONG "
                f"seq_num={pong.seq_num} timestamp={pong.timestamp}"
            )

    async def wait_closed(self) -> None:
        """Wait until the receive loop observes that the stream has closed."""
        await self._closed_event.wait()

    async def close(self) -> None:
        """Cancel background tasks and close the TCP writer cleanly."""
        current = asyncio.current_task()
        tasks = [self._heartbeat_task, self._receive_task]
        for task in tasks:
            if task is not None and task is not current and not task.done():
                task.cancel()

        if self.writer is not None and not self.writer.is_closing():
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (ConnectionError, OSError):
                pass

        pending = [
            task
            for task in tasks
            if task is not None and task is not current and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        self._closed_event.set()

    def _log(self, direction: str, payload: bytes) -> None:
        if not self.verbose:
            return
        try:
            rendered = json.dumps(json.loads(payload), separators=(",", ":"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            rendered = repr(payload)
        print(f"[{direction}] {rendered}")
