"""Terminal renderer for the server-authoritative visible state."""

from __future__ import annotations

from typing import Any

from mtgnp.protocol.catalog import base_id, load_catalog


class Renderer:
    """Render the latest personalized GAME_STATE_UPDATE for one player."""

    def __init__(self) -> None:
        self.catalog = load_catalog()

    def render(self, visible_state: dict[str, Any]) -> str:
        phase = visible_state.get("phase", "UNKNOWN")
        if phase in {"LOBBY", "GAME_SETUP"}:
            return self._render_lobby(visible_state)
        if phase == "MULLIGAN":
            return self._render_mulligan(visible_state)
        return self._render_in_game(visible_state)

    def render_game_over(
        self, winner_id: str, loser_id: str, reason: str, your_player_id: str
    ) -> str:
        result = "YOU WIN" if winner_id == your_player_id else "YOU LOSE"
        return "\n".join(
            [
                "\n" + "=" * 60,
                f"GAME OVER: {result}",
                "=" * 60,
                f"Winner: {winner_id}",
                f"Loser: {loser_id}",
                f"Reason: {reason}",
                "",
            ]
        )

    def render_error(self, code: str, message: str) -> str:
        return f"\n[ERROR {code}] {message}"

    def _render_lobby(self, state: dict[str, Any]) -> str:
        ready = state.get("players_ready", 0)
        waiting = state.get("waiting_for", [])
        lines = [
            "\n" + "=" * 60,
            f"{state.get('phase', 'LOBBY')} - {ready}/2 players ready",
            "=" * 60,
        ]
        if waiting:
            lines.append("Waiting for: " + ", ".join(map(str, waiting)))
        else:
            lines.append("Both players are ready. Setting up the game...")
        lines.append("")
        return "\n".join(lines)

    def _render_mulligan(self, state: dict[str, Any]) -> str:
        your_player_id = state.get("your_player_id", "")
        hand = state.get("hand", [])
        lines = [
            "\n" + "=" * 60,
            "MULLIGAN - Decide whether to keep your opening hand",
            "=" * 60,
        ]
        lines.extend(self._render_life_totals(state, your_player_id))
        lines.append("\nYOUR HAND:")
        lines.extend(self._render_hand(hand))
        lines.append("")
        return "\n".join(lines)

    def _render_in_game(self, state: dict[str, Any]) -> str:
        your_player_id = state.get("your_player_id", "")
        active_player = state.get("active_player", "")
        priority_holder = state.get("priority_holder")
        phase = state.get("phase", "UNKNOWN")
        turn = state.get("turn", 0)

        lines = [
            "\n" + "=" * 60,
            f"Turn {turn} | {phase}",
            f"Active player: {active_player}",
        ]
        if priority_holder:
            lines.append(f"Priority holder: {priority_holder}")
        lines.append("=" * 60)

        lines.extend(self._render_life_totals(state, your_player_id))

        life_totals = state.get("life_totals", {})
        opponent_id = next(
            (pid for pid in life_totals if pid != your_player_id), None
        )
        battlefield = state.get("battlefield", {})

        if opponent_id:
            lines.append(f"\nOPPONENT BATTLEFIELD ({opponent_id}):")
            lines.extend(self._render_battlefield(battlefield.get(opponent_id, [])))

        lines.append("\nYOUR BATTLEFIELD:")
        lines.extend(self._render_battlefield(battlefield.get(your_player_id, [])))

        stack = state.get("stack", [])
        lines.append("\nSTACK (top first):")
        if not stack:
            lines.append("  (empty)")
        else:
            for index, item in enumerate(reversed(stack), 1):
                source = item.get("source", "?")
                item_type = item.get("item_type", "?")
                controller = item.get("controller", "?")
                targets = item.get("targets", [])
                target_text = f" -> {', '.join(targets)}" if targets else ""
                lines.append(
                    f"  {index}. {self._card_name(source)} [{item_type}, "
                    f"controller={controller}]{target_text}"
                )

        lines.append("\nYOUR HAND:")
        lines.extend(self._render_hand(state.get("hand", [])))

        if opponent_id:
            opponent_count = state.get("hand_counts", {}).get(opponent_id, 0)
            lines.append(f"\nOpponent hand: {opponent_count} card(s)")

        library_counts = state.get("library_counts", {})
        if library_counts:
            lines.append(
                "Libraries: "
                + ", ".join(f"{pid}={count}" for pid, count in library_counts.items())
            )

        graveyard = state.get("graveyard", {})
        if graveyard:
            lines.append("Graveyards:")
            for pid, cards in graveyard.items():
                rendered = ", ".join(self._card_name(card) for card in cards)
                lines.append(f"  {pid}: {rendered or '(empty)'}")

        lines.append("")
        return "\n".join(lines)

    def _render_life_totals(
        self, state: dict[str, Any], your_player_id: str
    ) -> list[str]:
        lines = ["\nLIFE TOTALS:"]
        life_totals = state.get("life_totals", {})
        if not life_totals:
            lines.append("  (not initialized)")
            return lines
        for player_id, life in life_totals.items():
            suffix = " (YOU)" if player_id == your_player_id else ""
            lines.append(f"  {player_id}: {life}{suffix}")
        return lines

    def _render_battlefield(self, permanents: list[dict[str, Any]]) -> list[str]:
        if not permanents:
            return ["  (empty)"]
        return [self._render_permanent(permanent) for permanent in permanents]

    def _render_permanent(self, permanent: dict[str, Any]) -> str:
        permanent_id = permanent.get("id", "?")
        name = self._card_name(permanent_id)
        annotations: list[str] = []
        if permanent.get("tapped"):
            annotations.append("TAPPED")
        if permanent.get("summoning_sick"):
            annotations.append("summoning sick")

        power = permanent.get("power")
        toughness = permanent.get("toughness")
        stats = ""
        if power is not None and toughness is not None:
            damage = permanent.get("damage") or 0
            stats = f" {power}/{toughness}"
            if damage:
                stats += f" ({damage} damage)"

        annotation_text = f" [{' | '.join(annotations)}]" if annotations else ""
        return f"  • {name} ({permanent_id}){stats}{annotation_text}"

    def _render_hand(self, hand: list[str]) -> list[str]:
        if not hand:
            return ["  (empty)"]
        return [
            f"  {index}. {self._card_name(card_id)} ({card_id})"
            for index, card_id in enumerate(hand, 1)
        ]

    def _card_name(self, card_id: str) -> str:
        card = self.catalog.get(base_id(card_id))
        return card.name if card else card_id
