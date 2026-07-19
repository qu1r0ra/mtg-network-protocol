"""Renderer: authoritative visible_state -> human-readable text.

Renders life totals, battlefield, hand, stack, phase/priority from the latest
GAME_STATE_UPDATE (the sole source of truth). Uses the shared catalog to show
names / power / toughness for card ids. Swappable: a curses/textual renderer is
the TUI bonus and only replaces this module.
"""

from __future__ import annotations

# class Renderer:
#     def render(self, visible_state) -> str: ...
