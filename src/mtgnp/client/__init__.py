"""Client — thin, three swappable parts (ADR: CLI client).

  * connection.py  — async framing + PING/PONG heartbeat + receive loop
  * renderer.py    — visible_state -> text  (swap -> curses = TUI bonus)
  * controller.py  — human prompt -> PDU    (swap -> script reader = headless)

The client NEVER computes game outcomes (RFC §4.3); it accepts GAME_STATE_UPDATE
as authoritative and discards any locally computed state. Splitting render/input
from the connection lets a headless scripted controller drive automated interop
and E2E tests without a rewrite.
"""
