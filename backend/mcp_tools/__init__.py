"""The three calculators, exposed as MCP tools over stdio.

This package is an *adapter*. It imports ``calculators/`` and the standard
library and nothing else — no chat layer, no LLM, no web framework. Every
number it returns was produced by the same function the direct path calls, so
the two transports cannot drift apart into two answers.

Three modules, three jobs:

:mod:`mcp_tools.schemas`  the tool list, derived from ``calculators.CALCULATORS``
                          and the validators' own bounds
:mod:`mcp_tools.wire`     the error boundary: results and exceptions across JSON
:mod:`mcp_tools.server`   the JSON-RPC loop, run as ``python -m mcp_tools.server``

The client lives in ``chat/mcp_client.py``, on the far side of the boundary,
because it is the chatbot that has a choice of transports — the server has
none.
"""

from __future__ import annotations

from .schemas import TOOLS, tool_definitions
from .wire import (
    WireError,
    decode_error,
    decode_result,
    encode_error,
    encode_result,
)

__all__ = [
    "TOOLS",
    "WireError",
    "decode_error",
    "decode_result",
    "encode_error",
    "encode_result",
    "tool_definitions",
]
