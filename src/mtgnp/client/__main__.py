"""Client entry point:
`mtgnp-client [--host H] [--port 4444] [--verbose] [--script FILE]`.

Wires Connection + Renderer + (CLI or Script) Controller and runs the event loop.
--verbose toggles PDU logging (mandatory for the demo); --script selects the
headless controller for automated play. Wired to pyproject [project.scripts].
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
