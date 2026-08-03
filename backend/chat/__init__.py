"""Conversation layer: intent routing, slot filling, and presentation.

Depends on ``calculators/`` and never the other way round. Nothing in this
package performs financial arithmetic — every number shown to a user was
produced by a calculator and passed through ``formatting`` unchanged.
"""

from __future__ import annotations

from .llm import LLM, LLMError, LLMUnavailableError, get_llm
from .router import Intent, Route, classify
from .session import Session, State

__all__ = [
    "Intent",
    "LLM",
    "LLMError",
    "LLMUnavailableError",
    "Route",
    "Session",
    "State",
    "classify",
    "get_llm",
]
