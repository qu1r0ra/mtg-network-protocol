"""Turn/phase driver — walks the fixed 14-phase sequence (RFC §7).

Each phase/step is handled explicitly; the driver advances through the ordered
Phase sequence, opening a PriorityWindow (priority.py) on steps that grant one
and transitioning automatically on those that do not (UNTAP, CLEANUP). Combat is
delegated to combat.py. Turn-1 first player skips the DRAW (RFC §7.4) — written
from the RFC, NOT from examples.md, which self-declares a deviation there (advisor
R3). Cleanup handles >7-card discard, damage/effect clearing, turn++ and AP swap
(RFC §7.8).

Every step-advance routes through sba.resolve (advisor R4) before any priority is
granted.
"""

from __future__ import annotations

# begin_turn(state) -> list[Outbound]                # UNTAP + reset land_played
# advance(state) -> list[Outbound]                   # to next phase/step
# handle_play_land(state, player_id, pdu) -> [...]   # §7.5, retains priority
# handle_discard(state, player_id, pdu) -> [...]     # §7.8 cleanup
