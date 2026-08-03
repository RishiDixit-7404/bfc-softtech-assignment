"""An MCP server for the three calculators, speaking JSON-RPC 2.0 over stdio.

    python -m mcp_tools.server

One JSON object per line, requests on stdin and responses on stdout. Four
methods: ``initialize``, the ``notifications/initialized`` acknowledgement,
``tools/list`` and ``tools/call``.

**Nothing but JSON-RPC goes to stdout.** That is the one rule a stdio server
has, and it is why there is no print statement anywhere below; diagnostics go
to stderr, where they belong and where the parent can see them.

**A calculator failure is a result, not a JSON-RPC error.** MCP separates the
two deliberately: a protocol error means the call could not be made, while
``isError: true`` means it was made and the answer is that it cannot be done.
An EMI below the monthly interest is the second kind — the request was
perfectly well formed — so it comes back as a result carrying the exception's
structured fields, and the client re-raises it on the far side. JSON-RPC
errors are reserved for an unknown method, an unknown tool, or arguments that
are not an object.

Every response also carries a ``content`` block of plain text. This layer does
not format money, so that text is the calculator's own unformatted message: it
exists so a caller that ignores ``structuredContent`` still gets something
readable, and this chatbot is not that caller. It reads the structure and lets
``chat/formatting.py`` render, exactly as it does on the direct path.

What is not implemented, so nobody has to find out by trying: resources,
prompts, sampling, completion, progress, cancellation, and the HTTP transports.
Tools over stdio is the whole surface.

That slice is hand-written rather than taken from the official ``mcp`` SDK, for
two reasons. The SDK is async throughout, and ``chat/session.py`` is a
synchronous state machine called from a synchronous request handler, so using it
would mean threading an event loop through the conversation - or an
``asyncio.run`` per call - to overlap a millisecond of arithmetic behind a pipe
with nothing. And it arrives with roughly a dozen transitive dependencies
(pydantic, starlette, uvicorn, jsonschema, opentelemetry, pyjwt) for a project
whose ``requirements.txt`` is five lines and which already reaches both LLM
providers through ``urllib`` rather than their SDKs.

Needing any of the unimplemented list above - or needing to be a *client* of
servers written by other people, which is a far larger problem than speaking to
one known peer - is what would make the SDK the right answer instead.
"""

from __future__ import annotations

import json
import sys
from typing import IO

from calculators import CALCULATORS, CalculatorError

from .schemas import tool_definitions
from .wire import encode_error, encode_result

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "bfcsofttech-calculators"
SERVER_VERSION = "1.0"

# JSON-RPC 2.0 reserved codes. Only the three that can happen here.
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _result(request_id: object, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _initialize() -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _call_tool(params: dict) -> dict | None:
    """Run one calculator. ``None`` means the request itself was malformed.

    Returns an MCP tool result either way a *calculator* can end: the value,
    or ``isError`` with the exception's fields. Returning ``None`` is reserved
    for the cases that are protocol errors rather than answers.
    """
    name = params.get("name")
    arguments = params.get("arguments", {})
    if name not in CALCULATORS or not isinstance(arguments, dict):
        return None

    try:
        result = CALCULATORS[name].function(**arguments)
    except CalculatorError as refused:
        # The tool ran and the scenario has no answer. That is a result.
        return {
            "isError": True,
            "content": [{"type": "text", "text": str(refused)}],
            "structuredContent": {"ok": False, "error": encode_error(refused)},
        }
    except TypeError as signature:
        # Wrong or missing argument names: the schema said what was required.
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"{name}: {signature}"}],
            "structuredContent": {"ok": False, "invalidArguments": str(signature)},
        }

    encoded = encode_result(result)
    return {
        "isError": False,
        "content": [{"type": "text", "text": json.dumps(encoded["fields"])}],
        "structuredContent": {"ok": True, "result": encoded},
    }


def handle(request: dict) -> dict | None:
    """One request in, one response out. ``None`` for a notification."""
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(request_id, _initialize())

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None  # Notifications carry no id and are never answered.

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": tool_definitions()})

    if method == "tools/call":
        payload = _call_tool(params)
        if payload is None:
            return _error(
                request_id,
                INVALID_PARAMS,
                f"unknown tool or malformed arguments: {params.get('name')!r}",
            )
        return _result(request_id, payload)

    return _error(request_id, METHOD_NOT_FOUND, f"unknown method: {method!r}")


def serve(stdin: IO[str], stdout: IO[str]) -> None:
    """Read requests until the stream closes. Never writes anything else."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as malformed:
            response = _error(None, INTERNAL_ERROR, f"malformed request: {malformed}")
        else:
            response = handle(request)

        if response is not None:
            stdout.write(json.dumps(response, allow_nan=False) + "\n")
            stdout.flush()


def main() -> None:  # pragma: no cover - exercised as a subprocess
    serve(sys.stdin, sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    main()
