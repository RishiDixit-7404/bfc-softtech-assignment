"""Provider-agnostic access to a language model.

This module is transport only. It holds no prompt text (that is
``chat/prompts.py``) and makes no decisions about conversation state.

Both providers speak plain HTTP through the standard library rather than a
vendor SDK. Two reasons: the whole request is visible in thirty lines, which a
reviewer can check against the API docs, and the test suite gains no dependency
it would have to mock. Nothing here is imported at conversation time either —
``get_llm`` is called once, by ``app.py``, and never by the tests.

``generate`` takes a ``task`` label alongside the prompts. Providers use it to
pick a temperature — deterministic for ``classify`` and ``extract``, freer for
``answer`` — and test doubles use it to dispatch without pattern-matching on
prompt text.

Every failure mode leaves here as an :class:`LLMError` subclass carrying what
went wrong. The chat layer turns each into its own plain sentence; no traceback
and no provider JSON ever reaches a user.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, runtime_checkable

Task = Literal["classify", "extract", "answer"]

PROVIDER_ENV_VAR = "LLM_PROVIDER"
TIMEOUT_ENV_VAR = "LLM_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 30.0

GEMINI_KEY_ENV_VAR = "GEMINI_API_KEY"
GEMINI_MODEL_ENV_VAR = "GEMINI_MODEL"
# An alias rather than a pinned version, deliberately. Google retires pinned
# models for new keys while still listing them — gemini-2.5-flash answers
# ListModels and then 404s on generateContent with "no longer available to new
# users", which is a confusing failure to hand someone cloning this months
# from now. Determinism here comes from calculators/, not from the model, so
# the alias costs nothing. Pin with GEMINI_MODEL if you want a fixed version.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

OLLAMA_HOST_ENV_VAR = "OLLAMA_HOST"
OLLAMA_MODEL_ENV_VAR = "OLLAMA_MODEL"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"

# Reading a message and pulling values out of it are jobs with one right
# answer, so they are asked for deterministically. Prose gets a little room.
TEMPERATURES: dict[str, float] = {"classify": 0.0, "extract": 0.0, "answer": 0.4}


class LLMError(RuntimeError):
    """The model could not be reached, or answered with something unusable.

    The chat layer catches this at the turn boundary and says so plainly.
    Conversation state is never discarded because a provider failed.
    """


class LLMUnavailableError(LLMError):
    """The provider could not be reached — host down, connection refused."""


class LLMMisconfiguredError(LLMUnavailableError):
    """No provider is selected, the name is unknown, or the key is missing.

    Separate from its parent because the two need different things said. An
    unreachable host may come back and retrying is sensible; an unset
    environment variable will not fix itself, and telling a user to try again
    wastes their time.
    """


class LLMQuotaError(LLMError):
    """The provider was reached and refused: the request allowance is spent.

    Its own class because it is the failure a free key hits first — Gemini's
    free tier allows 20 generate requests per day, which is roughly seven
    turns of conversation — and because "could not reach the model" would be
    a lie about what happened and about when it will work again.
    """


class LLMTimeoutError(LLMError):
    """The provider did not answer within the configured timeout."""


class LLMResponseError(LLMError):
    """The provider answered with something that is not a usable reply."""


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
        raise LLMMisconfiguredError(
            f"No language model is configured. Set {PROVIDER_ENV_VAR} to one "
            f"of: {', '.join(available_providers()) or 'none registered'}."
        )
    if chosen not in _PROVIDERS:
        raise LLMMisconfiguredError(
            f"Unknown language model provider {chosen!r}. Available: "
            f"{', '.join(available_providers()) or 'none registered'}."
        )
    return _PROVIDERS[chosen]()


# --------------------------------------------------------------------------
# HTTP, once, for both providers
# --------------------------------------------------------------------------


def post_json(
    url: str, payload: dict, headers: dict[str, str], timeout: float
) -> dict:
    """POST JSON and return the decoded reply.

    The single seam both providers go through, so timeout and transport
    handling exist once. Tests replace this function rather than a socket.

    Raises:
        LLMTimeoutError: no answer inside ``timeout`` seconds.
        LLMUnavailableError: the host refused the connection or is unreachable.
        LLMResponseError: an HTTP error status, or a body that is not JSON.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except socket.timeout as timed_out:
        raise LLMTimeoutError(f"no reply within {timeout:g}s") from timed_out
    except urllib.error.HTTPError as http_error:
        raise _from_status(http_error.code, _error_detail(http_error)) from http_error
    except urllib.error.URLError as url_error:
        if isinstance(url_error.reason, (socket.timeout, TimeoutError)):
            raise LLMTimeoutError(f"no reply within {timeout:g}s") from url_error
        raise LLMUnavailableError(
            f"could not reach the provider: {url_error.reason}"
        ) from url_error
    except OSError as os_error:  # pragma: no cover - defensive
        raise LLMUnavailableError(
            f"could not reach the provider: {os_error}"
        ) from os_error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as malformed:
        raise LLMResponseError("the provider's reply was not JSON") from malformed

    if not isinstance(decoded, dict):
        raise LLMResponseError("the provider's reply was not a JSON object")
    return decoded


def _error_detail(http_error: urllib.error.HTTPError) -> str:
    """The provider's own explanation, for the operator reading the log.

    Discarding this was a mistake worth naming: an unusable model name reached
    the operator as a bare "HTTP 404" and took a hand-written script to
    diagnose. The detail goes in the *exception*, never in the reply — the
    user still sees one plain sentence from ``chat/prompts.py``.
    """
    try:
        body = http_error.read().decode("utf-8", "replace")
    except Exception:  # pragma: no cover - body already consumed or absent
        return "no detail"

    try:
        message = json.loads(body)["error"]["message"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return body[:200].strip() or "no detail"
    return str(message)[:300]


def _from_status(code: int, detail: str) -> LLMError:
    """Map an HTTP status to the failure the user needs to hear about.

    A rejected key and an unknown model are configuration mistakes that
    retrying cannot fix; a quota or a 5xx is worth trying again later. Sorting
    them here is what lets the four sentences in ``prompts.py`` stay true.
    """
    if code in (401, 403):
        return LLMMisconfiguredError(f"the provider rejected the key: {detail}")
    if code == 404:
        return LLMMisconfiguredError(
            f"the provider has no such model, or it is not available to this "
            f"key: {detail}"
        )
    if code == 429:
        return LLMQuotaError(f"the request allowance is spent: {detail}")
    if code >= 500:
        return LLMUnavailableError(f"the provider is unavailable (HTTP {code}): {detail}")
    return LLMResponseError(f"the provider returned HTTP {code}: {detail}")


def _timeout_from_env() -> float:
    """Read the timeout, falling back rather than failing on a bad value."""
    try:
        timeout = float(os.environ.get(TIMEOUT_ENV_VAR, DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS


def _text_or_error(text: object) -> str:
    """Every provider ends here: a reply must be a non-empty string."""
    if not isinstance(text, str) or not text.strip():
        raise LLMResponseError("the provider returned an empty reply")
    return text.strip()


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GeminiLLM:
    """Google's Gemini over its REST endpoint."""

    api_key: str
    model: str = DEFAULT_GEMINI_MODEL
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def generate(self, *, system: str, user: str, task: Task) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": TEMPERATURES.get(task, 0.0),
                "candidateCount": 1,
            },
        }
        reply = post_json(
            GEMINI_ENDPOINT.format(model=self.model),
            payload,
            {"x-goog-api-key": self.api_key},
            self.timeout,
        )

        blocked = reply.get("promptFeedback", {}).get("blockReason")
        if blocked:
            raise LLMResponseError(f"the provider blocked the request ({blocked})")

        try:
            text = reply["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as unexpected:
            raise LLMResponseError(
                "the provider's reply had no text in it"
            ) from unexpected
        return _text_or_error(text)


def _gemini_from_env() -> LLM:
    key = os.environ.get(GEMINI_KEY_ENV_VAR, "").strip()
    if not key:
        raise LLMMisconfiguredError(
            f"{GEMINI_KEY_ENV_VAR} is not set. Copy .env.example, put your key "
            f"in it, and export it before starting the server."
        )
    return GeminiLLM(
        api_key=key,
        model=os.environ.get(GEMINI_MODEL_ENV_VAR, "").strip() or DEFAULT_GEMINI_MODEL,
        timeout=_timeout_from_env(),
    )


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OllamaLLM:
    """A local Ollama server. No key: it is on the machine or it is not."""

    model: str = DEFAULT_OLLAMA_MODEL
    host: str = DEFAULT_OLLAMA_HOST
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def generate(self, *, system: str, user: str, task: Task) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": TEMPERATURES.get(task, 0.0)},
        }
        reply = post_json(
            f"{self.host.rstrip('/')}/api/chat", payload, {}, self.timeout
        )

        try:
            text = reply["message"]["content"]
        except (KeyError, TypeError) as unexpected:
            raise LLMResponseError(
                "the provider's reply had no text in it"
            ) from unexpected
        return _text_or_error(text)


def _ollama_from_env() -> LLM:
    return OllamaLLM(
        model=os.environ.get(OLLAMA_MODEL_ENV_VAR, "").strip() or DEFAULT_OLLAMA_MODEL,
        host=os.environ.get(OLLAMA_HOST_ENV_VAR, "").strip() or DEFAULT_OLLAMA_HOST,
        timeout=_timeout_from_env(),
    )


register_provider("gemini", _gemini_from_env)
register_provider("ollama", _ollama_from_env)


@dataclass(frozen=True)
class UnconfiguredLLM:
    """Stands in when no provider is configured.

    It fails on use rather than on start-up, so the server still runs, the
    page still loads, and the greeting still lists the calculators. The first
    message then explains what is missing through the ordinary failure path
    instead of a stack trace at boot.
    """

    reason: str

    def generate(self, *, system: str, user: str, task: Task) -> str:
        raise LLMMisconfiguredError(self.reason)


def get_llm_or_unconfigured() -> LLM:
    """Build the configured provider, or a placeholder that explains itself."""
    try:
        return get_llm()
    except LLMUnavailableError as missing:
        return UnconfiguredLLM(str(missing))
