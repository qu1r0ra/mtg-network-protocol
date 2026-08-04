"""Client entry point:
`mtgnp-client [--host H] [--port 4444] [--verbose] [--script FILE]`.

Wires Connection + Renderer + (CLI or Script) Controller and runs the event loop.
--verbose toggles PDU logging (mandatory for the demo); --script selects the
headless controller for automated play. Wired to pyproject [project.scripts].
"""

from __future__ import annotations

import argparse
import asyncio

from mtgnp.protocol.constants import DEFAULT_PORT
from mtgnp.client.connection import Connection
from mtgnp.client.renderer import Renderer
from mtgnp.client.controller import CLIController, ScriptController


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
        "--script", type=str, default=None, help="path to headless script file (JSON)"
    )
    return parser


async def run_client(host: str, port: int, verbose: bool, script: str | None) -> None:
    """Wire and run the client: Connection + Renderer + Controller."""
    connection = Connection(host=host, port=port, verbose=verbose)
    renderer = Renderer()
    controller = (
        ScriptController(script_path=script)
        if script
        else CLIController()
    )
    
    # TODO: Implement client orchestration
    # - Connect to server
    # - Start heartbeat & receive loop
    # - Drive interaction loop (receive state -> render -> prompt -> send action)


def main() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(run_client(args.host, args.port, args.verbose, args.script))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
