"""Async TCP transport shell for the authoritative game engine.

This module owns sockets and wall-clock timers.  Game rules, sequence numbers,
validation, and visibility filtering remain in :class:`GameEngine`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterable

from mtgnp.protocol.constants import (
    DEFAULT_PORT,
    LENGTH_PREFIX_BYTES,
    MAX_PDU_BYTES,
    MAX_PLAYERS,
    RECONNECT_TIMEOUT_S,
)
from mtgnp.protocol.framing import decode_length_prefix, encode_frame
from mtgnp.protocol.pdus import PriorityGrant
from mtgnp.server.engine import GameEngine, Outbound
from mtgnp.server.state import Lifecycle


class TransportServer:
    """Own one engine and expose it to at most two TCP connections."""

    def __init__(self, *, verbose: bool = False, engine: GameEngine | None = None):
        self.verbose = verbose
        self.engine = engine or GameEngine()
        self.writers: dict[str, asyncio.StreamWriter] = {}
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._reconnect_tasks: dict[str, asyncio.Task[None]] = {}
        self._priority_task: asyncio.Task[None] | None = None
        self._server: asyncio.AbstractServer | None = None

    async def start(self, host: str, port: int) -> asyncio.AbstractServer:
        self._server = await asyncio.start_server(self._accept, host, port)
        return self._server

    async def serve_forever(self, host: str, port: int) -> None:
        server = await self.start(host, port)
        addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        print(f"MTGNP server listening on {addresses}")
        async with server:
            await server.serve_forever()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

        tasks = [*self._client_tasks, *self._reconnect_tasks.values()]
        if self._priority_task is not None:
            tasks.append(self._priority_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        writers = list(self.writers.values())
        self.writers.clear()
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)

        slot = self._available_slot()
        if slot is None:
            if self.verbose:
                print(f"[REFUSED] {writer.get_extra_info('peername')}: server full")
            writer.close()
            await writer.wait_closed()
            if task is not None:
                self._client_tasks.discard(task)
            return

        self.writers[slot] = writer
        claimed_id = self.engine.state.connections.get(slot)
        if claimed_id and claimed_id in self.engine.state.players:
            reconnect_task = self._reconnect_tasks.pop(slot, None)
            if reconnect_task is not None:
                reconnect_task.cancel()
            await self._emit(self.engine.on_reconnect(claimed_id))

        if self.verbose:
            print(f"[CONNECTED] {slot} <- {writer.get_extra_info('peername')}")

        try:
            while True:
                payload = await _read_frame(reader)
                self._log("C->S", slot, payload)
                await self._emit(self.engine.handle(slot, payload))
        except asyncio.IncompleteReadError:
            pass
        except ValueError as exc:
            if self.verbose:
                print(f"[PROTOCOL ERROR] {slot}: {exc}")
        except (ConnectionError, OSError) as exc:
            if self.verbose:
                print(f"[CONNECTION ERROR] {slot}: {exc}")
        finally:
            # A replaced/reconnected writer must not tear down its successor.
            if self.writers.get(slot) is writer:
                self.writers.pop(slot, None)
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                await self._handle_disconnect(slot)
            if task is not None:
                self._client_tasks.discard(task)
            if self.verbose:
                print(f"[DISCONNECTED] {slot}")

    def _available_slot(self) -> str | None:
        for number in range(1, MAX_PLAYERS + 1):
            slot = f"player_{number}"
            if slot not in self.writers:
                return slot
        return None

    async def _emit(self, outbounds: Iterable[Outbound]) -> None:
        for outbound in outbounds:
            recipients = (
                list(self.writers)
                if outbound.recipient == "ALL"
                else [outbound.recipient]
            )
            payload = outbound.pdu.model_dump_json().encode("utf-8")
            frame = encode_frame(payload)
            for slot in recipients:
                writer = self.writers.get(slot)
                if writer is None or writer.is_closing():
                    continue
                self._log("S->C", slot, payload)
                try:
                    writer.write(frame)
                    await writer.drain()
                except (ConnectionError, OSError):
                    # The connection coroutine observes the same failure/EOF and
                    # performs the single authoritative disconnect transition.
                    writer.close()

            if isinstance(outbound.pdu, PriorityGrant):
                self._schedule_priority_timeout(outbound.pdu)

    def _schedule_priority_timeout(self, grant: PriorityGrant) -> None:
        if self._priority_task is not None:
            self._priority_task.cancel()
        self._priority_task = asyncio.create_task(
            self._priority_timeout(
                grant.player_id, grant.seq_num, grant.time_limit_ms / 1000
            )
        )

    async def _priority_timeout(
        self, player_id: str, token: int, delay: float
    ) -> None:
        try:
            await asyncio.sleep(delay)
            if (
                self.engine.state.priority_holder == player_id
                and self.engine.state.priority_token == token
            ):
                await self._emit(self.engine.on_priority_timeout(player_id))
        except asyncio.CancelledError:
            raise

    async def _handle_disconnect(self, slot: str) -> None:
        claimed_id = self.engine.state.connections.get(slot)
        if claimed_id is None or claimed_id not in self.engine.state.players:
            return
        # No game exists yet, so release a lone abandoned lobby claim.  The
        # engine's game-disconnect path expects two players so it can identify
        # a winner and loser.
        if (
            self.engine.state.lifecycle is Lifecycle.LOBBY
            and len(self.engine.state.players) < 2
        ):
            self.engine.state.connections[slot] = None
            self.engine.state.players.pop(claimed_id, None)
            return
        await self._emit(self.engine.on_disconnect(claimed_id))
        old_task = self._reconnect_tasks.pop(slot, None)
        if old_task is not None:
            old_task.cancel()
        self._reconnect_tasks[slot] = asyncio.create_task(
            self._reconnect_timeout(slot, claimed_id)
        )

    async def _reconnect_timeout(self, slot: str, player_id: str) -> None:
        try:
            await asyncio.sleep(RECONNECT_TIMEOUT_S)
            if slot not in self.writers:
                player = self.engine.state.players.get(player_id)
                if player is not None and not player.connected:
                    await self._emit(self.engine.on_disconnect(player_id))
        except asyncio.CancelledError:
            raise
        finally:
            if self._reconnect_tasks.get(slot) is asyncio.current_task():
                self._reconnect_tasks.pop(slot, None)

    def _log(self, direction: str, slot: str, payload: bytes) -> None:
        if not self.verbose:
            return
        try:
            rendered = json.dumps(json.loads(payload), separators=(",", ":"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            rendered = repr(payload)
        print(f"[{direction}] {slot} {rendered}")


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    prefix = await reader.readexactly(LENGTH_PREFIX_BYTES)
    length = decode_length_prefix(prefix)
    if length > MAX_PDU_BYTES:
        raise ValueError(f"frame length {length} exceeds maximum {MAX_PDU_BYTES}")
    return await reader.readexactly(length)


async def serve(
    host: str = "127.0.0.1", port: int = DEFAULT_PORT, *, verbose: bool = False
) -> None:
    """Run an MTGNP server until cancelled."""
    transport = TransportServer(verbose=verbose)
    try:
        await transport.serve_forever(host, port)
    finally:
        await transport.close()
