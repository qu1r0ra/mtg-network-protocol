"""Server entry point: `mtgnp-server [--host H] [--port 4444] [--verbose]`.

Parses args and runs the asyncio transport shell. --verbose toggles PDU logging
(mandatory for the demo). Wired to pyproject [project.scripts].
"""
from __future__ import annotations

import argparse
import asyncio

from mtgnp.protocol.constants import DEFAULT_PORT
from mtgnp.server.transport import serve


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MTGNP TCP server")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="TCP port to bind"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="log every inbound/outbound PDU"
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(serve(args.host, args.port, verbose=args.verbose))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
