"""Controller: turn human intent into action PDUs.

Prompts the player for the choice the server is currently asking for (cast / pass
/ play land / attack / block / mulligan / discard / trigger order/choice) and
builds the corresponding PDU, echoing the correct seq_num per RFC §5.4. A headless
variant reads actions from a script file instead of prompting — same interface —
enabling automated interop and E2E tests (used by tests/transport).
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from mtgnp.protocol.catalog import base_id, load_catalog
from mtgnp.protocol.pdus import (
    AnyPDU,
    AssignDamageOrder,
    CastSpell,
    Concede,
    DeclareAttackers,
    DeclareBlockers,
    Discard,
    MulliganChoice,
    PlayLand,
    PriorityPass,
    TriggerChoiceResponse,
    TriggerOrderResponse,
    AttackerDeclaration,
    BlockerDeclaration,
)


class InputController(ABC):
    """Protocol for controllers that produce action PDUs from player intent."""

    @abstractmethod
    async def next_action(self, visible_state: dict[str, Any], prompt: str, seq_num: int) -> AnyPDU:
        """Prompt for the next player action and return the corresponding PDU.
        
        Args:
            visible_state: Current game state visible to this player
            prompt: Human-readable prompt describing what action is needed
            seq_num: The current priority token to echo in the PDU
        
        Returns:
            A PDU ready to send to the server (with seq_num already set)
        """
        ...


class CLIController(InputController):
    """Interactive CLI controller: prompts player for input and builds PDUs."""

    def __init__(self) -> None:
        self.catalog = load_catalog()

    async def next_action(self, visible_state: dict[str, Any], prompt: str, seq_num: int) -> AnyPDU:
        """Prompt the player interactively and return a PDU."""
        # Run the blocking input in a thread to avoid blocking the event loop
        user_input = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input(f"\n{prompt}\n> ").strip().lower()
        )

        # Parse the input and return the appropriate PDU
        return await self._parse_user_input(user_input, visible_state, seq_num, prompt)

    async def _parse_user_input(
        self, user_input: str, visible_state: dict[str, Any], seq_num: int, prompt: str
    ) -> AnyPDU:
        """Parse user input and build the corresponding PDU."""
        tokens = user_input.split()

        if not tokens:
            # Default to pass on empty input during priority
            if "priority" in prompt.lower() or "action" in prompt.lower():
                return PriorityPass(seq_num=seq_num)
            return await self.next_action(visible_state, "Invalid input. Please try again.", seq_num)

        action = tokens[0]

        # Mulligan phase
        if action in ("keep", "mulligan"):
            return MulliganChoice(
                seq_num=seq_num,
                keep=(action == "keep"),
                cards_to_bottom=tokens[1:] if action == "keep" else [],
            )

        # Priority phase: pass
        if action == "pass":
            return PriorityPass(seq_num=seq_num)

        # Priority phase: cast spell
        if action == "cast":
            if len(tokens) < 2:
                return await self.next_action(
                    visible_state, "Usage: cast <card_id> [target1 target2 ...] [kicked]", seq_num
                )
            card_id = tokens[1]
            kicked = "kicked" in tokens[2:]
            targets = [token for token in tokens[2:] if token != "kicked"]
            card = self.catalog.get(base_id(card_id))
            if card is None:
                return await self.next_action(
                    visible_state, f"Unknown card id: {card_id}", seq_num
                )

            mana_payment = dict(card.mana_cost)
            if kicked and card.kicker_cost is not None:
                for color, amount in card.kicker_cost.items():
                    mana_payment[color] = mana_payment.get(color, 0) + amount

            return CastSpell(
                seq_num=seq_num,
                card_id=card_id,
                targets=targets,
                mana_payment=mana_payment,
                kicked=kicked,
            )

        # Priority phase: play land
        if action == "play":
            if len(tokens) < 2:
                return await self.next_action(
                    visible_state, "Usage: play <card_id>", seq_num
                )
            card_id = tokens[1]
            return PlayLand(seq_num=seq_num, card_id=card_id)

        # Combat: declare attackers
        if action == "attack":
            # Format: attack <creature_id> <target> [<creature_id> <target> ...]
            attackers = []
            for i in range(1, len(tokens), 2):
                if i + 1 < len(tokens):
                    attackers.append(AttackerDeclaration(
                        creature_id=tokens[i],
                        target=tokens[i + 1]
                    ))
            return DeclareAttackers(seq_num=seq_num, attackers=attackers)

        # Combat: declare blockers
        if action == "block":
            # Format: block <creature_id> <blocking_id> [<creature_id> <blocking_id> ...]
            blockers = []
            for i in range(1, len(tokens), 2):
                if i + 1 < len(tokens):
                    blockers.append(BlockerDeclaration(
                        creature_id=tokens[i],
                        blocking_id=tokens[i + 1]
                    ))
            return DeclareBlockers(seq_num=seq_num, blockers=blockers)

        # Damage order assignment
        if action == "assign":
            if len(tokens) < 3:
                return await self.next_action(
                    visible_state, "Usage: assign <attacker_id> <blocker1> [<blocker2> ...]", seq_num
                )
            attacker_id = tokens[1]
            blocker_order = tokens[2:]
            return AssignDamageOrder(seq_num=seq_num, attacker_id=attacker_id, blocker_order=blocker_order)

        # Discard
        if action == "discard":
            card_ids = tokens[1:]
            if not card_ids:
                return await self.next_action(
                    visible_state, "Usage: discard <card_id> [<card_id> ...]", seq_num
                )
            return Discard(seq_num=seq_num, card_ids=card_ids)

        # Trigger ordering
        if action == "order":
            trigger_ids = tokens[1:]
            if not trigger_ids:
                return await self.next_action(
                    visible_state, "Usage: order <trigger_id> [<trigger_id> ...]", seq_num
                )
            return TriggerOrderResponse(seq_num=seq_num, ordered_trigger_ids=trigger_ids)

        # Trigger choice
        if action == "trigger":
            if len(tokens) < 2:
                return await self.next_action(
                    visible_state, "Usage: trigger <trigger_id> [accept|decline] [target]", seq_num
                )
            trigger_id = tokens[1]
            accept = len(tokens) < 3 or tokens[2].lower() == "accept"
            chosen_target = tokens[3] if len(tokens) > 3 else None
            return TriggerChoiceResponse(
                seq_num=seq_num,
                trigger_id=trigger_id,
                accept=accept,
                chosen_target=chosen_target
            )

        # Concede
        if action == "concede":
            player_id = visible_state.get("your_player_id", "unknown")
            return Concede(seq_num=seq_num, player_id=player_id)

        # Unknown command
        return await self.next_action(
            visible_state,
            f"Unknown action '{action}'. Try: keep, mulligan, pass, cast, play, attack, block, discard, trigger, concede",
            seq_num
        )


class ScriptController(InputController):
    """Headless script controller: reads pre-recorded actions from a JSON file."""

    def __init__(self, script_path: str):
        self.script_path = script_path
        self.actions: list[dict[str, Any]] = []
        self.action_index = 0

    async def load_script(self) -> None:
        """Load the script file into memory."""
        try:
            with open(self.script_path, "r") as f:
                self.actions = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to load script '{self.script_path}': {e}") from e

    async def next_action(self, visible_state: dict[str, Any], prompt: str, seq_num: int) -> AnyPDU:
        """Return the next action from the loaded script."""
        if self.action_index >= len(self.actions):
            raise RuntimeError("Script exhausted: no more actions available")

        action_spec = self.actions[self.action_index]
        self.action_index += 1

        return await self._build_pdu_from_script(action_spec, seq_num, visible_state)

    async def _build_pdu_from_script(
        self, action_spec: dict[str, Any], seq_num: int, visible_state: dict[str, Any]
    ) -> AnyPDU:
        """Build a PDU from a script action specification."""
        action_type = action_spec.get("action", "").upper()

        if action_type == "PLAYER_READY":
            from mtgnp.protocol.pdus import PlayerReady
            player_id = action_spec.get("player_id", "Player1")
            deck_list = action_spec.get("deck", [])
            return PlayerReady(seq_num=seq_num, player_id=player_id, deck_list=deck_list)

        if action_type == "MULLIGAN_CHOICE":
            keep = action_spec.get("keep", True)
            cards_to_bottom = action_spec.get("cards_to_bottom", [])
            return MulliganChoice(seq_num=seq_num, keep=keep, cards_to_bottom=cards_to_bottom)

        if action_type == "PASS_PRIORITY":
            return PriorityPass(seq_num=seq_num)

        if action_type == "CAST_SPELL":
            card_id = action_spec.get("card_id", "")
            targets = action_spec.get("targets", [])
            mana_payment = action_spec.get("mana_payment", {})
            kicked = action_spec.get("kicked", False)
            return CastSpell(seq_num=seq_num, card_id=card_id, targets=targets, mana_payment=mana_payment, kicked=kicked)

        if action_type == "PLAY_LAND":
            card_id = action_spec.get("card_id", "")
            return PlayLand(seq_num=seq_num, card_id=card_id)

        if action_type == "DECLARE_ATTACKERS":
            attackers_spec = action_spec.get("attackers", [])
            attackers = [
                AttackerDeclaration(creature_id=a["creature_id"], target=a["target"])
                for a in attackers_spec
            ]
            return DeclareAttackers(seq_num=seq_num, attackers=attackers)

        if action_type == "DECLARE_BLOCKERS":
            blockers_spec = action_spec.get("blockers", [])
            blockers = [
                BlockerDeclaration(creature_id=b["creature_id"], blocking_id=b["blocking_id"])
                for b in blockers_spec
            ]
            return DeclareBlockers(seq_num=seq_num, blockers=blockers)

        if action_type == "ASSIGN_DAMAGE_ORDER":
            attacker_id = action_spec.get("attacker_id", "")
            blocker_order = action_spec.get("blocker_order", [])
            return AssignDamageOrder(seq_num=seq_num, attacker_id=attacker_id, blocker_order=blocker_order)

        if action_type == "DISCARD":
            card_ids = action_spec.get("card_ids", [])
            return Discard(seq_num=seq_num, card_ids=card_ids)

        if action_type == "TRIGGER_CHOICE_RESPONSE":
            trigger_id = action_spec.get("trigger_id", "")
            accept = action_spec.get("accept", True)
            chosen_target = action_spec.get("chosen_target", None)
            return TriggerChoiceResponse(seq_num=seq_num, trigger_id=trigger_id, accept=accept, chosen_target=chosen_target)

        if action_type == "TRIGGER_ORDER_RESPONSE":
            ordered_trigger_ids = action_spec.get("ordered_trigger_ids", [])
            return TriggerOrderResponse(seq_num=seq_num, ordered_trigger_ids=ordered_trigger_ids)

        if action_type == "CONCEDE":
            player_id = action_spec.get("player_id", visible_state.get("your_player_id", "unknown"))
            return Concede(seq_num=seq_num, player_id=player_id)

        raise ValueError(f"Unknown action type in script: {action_type}")
