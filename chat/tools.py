"""How the session reaches a calculator: directly, or over MCP.

Two implementations of one method. ``invoke`` takes a calculator id and its
arguments and returns what the calculator returns, or raises what it raises —
and that sentence is true of both, which is the whole design. Nothing
downstream branches on which one is in use: ``chat/session.py`` catches the
same exception classes and ``chat/formatting.py`` reads the same attributes off
them, because on the MCP path those are the same classes and the same
attributes, rebuilt on this side of the pipe. See ``mcp_tools/wire.py``.

``CALCULATOR_TRANSPORT`` picks one, defaulting to ``direct``. The default is
not an opinion about which is better; it is that a reviewer who clones this and
runs ``pytest -q`` should not be spawning subprocesses to find out whether the
loan formula is right.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from calculators import CALCULATORS

from .mcp_client import McpStdioClient, ToolTransportError

TRANSPORT_ENV_VAR = "CALCULATOR_TRANSPORT"
DIRECT = "direct"
MCP = "mcp"
TRANSPORTS = (DIRECT, MCP)


class UnknownTransportError(ValueError):
    """``CALCULATOR_TRANSPORT`` names something that does not exist."""


@runtime_checkable
class Tools(Protocol):
    """The one thing the conversation needs from a calculator backend."""

    def invoke(self, calculator_id: str, **arguments: float) -> object:
        """Run a calculator.

        Raises:
            CalculatorError: the calculator refused, for any of its own
                reasons. Identical in class and attributes on both transports.
        """


class DirectTools:
    """Call the function. The registry already holds it."""

    transport = DIRECT

    def invoke(self, calculator_id: str, **arguments: float) -> object:
        return CALCULATORS[calculator_id].function(**arguments)


class McpTools:
    """Call the same function through an MCP server in another process."""

    transport = MCP

    def __init__(self, client: McpStdioClient | None = None) -> None:
        self.client = client or McpStdioClient()

    def invoke(self, calculator_id: str, **arguments: float) -> object:
        """Raises ToolTransportError if the server cannot be reached."""
        return self.client.call(calculator_id, arguments)


def build_tools(transport: str | None = None) -> Tools:
    """The backend named by ``transport``, or by the environment.

    Raises:
        UnknownTransportError: the name is not one of ``TRANSPORTS``. Failing
            here beats silently falling back to direct calls and reporting a
            green MCP test run that never opened a pipe.
    """
    chosen = (transport or os.getenv(TRANSPORT_ENV_VAR) or DIRECT).strip().lower()
    if chosen == DIRECT:
        return DirectTools()
    if chosen == MCP:
        return McpTools()
    raise UnknownTransportError(
        f"{TRANSPORT_ENV_VAR} must be one of {', '.join(TRANSPORTS)} - got {chosen!r}."
    )


_DEFAULT: Tools | None = None


def default_tools() -> Tools:
    """The process-wide backend, built once.

    Sessions are cheap and numerous; an MCP server process is neither, so all
    of them share one. Built lazily so that importing this module never spawns
    anything.
    """
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = build_tools()
    return _DEFAULT


def reset_default_tools() -> None:
    """Drop the cached backend. For tests that change the environment."""
    global _DEFAULT
    _DEFAULT = None


__all__ = [
    "DIRECT",
    "DirectTools",
    "MCP",
    "McpTools",
    "TRANSPORTS",
    "TRANSPORT_ENV_VAR",
    "ToolTransportError",
    "Tools",
    "UnknownTransportError",
    "build_tools",
    "default_tools",
    "reset_default_tools",
]
