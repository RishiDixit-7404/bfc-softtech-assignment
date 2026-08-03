"""A synchronous MCP client over stdio.

The server runs as a child process; this speaks JSON-RPC 2.0 to it, one JSON
object per line. It is deliberately small, and everything it does not do is
listed in ``mcp_tools/server.py``.

Synchronous on purpose, and hand-written rather than the official ``mcp`` SDK.
``chat/session.py`` is a plain state machine called from a FastAPI handler, and
the calculator call is a millisecond of arithmetic behind a pipe; the SDK is
async throughout, so using it would mean an event loop threaded through the
session, or an ``asyncio.run`` per call, to overlap nothing. It would also add
roughly a dozen transitive dependencies to a five-line ``requirements.txt``.
Speaking the protocol to one known peer is a much smaller problem than being a
client of servers written by other people, which is where the SDK earns its
weight — ``mcp_tools/server.py`` lists exactly which slice exists here.

The process starts on first use and is reused, because spawning an interpreter
per EMI calculation is a strange way to save nothing. It is shut down at exit.

Transport failures raise :class:`ToolTransportError`, which is *not* a
``CalculatorError`` — the calculation did not fail, the pipe did, and telling a
user their EMI is invalid because a subprocess died would be a lie. It is the
one thing the chat layer learns from this phase, and it earns a sentence of its
own the same way each provider failure does.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
from pathlib import Path

from calculators import CalculatorError

from mcp_tools.wire import WireError, decode_error, decode_result

SERVER_MODULE = "mcp_tools.server"
_REPO_ROOT = Path(__file__).resolve().parent.parent


class ToolTransportError(Exception):
    """The calculator could not be reached. Says nothing about the numbers."""


class McpStdioClient:
    """One long-lived server process, spoken to over its stdin and stdout."""

    def __init__(self, command: list[str] | None = None) -> None:
        self._command = command or [sys.executable, "-m", SERVER_MODULE]
        self._process: subprocess.Popen | None = None
        self._next_id = 0
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """Every tool the server advertises, with its input schema."""
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ToolTransportError(f"tools/list returned no tool list: {result!r}")
        return tools

    def call(self, name: str, arguments: dict) -> object:
        """Run one calculator and return exactly what a direct call would.

        Raises:
            CalculatorError: whatever the calculator raised, rebuilt as the
                class it was with every structured field intact. The caller
                cannot tell it crossed a process boundary, which is the point.
            ToolTransportError: the server could not be reached or answered
                with something this client cannot read.
        """
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise ToolTransportError(f"{name} returned no structured content")

        try:
            if structured.get("ok"):
                return decode_result(structured.get("result"))
            if "error" in structured:
                raise decode_error(structured["error"])
        except WireError as unreadable:
            raise ToolTransportError(f"{name}: {unreadable}") from unreadable

        raise ToolTransportError(
            f"{name} was called with arguments it refused: "
            f"{structured.get('invalidArguments', structured)}"
        )

    def close(self) -> None:
        """Shut the server down. Safe to call twice, and at interpreter exit."""
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return

        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):  # pragma: no cover
            process.kill()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _ensure_started(self) -> subprocess.Popen:
        """Spawn and initialise the server, once."""
        if self._process is not None and self._process.poll() is None:
            return self._process

        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                cwd=_REPO_ROOT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
            )
        except OSError as unstartable:
            raise ToolTransportError(
                f"could not start the calculator server: {unstartable}"
            ) from unstartable

        self._handshake()
        return self._process

    def _handshake(self) -> None:
        """MCP's initialize, then the notification that says it took."""
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "bfcsofttech-chat", "version": "1.0"},
            },
            handshaking=True,
        )
        self._notify("notifications/initialized")

    def _request(self, method: str, params: dict, *, handshaking: bool = False) -> dict:
        """Send one request and read its response.

        Raises:
            ToolTransportError: the server is gone, silent, or answered with a
                JSON-RPC error.
        """
        process = self._process if handshaking else self._ensure_started()
        if process is None or process.stdin is None or process.stdout is None:
            raise ToolTransportError("the calculator server is not running")

        self._next_id += 1
        request_id = self._next_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (BrokenPipeError, OSError, ValueError) as broken:
            raise ToolTransportError(
                f"the calculator server stopped responding: {broken}"
            ) from broken

        if not line:
            raise ToolTransportError("the calculator server closed the connection")

        return self._read_response(line, request_id, method)

    def _notify(self, method: str) -> None:
        """Fire and forget. Notifications carry no id and get no reply."""
        process = self._process
        if process is None or process.stdin is None:
            return  # pragma: no cover - defensive
        try:
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):  # pragma: no cover
            pass

    @staticmethod
    def _read_response(line: str, request_id: int, method: str) -> dict:
        try:
            response = json.loads(line)
        except json.JSONDecodeError as malformed:
            raise ToolTransportError(
                f"{method} got a reply that is not JSON: {line.strip()!r}"
            ) from malformed

        if response.get("id") != request_id:
            # Strictly serial by construction, so a mismatch means the stream
            # is out of step - worth failing on rather than reading past.
            raise ToolTransportError(
                f"{method} got the reply to a different request: {response.get('id')!r}"
            )

        if "error" in response:
            detail = response["error"]
            raise ToolTransportError(
                f"{method} was refused: {detail.get('message', detail)}"
            )

        result = response.get("result")
        if not isinstance(result, dict):
            raise ToolTransportError(f"{method} returned no result object")
        return result


__all__ = ["CalculatorError", "McpStdioClient", "ToolTransportError"]
