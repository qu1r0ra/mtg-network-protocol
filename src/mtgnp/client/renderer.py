"""Renderer: authoritative visible_state -> human-readable text.

Renders life totals, battlefield, hand, stack, phase/priority from the latest
GAME_STATE_UPDATE (the sole source of truth). Uses the shared catalog to show
names / power / toughness for card ids. Swappable: a curses/textual renderer is
the TUI bonus and only replaces this module.
"""

from __future__ import annotations

from typing import Any

from mtgnp.protocol.catalog import Card, base_id, load_catalog


class Renderer:
    """Renders game state to human-readable terminal text."""

    def __init__(self):
        self.catalog = load_catalog()

    def render(self, visible_state: dict[str, Any]) -> str:
        """Render the visible game state as formatted text.
        
        Args:
            visible_state: The game state dict from GAME_STATE_UPDATE
        
        Returns:
            Formatted string ready to print to terminal
        """
        lines = []

        # Determine current lifecycle phase
        lifecycle = visible_state.get("lifecycle", "UNKNOWN")
        lines.append(f"\n{'='*60}")
        lines.append(f"Lifecycle: {lifecycle}")
        lines.append(f"{'='*60}")

        # Render lobby state
        if lifecycle == "LOBBY":
            return self._render_lobby(visible_state)

        # Render mulligan state
        if lifecycle == "MULLIGAN":
            return self._render_mulligan(visible_state)

        # Render in-game state
        if lifecycle == "IN_GAME":
            return self._render_in_game(visible_state)

        # Render game over state
        if lifecycle == "GAME_OVER":
            return self._render_game_over(visible_state)

        return "\n".join(lines)

    def _render_lobby(self, state: dict[str, Any]) -> str:
        """Render the lobby state (waiting for players to join)."""
        lines = ["\n" + "="*60, "LOBBY - Waiting for players to join", "="*60]
        
        players = state.get("players", {})
        for player_id, player_info in players.items():
            life = player_info.get("life", 20)
            lines.append(f"  {player_id}: Life={life}")
        
        lines.append("")
        return "\n".join(lines)

    def _render_mulligan(self, state: dict[str, Any]) -> str:
        """Render the mulligan phase (opening hand decision)."""
        lines = ["\n" + "="*60, "MULLIGAN - Decide on opening hand", "="*60]

        your_player_id = state.get("your_player_id", "")
        your_hand = state.get("your_hand", [])

        lines.append("\nYour opening hand:")
        lines.extend(self._render_hand(your_hand))

        lines.append("\nCommand: 'keep' or 'mulligan'")
        lines.append("")
        return "\n".join(lines)

    def _render_in_game(self, state: dict[str, Any]) -> str:
        """Render the main game state (battlefield, hand, stack, priority)."""
        lines = []

        # Turn and phase info
        turn = state.get("turn", 0)
        phase = state.get("phase", "UNKNOWN")
        active_player = state.get("active_player", "")
        priority_holder = state.get("priority_holder", "")
        your_player_id = state.get("your_player_id", "")

        lines.append(f"\n{'='*60}")
        lines.append(f"Turn {turn} - Phase: {phase}")
        lines.append(f"Active Player: {active_player}")
        if priority_holder:
            lines.append(f"Priority: {priority_holder}")
        lines.append(f"{'='*60}\n")

        # Player life totals
        players = state.get("players", {})
        lines.append("LIFE TOTALS:")
        for player_id, player_info in players.items():
            life = player_info.get("life", 20)
            is_you = " (YOU)" if player_id == your_player_id else ""
            lines.append(f"  {player_id}: {life}{is_you}")
        lines.append("")

        # Opponent battlefield (public info)
        opponent_id = next(
            (pid for pid in players.keys() if pid != your_player_id), None
        )
        if opponent_id and opponent_id in players:
            opponent_battlefield = players[opponent_id].get("battlefield", [])
            if opponent_battlefield:
                lines.append(f"OPPONENT BATTLEFIELD ({opponent_id}):")
                for perm in opponent_battlefield:
                    lines.append(self._render_permanent(perm))
                lines.append("")

        # Your battlefield
        your_player = players.get(your_player_id, {})
        your_battlefield = your_player.get("battlefield", [])
        if your_battlefield:
            lines.append("YOUR BATTLEFIELD:")
            for perm in your_battlefield:
                lines.append(self._render_permanent(perm))
            lines.append("")

        # Stack
        stack = state.get("stack", [])
        if stack:
            lines.append("STACK (top to bottom):")
            for i, item in enumerate(reversed(stack), 1):  # Reverse to show top first
                source = item.get("source_id", "?")
                item_type = item.get("item_type", "?")
                controller = item.get("controller_id", "?")
                lines.append(f"  {i}. {self._card_name(source)} ({item_type}) [ctrl: {controller}]")
            lines.append("")

        # Your hand
        your_hand = your_player.get("hand", [])
        if your_hand:
            lines.append("YOUR HAND:")
            lines.extend(self._render_hand(your_hand))
            lines.append("")

        # Opponent hand count (hidden info)
        if opponent_id and opponent_id in players:
            opponent_hand_count = len(players[opponent_id].get("hand", []))
            lines.append(f"Opponent hand size: {opponent_hand_count} cards\n")

        return "\n".join(lines)

    def _render_game_over(self, state: dict[str, Any]) -> str:
        """Render the game over state."""
        lines = ["\n" + "="*60, "GAME OVER", "="*60]

        winner = state.get("winner_id", "")
        loser = state.get("loser_id", "")
        reason = state.get("reason", "UNKNOWN")

        lines.append(f"\nWinner: {winner}")
        lines.append(f"Loser: {loser}")
        lines.append(f"Reason: {reason}\n")

        return "\n".join(lines)

    def _render_permanent(self, perm: dict[str, Any]) -> str:
        """Render a single permanent on the battlefield."""
        perm_id = perm.get("id", "?")
        name = self._card_name(perm_id)
        tapped = " [TAPPED]" if perm.get("tapped", False) else ""
        
        # Creature stats
        power = perm.get("power")
        toughness = perm.get("toughness")
        damage = perm.get("damage", 0)
        
        if power is not None and toughness is not None:
            effective_toughness = (toughness or 0) - (damage or 0)
            stats = f"({power}/{effective_toughness})"
            if damage and damage > 0:
                stats += f" [damage: {damage}]"
        else:
            stats = ""

        # Keywords
        keywords = []
        if perm.get("haste") or perm.get("temp_haste"):
            keywords.append("Haste")
        if perm.get("first_strike"):
            keywords.append("First Strike")
        if perm.get("double_strike"):
            keywords.append("Double Strike")
        if perm.get("summoning_sick"):
            keywords.append("Summoning Sick")
        keyword_str = f" [{', '.join(keywords)}]" if keywords else ""

        return f"  • {name} {stats}{tapped}{keyword_str}"

    def _render_hand(self, hand: list[str]) -> list[str]:
        """Render the cards in hand as a list of lines."""
        lines = []
        for i, card_id in enumerate(hand, 1):
            card_name = self._card_name(card_id)
            lines.append(f"  {i}. {card_name} ({card_id})")
        return lines

    def _card_name(self, card_id: str) -> str:
        """Look up a card's name from the catalog by instance id."""
        bid = base_id(card_id)
        card = self.catalog.get(bid)
        if card:
            return card.name
        return card_id
