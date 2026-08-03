"""The MCP adapter: schemas, the wire boundary, and a live stdio round trip.

Most of this runs in-process against ``mcp_tools.server.handle``, because the
protocol is a pure function of the request and a subprocess proves nothing
extra about it. The handful of tests that do spawn the server are marked
``subprocess`` and are the ones that would catch a client which works only
against an imaginary peer.

Financial figures are from TEST_VECTORS.md - L1 for the loan, L4 for the EMI
trap - and are asserted here for one reason only: to show that the numbers
crossing the boundary are the numbers, unchanged.
"""

import json
import math
import sys
from dataclasses import fields

import pytest

from calculators import (
    CALCULATORS,
    CalculatorError,
    EmiTooLowError,
    InfeasibleScenarioError,
    InvalidAmountError,
    InvalidPeriodError,
    InvalidRateError,
    LoanTenure,
    ValidationError,
    loan_tenure,
    sip_for_target,
    swp_projection,
)
from calculators.validation import MAX_RATE, MAX_YEARS, MIN_RATE
from chat.mcp_client import McpStdioClient, ToolTransportError
from chat.tools import (
    DIRECT,
    MCP,
    DirectTools,
    McpTools,
    UnknownTransportError,
    build_tools,
)
from mcp_tools import server as server_module
from mcp_tools.schemas import tool_definitions
from mcp_tools.wire import (
    RESULT_TYPES,
    WireError,
    decode_error,
    decode_result,
    encode_error,
    encode_result,
    error_types,
)

L1 = {"principal": 500_000, "emi": 10_000, "annual_rate_pct": 9.0}
L4 = {"principal": 500_000, "emi": 3_000, "annual_rate_pct": 9.0}


def call(method, params=None, request_id=1):
    """One request through the server's dispatcher, in process."""
    return server_module.handle(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    )


# --------------------------------------------------------------------------
# Tool definitions
# --------------------------------------------------------------------------


def test_every_calculator_is_a_tool_and_nothing_else_is():
    """Derived from the registry, so the two cannot disagree."""
    names = [tool["name"] for tool in tool_definitions()]

    assert names == list(CALCULATORS)


@pytest.mark.parametrize("tool", tool_definitions(), ids=lambda t: t["name"])
def test_a_tool_takes_exactly_the_arguments_its_function_takes(tool):
    """A schema that is not the signature is a schema that misleads a caller."""
    import inspect

    spec = CALCULATORS[tool["name"]]
    signature = list(inspect.signature(spec.function).parameters)

    assert list(tool["inputSchema"]["properties"]) == signature
    assert tool["inputSchema"]["required"] == signature
    assert tool["inputSchema"]["additionalProperties"] is False


@pytest.mark.parametrize("tool", tool_definitions(), ids=lambda t: t["name"])
def test_every_parameter_states_its_units_and_its_bounds(tool):
    """The two things a caller who is not this chatbot cannot infer."""
    for name, schema in tool["inputSchema"]["properties"].items():
        assert schema["units"], name
        assert schema["description"].strip(), name
        assert {"minimum", "exclusiveMinimum"} & set(schema), name


def test_rate_bounds_come_from_the_validator_not_from_a_literal():
    """A schema promising 0-100 while the validator enforces something else
    is worse than no schema: it invites a caller to send what will be refused."""
    for tool in tool_definitions():
        rate = tool["inputSchema"]["properties"].get("annual_rate_pct")
        assert rate["minimum"] == MIN_RATE
        assert rate["maximum"] == MAX_RATE

    years = tool_definitions()[1]["inputSchema"]["properties"]["years"]
    assert years["maximum"] == MAX_YEARS


def test_the_sip_tool_warns_that_the_spec_formula_is_not_an_annuity_due():
    """D2 is the one thing an outside caller would otherwise misread as a bug."""
    sip = next(t for t in tool_definitions() if t["name"] == "sip")

    assert "annuity-due" in sip["description"]


# --------------------------------------------------------------------------
# The wire: results
# --------------------------------------------------------------------------

VALID_CALLS = [
    (loan_tenure, L1),
    (loan_tenure, {"principal": 500_000, "emi": 10_000, "annual_rate_pct": 0}),
    (sip_for_target, {"target": 1_000_000, "annual_rate_pct": 12.0, "years": 10}),
    (swp_projection, {"lumpsum": 1_000_000, "years": 10, "annual_rate_pct": 9.0,
                      "monthly_withdrawal": 8_000}),
    (swp_projection, {"lumpsum": 300_000, "years": 10, "annual_rate_pct": 8.0,
                      "monthly_withdrawal": 6_000}),  # W5, depleted
]


@pytest.mark.parametrize("function, arguments", VALID_CALLS)
def test_a_result_survives_the_crossing_exactly(function, arguments):
    """Equal, not approximately equal.

    json round-trips a float through its shortest repr, so there is no reason
    to accept a tolerance here - and accepting one would hide a boundary that
    had started rounding.
    """
    original = function(**arguments)
    rebuilt = decode_result(encode_result(original))

    assert rebuilt == original
    assert type(rebuilt) is type(original)
    for field in fields(original):
        assert getattr(rebuilt, field.name) == getattr(original, field.name)


def test_every_calculator_returns_a_type_the_wire_knows():
    """A fourth result dataclass must be registered, not silently unsendable."""
    for function, arguments in VALID_CALLS:
        assert type(function(**arguments)).__name__ in RESULT_TYPES


def test_a_non_result_is_refused_rather_than_guessed_at():
    with pytest.raises(WireError):
        encode_result({"months": 63})


def test_a_result_type_the_peer_invented_is_refused():
    with pytest.raises(WireError):
        decode_result({"type": "FreeMoney", "fields": {}})


# --------------------------------------------------------------------------
# The wire: errors - the part that matters
# --------------------------------------------------------------------------

ERRORS = [
    EmiTooLowError(
        "emi too low", principal=500_000.0, emi=3_000.0,
        monthly_interest=3_603.661658, minimum_emi=3_603.661658,
    ),
    InvalidAmountError("bad amount", field="loan amount", value=0.0, minimum=0.0),
    InvalidAmountError(
        "negative withdrawal", field="monthly withdrawal", value=-500.0,
        minimum=0.0, minimum_inclusive=True,
    ),
    InvalidAmountError(
        "too big", field="monthly withdrawal", value=2e6, maximum=1e6,
    ),
    InvalidRateError("bad rate", field="interest rate", value=150.0),
    InvalidPeriodError("bad period", field="investment period", value=0.0),
    ValidationError("generic", field="something", value=1),
    InfeasibleScenarioError("no answer"),
    CalculatorError("base"),
]


@pytest.mark.parametrize("original", ERRORS, ids=lambda e: type(e).__name__)
def test_an_error_survives_as_the_class_it_was_with_every_field(original):
    """isinstance and attribute access are what chat/formatting.py does.

    Flattening to a string would leave render_error with nothing to read and
    would silently downgrade a structured recovery into a generic apology.
    """
    rebuilt = decode_error(encode_error(original))

    assert type(rebuilt) is type(original)
    assert isinstance(rebuilt, CalculatorError)
    assert str(rebuilt) == str(original)
    assert vars(rebuilt) == vars(original)


def test_every_calculator_error_subclass_can_cross():
    """The load-bearing assumption, asserted rather than trusted.

    encode/decode rely on every subclass taking (message, **fields) and
    storing each field under its own name. A subclass that breaks that fails
    here, at the seam, instead of at the moment a user hits it.
    """
    transportable = {type(error).__name__ for error in ERRORS}

    assert set(error_types()) == transportable


def test_an_error_class_outside_the_calculator_tree_cannot_be_constructed():
    """Wire data names a class. Only these classes."""
    for forbidden in ("SystemExit", "OSError", "ToolTransportError"):
        with pytest.raises(WireError):
            decode_error({"type": forbidden, "message": "x", "data": {}})


def test_a_field_json_cannot_represent_fails_at_the_seam():
    """Loudly here beats a NaN arriving somewhere it will be printed."""
    with pytest.raises(WireError):
        encode_error(InvalidAmountError("nan", field="x", value=math.nan))


# --------------------------------------------------------------------------
# The protocol
# --------------------------------------------------------------------------


def test_initialize_advertises_tools_and_nothing_it_does_not_have():
    result = call("initialize")["result"]

    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "bfcsofttech-calculators"


def test_the_initialized_notification_gets_no_reply():
    """A notification has no id; answering one desynchronises the stream."""
    assert server_module.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_returns_the_definitions():
    assert call("tools/list")["result"]["tools"] == tool_definitions()


def test_a_successful_call_carries_both_text_and_structure():
    """The structure is for this client; the text is for every other one."""
    result = call("tools/call", {"name": "loan_tenure", "arguments": L1})["result"]

    assert result["isError"] is False
    assert result["structuredContent"]["ok"] is True
    assert json.loads(result["content"][0]["text"])["months"] == 63


def test_a_calculator_failure_is_a_result_not_a_json_rpc_error():
    """MCP draws the line at 'could the call be made', and it could."""
    response = call("tools/call", {"name": "loan_tenure", "arguments": L4})

    assert "error" not in response
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"]["type"] == "EmiTooLowError"


def test_an_unknown_tool_is_a_json_rpc_error():
    """That call could not be made at all, which is the other kind."""
    response = call("tools/call", {"name": "compound_interest", "arguments": {}})

    assert response["error"]["code"] == -32602


def test_an_unknown_method_is_a_json_rpc_error():
    assert call("does/not/exist")["error"]["code"] == -32601


def test_arguments_the_signature_refuses_come_back_as_a_tool_error():
    response = call("tools/call", {"name": "loan_tenure", "arguments": {"nope": 1}})

    assert response["result"]["isError"] is True
    assert "invalidArguments" in response["result"]["structuredContent"]


def test_the_server_writes_only_json_rpc_to_stdout():
    """A stray print on stdout corrupts the stream for every later message."""
    import io

    stdout = io.StringIO()
    server_module.serve(
        io.StringIO(
            '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n'
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            '{"jsonrpc":"2.0","id":2,"method":"ping","params":{}}\n'
        ),
        stdout,
    )

    lines = stdout.getvalue().strip().splitlines()
    assert [json.loads(line)["id"] for line in lines] == [1, 2]  # notification unanswered


# --------------------------------------------------------------------------
# A live server, over a real pipe
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    started = McpStdioClient()
    yield started
    started.close()


@pytest.mark.subprocess
def test_the_tool_list_is_discoverable_over_stdio(client):
    assert [tool["name"] for tool in client.list_tools()] == list(CALCULATORS)


@pytest.mark.subprocess
def test_L1_over_stdio_is_identical_to_the_direct_call(client):
    """TEST_VECTORS.md L1: 63 payments, ₹2,245.30 final, ₹6,22,245.30 repaid."""
    over_mcp = client.call("loan_tenure", L1)

    assert isinstance(over_mcp, LoanTenure)
    assert over_mcp == loan_tenure(**L1)
    assert over_mcp.months == 63
    assert over_mcp.months_exact == pytest.approx(62.223905, abs=1e-6)
    assert over_mcp.final_payment == pytest.approx(2_245.296261, abs=1e-4)
    assert over_mcp.total_paid == pytest.approx(622_245.296261, abs=1e-4)


@pytest.mark.subprocess
def test_L4_over_stdio_raises_the_exception_with_its_numbers(client):
    """TEST_VECTORS.md L4. The client re-raises; the caller sees no boundary."""
    with pytest.raises(EmiTooLowError) as exc:
        client.call("loan_tenure", L4)

    assert exc.value.minimum_emi == pytest.approx(3_603.661658, abs=1e-4)
    assert exc.value.monthly_interest == pytest.approx(3_603.661658, abs=1e-4)
    assert exc.value.principal == 500_000
    assert exc.value.emi == 3_000


@pytest.mark.subprocess
def test_the_rendered_error_is_the_same_sentence_on_both_transports(client):
    """The end of the boundary problem: identical output, either way."""
    from chat.formatting import render_error

    with pytest.raises(EmiTooLowError) as direct:
        loan_tenure(**L4)
    with pytest.raises(EmiTooLowError) as over_mcp:
        client.call("loan_tenure", L4)

    assert render_error(over_mcp.value) == render_error(direct.value)


@pytest.mark.subprocess
def test_the_server_survives_being_asked_twice(client):
    """One process, many calls - the client does not respawn per calculation."""
    first = client.call("loan_tenure", L1)
    second = client.call("sip", {"target": 1_000_000, "annual_rate_pct": 12.0, "years": 10})

    assert first.months == 63
    assert second.months == 120


@pytest.mark.subprocess
def test_a_dead_server_is_a_transport_error_not_a_calculator_error():
    """The numbers were never in question, so this must not look like they were."""
    broken = McpStdioClient(command=[sys.executable, "-c", "raise SystemExit(1)"])

    with pytest.raises(ToolTransportError):
        broken.call("loan_tenure", L1)
    broken.close()


@pytest.mark.subprocess
def test_a_server_that_is_not_there_is_a_transport_error():
    missing = McpStdioClient(command=["./no-such-binary-at-all"])

    with pytest.raises(ToolTransportError):
        missing.list_tools()


# --------------------------------------------------------------------------
# Transport selection
# --------------------------------------------------------------------------


def test_the_default_transport_is_direct(monkeypatch):
    """A fresh clone runs the suite without spawning anything."""
    monkeypatch.delenv("CALCULATOR_TRANSPORT", raising=False)

    assert isinstance(build_tools(), DirectTools)


def test_the_environment_selects_the_transport(monkeypatch):
    monkeypatch.setenv("CALCULATOR_TRANSPORT", MCP)
    tools = build_tools()

    assert isinstance(tools, McpTools)
    tools.client.close()


@pytest.mark.parametrize("name", ["", "grpc", "MCP-ish", "directt"])
def test_an_unknown_transport_fails_loudly(name, monkeypatch):
    """Falling back to direct would report a green MCP run that never ran MCP."""
    monkeypatch.setenv("CALCULATOR_TRANSPORT", name)

    if name == "":
        assert isinstance(build_tools(), DirectTools)  # unset and empty are the same
    else:
        with pytest.raises(UnknownTransportError):
            build_tools()


@pytest.mark.parametrize("name", [DIRECT, MCP])
def test_both_transports_answer_L1_with_the_same_object(name):
    """The claim the whole phase rests on, asserted directly."""
    tools = build_tools(name)
    result = tools.invoke("loan_tenure", **L1)

    assert result == loan_tenure(**L1)
    if isinstance(tools, McpTools):
        tools.client.close()


def test_the_direct_transport_does_not_import_a_server():
    """Nothing spawns until something asks it to."""
    tools = DirectTools()

    assert tools.invoke("loan_tenure", **L1).months == 63


def test_a_session_reports_a_tool_outage_without_losing_its_slots():
    """The one thing the chat layer learned. Costs the turn, not the form."""
    from test_session import full_loan_flow
    from chat.session import State

    session, _stub, _reply = full_loan_flow()

    class DeadTools:
        def invoke(self, calculator_id, **arguments):
            raise ToolTransportError("pipe closed")

    session.tools = DeadTools()
    reply = session.handle("yes")

    assert "could not reach the calculators" in reply
    assert session.state is State.CONFIRMING
    assert session.slots == {"principal": 500_000.0, "emi": 10_000.0,
                             "annual_rate_pct": 9.0}
    assert reply.count("?") == 1
