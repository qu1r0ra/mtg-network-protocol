"""MTGNP client entry point and PDU-driven session orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from mtgnp.client.connection import Connection
from mtgnp.client.controller import CLIController, InputController, ScriptController
from mtgnp.client.renderer import Renderer
from mtgnp.protocol.constants import DEFAULT_PORT, MAX_DECK_SIZE, MIN_DECK_SIZE
from mtgnp.protocol.pdus import (
    AnyPDU,
    CombatDamageResult,
    Error,
    GameOver,
    GameStateUpdate,
    MulliganChoice,
    PhaseTransition,
    PlayerReady,
    Pong,
    PriorityGrant,
    StackPush,
    StackResolve,
    TriggerChoice,
    TriggerOrder,
)

_DECLARATION_PHASES = {
    "DECLARE_ATTACKERS",
    "DECLARE_BLOCKERS",
    "ASSIGN_DAMAGE_ORDER",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MTGNP TCP client")
    parser.add_argument("--host", default="127.0.0.1", help="server host address")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="server TCP port"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="log every inbound/outbound PDU"
    )
    parser.add_argument(
        "--script", type=str, default=None, help="headless action script (JSON)"
    )
    parser.add_argument(
        "--player-id",
        type=str,
        default=None,
        help="player id for interactive mode; prompted when omitted",
    )
    parser.add_argument(
        "--deck-file",
        type=str,
        default=None,
        help="JSON file containing a deck array for interactive mode",
    )
    return parser


async def _ainput(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


def _load_deck_file(path: str) -> list[str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load deck file '{path}': {exc}") from exc

    if isinstance(data, dict):
        data = data.get("deck_list", data.get("deck"))
    if not isinstance(data, list) or not all(isinstance(card, str) for card in data):
        raise ValueError("Deck file must contain a JSON array of card-id strings")
    if not MIN_DECK_SIZE <= len(data) <= MAX_DECK_SIZE:
        raise ValueError(
            f"Deck must contain {MIN_DECK_SIZE} to {MAX_DECK_SIZE} cards"
        )
    return data


async def _interactive_ready(
    player_id: str | None, deck_file: str | None, seq_num: int
) -> PlayerReady:
    chosen_id = (player_id or "").strip()
    while not chosen_id:
        chosen_id = (await _ainput("Player ID: ")).strip()

    if deck_file:
        deck = _load_deck_file(deck_file)
    else:
        print(
            "Enter 1-50 card IDs separated by spaces or commas. "
            "You may also paste the path to a .json deck file."
        )
        while True:
            raw = (await _ainput("Deck: ")).strip()
            candidate_path = Path(raw)
            try:
                if candidate_path.suffix.lower() == ".json" and candidate_path.exists():
                    deck = _load_deck_file(str(candidate_path))
                else:
                    deck = [card for card in raw.replace(",", " ").split() if card]
                    if not MIN_DECK_SIZE <= len(deck) <= MAX_DECK_SIZE:
                        raise ValueError(
                            f"Deck must contain {MIN_DECK_SIZE} to {MAX_DECK_SIZE} cards"
                        )
                break
            except ValueError as exc:
                print(f"Invalid deck: {exc}")

    return PlayerReady(seq_num=seq_num, player_id=chosen_id, deck_list=deck)


async def _initial_ready(
    controller: InputController,
    player_id: str | None,
    deck_file: str | None,
    seq_num: int,
) -> PlayerReady:
    if isinstance(controller, ScriptController):
        await controller.load_script()
        action = await controller.next_action({}, "Initial PLAYER_READY", seq_num)
        if not isinstance(action, PlayerReady):
            raise ValueError("The first scripted action must be PLAYER_READY")
        return action
    return await _interactive_ready(player_id, deck_file, seq_num)


async def _next_pdu(
    queue: asyncio.Queue[AnyPDU], closed_task: asyncio.Task[None]
) -> AnyPDU | None:
    receive = asyncio.create_task(queue.get())
    done, _ = await asyncio.wait(
        {receive, closed_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if receive in done:
        return receive.result()
    receive.cancel()
    await asyncio.gather(receive, return_exceptions=True)
    return None


def _priority_prompt(state: dict[str, Any]) -> str:
    phase = state.get("phase", "UNKNOWN")
    return (
        f"You hold priority during {phase}. Commands: pass, play <card_id>, "
        "cast <card_id> [target ...] [kicked], or concede."
    )


def _declaration_prompt(phase: str) -> str:
    if phase == "DECLARE_ATTACKERS":
        return (
            "Declare attackers: attack <creature_id> <opponent_id> [...]. "
            "Type 'attack' alone for no attackers."
        )
    if phase == "DECLARE_BLOCKERS":
        return (
            "Declare blockers: block <blocker_id> <attacker_id> [...]. "
            "Type 'block' alone for no blockers."
        )
    return "Assign damage: assign <attacker_id> <blocker1> [blocker2 ...]."


async def run_client(
    host: str,
    port: int,
    verbose: bool,
    script: str | None,
    player_id: str | None = None,
    deck_file: str | None = None,
) -> None:
    """Connect, send PLAYER_READY, then react to authoritative server PDUs."""
    connection = Connection(host=host, port=port, verbose=verbose)
    renderer = Renderer()
    controller: InputController = (
        ScriptController(script_path=script) if script else CLIController()
    )

    ready_seq = 1
    ready = await _initial_ready(controller, player_id, deck_file, ready_seq)
    own_player_id = ready.player_id
    saved_deck = list(ready.deck_list)

    queue: asyncio.Queue[AnyPDU] = asyncio.Queue()
    visible_state: dict[str, Any] = {"your_player_id": own_player_id}
    current_priority_token: int | None = None
    mulligan_request_seq: int | None = None
    mulligan_count = 0
    declaration_pending: str | None = None

    async def send_action(prompt: str, seq_num: int) -> AnyPDU:
        action = await controller.next_action(visible_state, prompt, seq_num)
        await connection.send(action)
        return action

    await connection.connect()
    connection.start(queue.put_nowait)
    closed_task = asyncio.create_task(connection.wait_closed())

    try:
        await connection.send(ready)

        while True:
            pdu = await _next_pdu(queue, closed_task)
            if pdu is None:
                print("Connection closed.")
                break

            if isinstance(pdu, GameStateUpdate):
                visible_state = dict(pdu.state)
                visible_state["your_player_id"] = own_player_id
                print(renderer.render(visible_state))

                phase = visible_state.get("phase")
                if phase == "MULLIGAN":
                    mulligan_request_seq = pdu.seq_num
                    bottom_note = (
                        f" If keeping, list exactly {mulligan_count} card ID(s) "
                        "after 'keep'."
                        if mulligan_count
                        else ""
                    )
                    action = await send_action(
                        "Choose 'keep' or 'mulligan'." + bottom_note,
                        pdu.seq_num,
                    )
                    if isinstance(action, MulliganChoice) and not action.keep:
                        mulligan_count += 1
                    continue

                if (
                    phase == "CLEANUP"
                    and visible_state.get("active_player") == own_player_id
                    and len(visible_state.get("hand", [])) > 7
                ):
                    await send_action(
                        "Discard down to seven: discard <card_id> [card_id ...]",
                        pdu.seq_num,
                    )
                continue

            if isinstance(pdu, PhaseTransition):
                visible_state.update(
                    {
                        "phase": pdu.to_phase,
                        "active_player": pdu.active_player,
                        "turn": pdu.turn,
                        "your_player_id": own_player_id,
                    }
                )
                visible_state.pop("priority_holder", None)
                current_priority_token = None
                declaration_pending = (
                    pdu.to_phase if pdu.to_phase in _DECLARATION_PHASES else None
                )
                print(
                    f"\n[PHASE] Turn {pdu.turn}: "
                    f"{pdu.from_phase} -> {pdu.to_phase}"
                )
                continue

            if isinstance(pdu, PriorityGrant):
                visible_state["priority_holder"] = pdu.player_id
                if pdu.player_id != own_player_id:
                    current_priority_token = None
                    continue

                current_priority_token = pdu.seq_num
                if declaration_pending:
                    phase = declaration_pending
                    await send_action(_declaration_prompt(phase), pdu.seq_num)
                    declaration_pending = None
                    visible_state.pop("priority_holder", None)
                else:
                    await send_action(_priority_prompt(visible_state), pdu.seq_num)
                    visible_state.pop("priority_holder", None)
                continue

            if isinstance(pdu, TriggerChoice):
                target_note = (
                    f" Legal targets: {', '.join(pdu.legal_targets)}."
                    if pdu.legal_targets
                    else ""
                )
                await send_action(
                    f"Trigger {pdu.trigger_id}: {pdu.effect_summary}. "
                    "Use: trigger <trigger_id> accept|decline [target]."
                    + target_note,
                    pdu.seq_num,
                )
                continue

            if isinstance(pdu, TriggerOrder):
                await send_action(
                    "Order simultaneous triggers using: order "
                    + " ".join(pdu.trigger_ids),
                    pdu.seq_num,
                )
                continue

            if isinstance(pdu, Error):
                print(renderer.render_error(pdu.code, pdu.message))
                rejected_type = (pdu.rejected_action or {}).get("type")
                if rejected_type == "MULLIGAN_CHOICE" and mulligan_request_seq:
                    action = await send_action(
                        "Retry mulligan choice. Use 'mulligan' or "
                        f"'keep <{mulligan_count} card id(s)>'.",
                        mulligan_request_seq,
                    )
                    if isinstance(action, MulliganChoice) and not action.keep:
                        mulligan_count += 1
                elif rejected_type in {
                    "PRIORITY_PASS",
                    "CAST_SPELL",
                    "PLAY_LAND",
                    "DECLARE_ATTACKERS",
                    "DECLARE_BLOCKERS",
                    "ASSIGN_DAMAGE_ORDER",
                } and current_priority_token is not None:
                    await send_action(
                        _declaration_prompt(visible_state.get("phase"))
                        if visible_state.get("phase") in _DECLARATION_PHASES
                        else _priority_prompt(visible_state),
                        current_priority_token,
                    )
                continue

            if isinstance(pdu, StackPush):
                print(
                    f"\n[STACK PUSH] {pdu.source} by {pdu.controller} "
                    f"targets={pdu.targets}"
                )
                continue

            if isinstance(pdu, StackResolve):
                print(
                    f"\n[STACK {pdu.result}] {pdu.stack_item_id}: "
                    f"{pdu.state_changes}"
                )
                continue

            if isinstance(pdu, CombatDamageResult):
                events = ", ".join(
                    f"{event.source}->{event.target}: {event.amount}"
                    for event in pdu.damage_events
                )
                print(f"\n[COMBAT DAMAGE] {events or 'No damage'}")
                continue

            if isinstance(pdu, GameOver):
                print(
                    renderer.render_game_over(
                        pdu.winner_id,
                        pdu.loser_id,
                        pdu.reason,
                        own_player_id,
                    )
                )

                if isinstance(controller, ScriptController):
                    try:
                        ready_seq += 1
                        next_ready = await controller.next_action(
                            visible_state, "New PLAYER_READY", ready_seq
                        )
                    except RuntimeError:
                        break
                    if not isinstance(next_ready, PlayerReady):
                        raise ValueError(
                            "After GAME_OVER, the next scripted action must be PLAYER_READY"
                        )
                    ready = next_ready
                    own_player_id = ready.player_id
                    saved_deck = list(ready.deck_list)
                else:
                    answer = (await _ainput("Play another game? [y/N]: ")).strip().lower()
                    if answer not in {"y", "yes"}:
                        break
                    ready_seq += 1
                    ready = PlayerReady(
                        seq_num=ready_seq,
                        player_id=own_player_id,
                        deck_list=saved_deck,
                    )

                visible_state = {"your_player_id": own_player_id}
                current_priority_token = None
                declaration_pending = None
                mulligan_count = 0
                await connection.send(ready)
                continue

    finally:
        closed_task.cancel()
        await asyncio.gather(closed_task, return_exceptions=True)
        await connection.close()


def main() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(
            run_client(
                args.host,
                args.port,
                args.verbose,
                args.script,
                args.player_id,
                args.deck_file,
            )
        )
    except (ConnectionError, ValueError, RuntimeError) as exc:
        print(f"Client error: {exc}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
