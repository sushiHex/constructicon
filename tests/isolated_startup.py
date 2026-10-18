"""One synthetic native executable for the isolated startup/publication proof.

The Linux proof selects this peer and a synthetic catalog at the injection root,
using the production lane, launcher methods, relay and store custody. It never
imports the custody/launch doubles used by the portable lane tests, and none of
its replies is private host evidence.
"""

from __future__ import annotations

import json

from tests.substrate.test_codex_protocol import managed, spend_result


def peer_program(plan: str) -> bytes:
    """An in-zone executable that answers only the startup protocol, then EOF."""
    if plan not in {"pro", "plus"}:
        raise ValueError("only the synthetic accepting and refusing cases exist")
    replies = {"initialize": {"ok": True}, "account/read": managed(planType=plan),
               "account/rateLimits/read": spend_result()}
    methods = ["initialize", "initialized", "account/read"]
    if plan == "pro":
        methods.append("account/rateLimits/read")
    return ("#!/usr/bin/python3\n"
            "import json, sys\n"
            f"replies = json.loads({json.dumps(replies)!r})\n"
            f"expected = {methods!r}\n"
            "seen = []\n"
            "try:\n"
            "    assert sys.argv[1:] == ['app-server', '--strict-config', '--stdio']\n"
            "    for raw in sys.stdin.buffer:\n"
            "        request = json.loads(raw)\n"
            "        method = request['method']\n"
            "        assert len(seen) < len(expected) and method == expected[len(seen)]\n"
            "        seen.append(method)\n"
            "        if method != 'initialized':\n"
            "            reply = {'id': request['id'], 'result': replies[method]}\n"
            "            sys.stdout.buffer.write((json.dumps(reply) + '\\n').encode())\n"
            "            sys.stdout.buffer.flush()\n"
            "    assert seen == expected\n"
            "except (AssertionError, KeyError, TypeError, ValueError):\n"
            "    sys.stderr.buffer.write(b'synthetic-startup-peer-refused\\n')\n"
            "    raise SystemExit(3) from None\n").encode()
