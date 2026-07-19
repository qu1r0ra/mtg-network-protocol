"""Server — authoritative engine core (sync) + transport shell (async).

Architecture (ADR 0002): functional core + imperative shell.
  * engine.py + state/lifecycle/turn/priority/stack/combat/effects/sba are a
    SYNCHRONOUS, fully-inspectable state machine. No sockets, no `await`.
  * transport.py is the ONLY async code: sockets, framing, timers, reconnect,
    verbose logging. It feeds bytes/events into the engine and writes back the
    Outbounds the engine returns.

This split makes reconnect/snapshot free, keeps interrupts uniform, and lets the
entire RFC be tested without networking.
"""
