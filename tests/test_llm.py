"""The two providers, and what each failure looks like to a user.

Nothing here opens a socket. Both providers funnel through ``llm.post_json``,
so replacing that one function exercises the whole request-building and
reply-reading path without a network, a key, or a running Ollama.
"""

import io
import json
import socket
import urllib.error

import pytest

from chat import llm, prompts
from chat.llm import (
    GeminiLLM,
    LLMMisconfiguredError,
    LLMQuotaError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    OllamaLLM,
    get_llm,
    get_llm_or_unconfigured,
)
from chat.session import Session, State
from test_session import LOAN_ROUTES, StubLLM


@pytest.fixture
def captured(monkeypatch):
    """Capture the outgoing request and return a scripted reply."""
    sent = {}
    reply = {}

    def fake_post(url, payload, headers, timeout):
        sent.update(url=url, payload=payload, headers=headers, timeout=timeout)
        if isinstance(reply.get("raise"), Exception):
            raise reply["raise"]
        return reply.get("body", {})

    monkeypatch.setattr(llm, "post_json", fake_post)
    return sent, reply


GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": "LOAN_TENURE"}]}}]
}
OLLAMA_OK = {"message": {"role": "assistant", "content": "LOAN_TENURE"}}


# --------------------------------------------------------------------------
# The happy path, and what actually goes over the wire
# --------------------------------------------------------------------------


def test_gemini_sends_the_system_prompt_and_reads_the_reply(captured):
    sent, reply = captured
    reply["body"] = GEMINI_OK

    text = GeminiLLM(api_key="k", model="gemini-2.5-flash", timeout=9).generate(
        system="you are a finance assistant", user="loan tenure", task="classify"
    )

    assert text == "LOAN_TENURE"
    assert sent["payload"]["systemInstruction"]["parts"][0]["text"] == (
        "you are a finance assistant"
    )
    assert sent["payload"]["contents"][0]["parts"][0]["text"] == "loan tenure"
    assert sent["headers"]["x-goog-api-key"] == "k"
    assert "gemini-2.5-flash" in sent["url"]
    assert sent["timeout"] == 9


def test_ollama_sends_a_chat_turn_and_reads_the_reply(captured):
    sent, reply = captured
    reply["body"] = OLLAMA_OK

    text = OllamaLLM(model="llama3.1", host="http://localhost:11434/").generate(
        system="sys", user="loan tenure", task="classify"
    )

    assert text == "LOAN_TENURE"
    assert sent["url"] == "http://localhost:11434/api/chat"
    assert sent["payload"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "loan tenure"},
    ]
    assert sent["payload"]["stream"] is False


@pytest.mark.parametrize(
    "task,temperature", [("classify", 0.0), ("extract", 0.0), ("answer", 0.4)]
)
def test_reading_a_message_is_deterministic_and_prose_is_not(
    captured, task, temperature
):
    """Classification and extraction have one right answer. Prose does not."""
    sent, reply = captured
    reply["body"] = GEMINI_OK

    GeminiLLM(api_key="k").generate(system="s", user="u", task=task)

    assert sent["payload"]["generationConfig"]["temperature"] == temperature


# --------------------------------------------------------------------------
# Malformed replies
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"candidates": []},
        {"candidates": [{"content": {}}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": ""}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "   "}]}}]},
    ],
)
def test_gemini_refuses_a_reply_with_no_usable_text(captured, body):
    _sent, reply = captured
    reply["body"] = body

    with pytest.raises(LLMResponseError):
        GeminiLLM(api_key="k").generate(system="s", user="u", task="classify")


def test_gemini_reports_a_blocked_prompt_as_a_response_error(captured):
    _sent, reply = captured
    reply["body"] = {"promptFeedback": {"blockReason": "SAFETY"}}

    with pytest.raises(LLMResponseError) as raised:
        GeminiLLM(api_key="k").generate(system="s", user="u", task="answer")
    assert "blocked" in str(raised.value)


@pytest.mark.parametrize("body", [{}, {"message": {}}, {"message": {"content": ""}}])
def test_ollama_refuses_a_reply_with_no_usable_text(captured, body):
    _sent, reply = captured
    reply["body"] = body

    with pytest.raises(LLMResponseError):
        OllamaLLM().generate(system="s", user="u", task="classify")


# --------------------------------------------------------------------------
# Transport failures, at the one seam both providers share
# --------------------------------------------------------------------------


class _FakeSocket:
    """Enough of a socket for urlopen's error paths."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, *_args):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _urlopen_raising(error):
    def fake_urlopen(_request, timeout=None):
        raise error

    return fake_urlopen


def test_a_timeout_is_reported_as_a_timeout(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", _urlopen_raising(socket.timeout())
    )
    with pytest.raises(LLMTimeoutError):
        llm.post_json("http://x", {}, {}, timeout=2)


def test_a_timeout_wrapped_in_a_url_error_is_still_a_timeout(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        _urlopen_raising(urllib.error.URLError(socket.timeout())),
    )
    with pytest.raises(LLMTimeoutError):
        llm.post_json("http://x", {}, {}, timeout=2)


def test_a_refused_connection_reads_as_unavailable(monkeypatch):
    """Ollama not running is the ordinary case of this."""
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        _urlopen_raising(urllib.error.URLError(ConnectionRefusedError(61, "refused"))),
    )
    with pytest.raises(LLMUnavailableError):
        llm.post_json("http://localhost:11434", {}, {}, timeout=2)


def _http_error(status, body=b""):
    return urllib.error.HTTPError("http://x", status, "no", {}, io.BytesIO(body))


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, LLMMisconfiguredError),  # bad key - retrying cannot help
        (403, LLMMisconfiguredError),
        (404, LLMMisconfiguredError),  # unusable model name, same class of fix
        (429, LLMQuotaError),  # allowance spent - resets, so say so
        (500, LLMUnavailableError),
        (503, LLMUnavailableError),
        (400, LLMResponseError),  # a malformed request from us
    ],
)
def test_each_http_status_maps_to_the_failure_it_actually_is(
    monkeypatch, status, expected
):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", _urlopen_raising(_http_error(status))
    )
    with pytest.raises(expected):
        llm.post_json("http://x", {}, {}, timeout=2)


def test_a_quota_error_is_not_reported_as_a_configuration_mistake(monkeypatch):
    """Telling a user to fix their config when the key is fine wastes their day."""
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", _urlopen_raising(_http_error(429))
    )
    with pytest.raises(LLMQuotaError) as raised:
        llm.post_json("http://x", {}, {}, timeout=2)
    assert not isinstance(raised.value, LLMMisconfiguredError)


def test_a_spent_allowance_does_not_claim_the_model_was_unreachable():
    """Observed against the live free tier: 20 requests a day, then 429."""
    session = Session(llm=_BrokenLLM(LLMQuotaError("allowance spent")))
    reply = session.handle("what is a mutual fund")

    assert prompts.LLM_QUOTA in reply
    assert prompts.LLM_UNAVAILABLE not in reply
    assert "resets daily" in reply


def test_the_provider_explanation_reaches_the_operator(monkeypatch):
    """A bare "HTTP 404" cost a hand-written script to diagnose once."""
    body = json.dumps(
        {"error": {"message": "This model models/gemini-2.5-flash is no longer available to new users."}}
    ).encode()
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", _urlopen_raising(_http_error(404, body))
    )

    with pytest.raises(LLMMisconfiguredError) as raised:
        llm.post_json("http://x", {}, {}, timeout=2)
    assert "no longer available to new users" in str(raised.value)


def test_a_non_json_error_body_still_yields_something_readable(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        _urlopen_raising(_http_error(500, b"<html>gateway blew up</html>")),
    )
    with pytest.raises(LLMUnavailableError) as raised:
        llm.post_json("http://x", {}, {}, timeout=2)
    assert "gateway blew up" in str(raised.value)


@pytest.mark.parametrize("body", [b"not json at all", b"[1, 2, 3]"])
def test_a_body_that_is_not_a_json_object_reads_as_a_response_error(monkeypatch, body):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda _r, timeout=None: _FakeSocket(body)
    )
    with pytest.raises(LLMResponseError):
        llm.post_json("http://x", {}, {}, timeout=2)


def test_a_well_formed_body_is_decoded(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        lambda _r, timeout=None: _FakeSocket(json.dumps({"ok": True}).encode()),
    )
    assert llm.post_json("http://x", {}, {}, timeout=2) == {"ok": True}


# --------------------------------------------------------------------------
# Selection and configuration
# --------------------------------------------------------------------------


def test_a_missing_key_is_named_before_any_request_is_made(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(LLMUnavailableError) as raised:
        get_llm()

    assert "GEMINI_API_KEY" in str(raised.value)
    assert ".env.example" in str(raised.value)


def test_the_provider_is_selected_by_environment_variable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "key-from-env")
    assert isinstance(get_llm(), GeminiLLM)

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert isinstance(get_llm(), OllamaLLM)


def test_ollama_needs_no_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")

    provider = get_llm()
    assert provider.model == "mistral"


def test_an_unknown_provider_names_the_ones_that_exist(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt5")

    with pytest.raises(LLMUnavailableError) as raised:
        get_llm()

    assert "gemini" in str(raised.value) and "ollama" in str(raised.value)


@pytest.mark.parametrize("value,expected", [("5", 5.0), ("", 30.0), ("nonsense", 30.0), ("-1", 30.0)])
def test_a_bad_timeout_falls_back_rather_than_failing(monkeypatch, value, expected):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", value)
    assert get_llm().timeout == expected


# --------------------------------------------------------------------------
# What the user sees
# --------------------------------------------------------------------------


class _BrokenLLM:
    def __init__(self, error):
        self.error = error

    def generate(self, *, system, user, task):
        raise self.error


@pytest.mark.parametrize(
    "error,expected",
    [
        (LLMTimeoutError("slow"), prompts.LLM_TIMEOUT),
        (LLMQuotaError("spent"), prompts.LLM_QUOTA),
        (LLMResponseError("garbage"), prompts.LLM_MALFORMED),
        (LLMUnavailableError("host down"), prompts.LLM_UNAVAILABLE),
        (LLMMisconfiguredError("GEMINI_API_KEY is not set"), prompts.LLM_MISCONFIGURED),
    ],
)
def test_each_failure_gets_its_own_plain_sentence(error, expected):
    session = Session(llm=StubLLM(routes=LOAN_ROUTES))
    session.handle("calculate my loan tenure")
    session.llm = _BrokenLLM(error)

    reply = session.handle("something it cannot read")

    assert expected in reply
    assert session.state is State.COLLECTING
    assert session.pending_slot == "principal"


def test_an_unreachable_host_and_a_missing_key_do_not_say_the_same_thing():
    """Retrying fixes one of them. The copy has to tell them apart."""
    assert prompts.LLM_UNAVAILABLE != prompts.LLM_MISCONFIGURED
    assert "will not help" in prompts.LLM_MISCONFIGURED


def test_an_unconfigured_server_still_starts_and_explains_itself(monkeypatch):
    """app.py builds the provider at import: a missing key must not stop it."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    placeholder = get_llm_or_unconfigured()

    session = Session(llm=placeholder)
    assert "Loan tenure" in session.greeting()  # the greeting needs no model
    assert prompts.LLM_MISCONFIGURED in session.handle("calculate my loan tenure")


@pytest.mark.parametrize(
    "error",
    [
        LLMTimeoutError("slow"),
        LLMQuotaError("spent"),
        LLMResponseError("garbage"),
        LLMUnavailableError("x"),
        LLMMisconfiguredError("GEMINI_API_KEY is not set"),
    ],
)
def test_no_provider_detail_ever_reaches_the_user(error):
    """Not the exception text, not a status code, not a traceback."""
    session = Session(llm=_BrokenLLM(error))

    reply = session.handle("what is a mutual fund")

    assert str(error) not in reply
    assert "Traceback" not in reply
    assert type(error).__name__ not in reply
