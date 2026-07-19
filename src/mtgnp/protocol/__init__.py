"""Shared protocol core — the anti-drift firewall.

Both `mtgnp.server` and `mtgnp.client` import from here and agree ONLY through
this package. Neither imports the other. Anything that crosses the wire (framing,
PDU schemas, error codes, wire constants, card catalog) lives here so the two
sides can never disagree on the format.
"""
