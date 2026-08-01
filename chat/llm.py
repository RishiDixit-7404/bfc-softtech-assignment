"""Provider-agnostic access to a language model.

This module is transport only. It holds no prompt text (that is
``chat/prompts.py``), makes no decisions about conversation state, and imports
no vendor SDK — providers register themselves at import time in Phase 4, so the
offline test suite never touches a network or an environment variable.

``generate`` takes a ``task`` label alongside the prompts. Providers use it to
pick a temperature — deterministic for ``classify`` and ``extract``, freer for
``answer`` — and test doubles use it to dispatch without pattern-matching on
prompt text.
"""

from __future__ import annotations

import os
from typing import Callable, Literal, Protocol, runtime_checkable

Task = Literal["classify", "extract", "answer"]

PROVIDER_ENV_VAR = "LLM_PROVIDER"


class LLMError(RuntimeError):
    """The model could not be reached, or answered with something unusable.

    The chat layer catches this at the turn boundary and says so plainly.
    Conversation state is never discarded because a provider failed.
    """


class LLMUnavailableError(LLMError):
    """No provider is configured, or the configured one is not registered."""


@runtime_checkable
class LLM(Protocol):
    """The entire surface the conversation layer needs from a model."""

    def generate(self, *, system: str, user: str, task: Task) -> str:
        """Return the model's reply as plain text.

        Raises:
            LLMError: the provider failed, timed out, or returned nothing.
        """


_PROVIDERS: dict[str, Callable[[], LLM]] = {}


def register_provider(name: str, factory: Callable[[], LLM]) -> None:
    """Register a provider factory under a lower-case name."""
    _PROVIDERS[name.strip().lower()] = factory


def available_providers() -> tuple[str, ...]:
    """Names that :func:`get_llm` will currently accept."""
    return tuple(sorted(_PROVIDERS))


def get_llm(name: str | None = None) -> LLM:
    """Build the configured provider.

    Args:
        name: Provider name. Defaults to the ``LLM_PROVIDER`` environment
            variable.

    Returns:
        An object satisfying :class:`LLM`.

    Raises:
        LLMUnavailableError: nothing is configured, or the name is unknown.
    """
    chosen = (name or os.environ.get(PROVIDER_ENV_VAR, "")).strip().lower()

    if not chosen:
        raise LLMUnavailableError(
            f"No language model is configured. Set {PROVIDER_ENV_VAR} to one "
            f"of: {', '.join(available_providers()) or 'none registered'}."
        )
    if chosen not in _PROVIDERS:
        raise LLMUnavailableError(
            f"Unknown language model provider {chosen!r}. Available: "
            f"{', '.join(available_providers()) or 'none registered'}."
        )
    return _PROVIDERS[chosen]()
