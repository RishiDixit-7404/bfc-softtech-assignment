"""Tool definitions, derived rather than written out.

Names and parameter order come from ``calculators.CALCULATORS``; the numeric
bounds come from ``calculators.validation``'s own constants. Neither is
restated here, so a tool cannot advertise a range the validator will reject or
a parameter the function does not take.

The descriptions are written for a caller that is *not* this chatbot, because
that is the only kind of caller a schema is for. Two things are easy to get
wrong from the outside and are therefore spelled out at every parameter that
has them: rates are percentages as written (``9`` means 9% a year, not 0.09),
and periods are in years while several of the outputs are in months.

A note on ``CLAUDE.md`` §3, which puts all prompt text in ``chat/prompts.py``:
these strings are read by models, so the question is fair. They are an API
contract rather than conversational copy — units, bounds and formulas, no
instruction to any model about how to behave — and an MCP client that is not a
model reads exactly the same text. ``DECISIONS.md`` D26 records the call.
"""

from __future__ import annotations

from calculators import CALCULATORS, CalculatorSpec, Parameter
from calculators.validation import MAX_RATE, MAX_YEARS, MIN_RATE

# The effective-monthly-rate conversion, quoted so a caller can see what its
# annual percentage becomes. It is the one formula shared by all three tools.
_RATE_NOTE = (
    "Annual rate as a percentage written the way people say it: 9 means "
    "9% a year, not 0.09. Converted internally to the effective monthly rate "
    "(1 + R/100)^(1/12) - 1, which is not R/12."
)

_TOOL_DESCRIPTIONS = {
    "loan_tenure": (
        "How many months a loan takes to repay at a fixed EMI. "
        "n = log(E / (E - P*r)) / log(1 + r), where r is the effective monthly "
        "rate. Returns the exact month count and the whole number of payments "
        "it rounds up to, the smaller final instalment that rounding implies, "
        "and the total actually repaid. Fails if the EMI does not exceed the "
        "monthly interest, because then the balance never falls."
    ),
    "sip": (
        "The monthly investment needed to reach a target amount. "
        "SIP = (Target * r / ((1 + r)^(n*12) - 1)) * (1 + r), with n in years. "
        "Note the trailing multiplication: this is the client's specified "
        "formula, and it differs from a standard annuity-due solve, which "
        "divides by (1 + r) instead. See DECISIONS.md D2."
    ),
    "swp": (
        "How a lumpsum holds up while a fixed amount is withdrawn monthly. "
        "FV = P(1 + r)^n - W * ((1 + r)^n - 1) / r, with n in months. Returns "
        "the closed-form final balance, total withdrawn and total profit, plus "
        "- when withdrawals outrun growth - the month the corpus runs dry and "
        "what could actually be taken before it did. A negative final balance "
        "means the plan depleted; read depletion_month, not final_balance."
    ),
}

_PARAMETER_SCHEMAS = {
    "money": {
        "type": "number",
        "exclusiveMinimum": 0,
        "units": "INR",
    },
    "rate": {
        "type": "number",
        "minimum": MIN_RATE,
        "maximum": MAX_RATE,
        "units": "percent per year",
    },
    "years": {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": MAX_YEARS,
        "units": "years",
    },
    # swp_projection takes rupees. A withdrawal given as a percentage of the
    # lumpsum is resolved to rupees before it gets here, so the tool never has
    # to guess which of the two it was handed.
    "money_or_percent": {
        "type": "number",
        "minimum": 0,
        "units": "INR",
    },
}

_PARAMETER_NOTES = {
    "money": "Rupee amount, greater than zero.",
    "rate": _RATE_NOTE,
    "years": (
        f"Period in years, greater than 0 and at most {MAX_YEARS:g}. Must "
        f"cover at least one whole month: pass 0.5 for six months, not 6."
    ),
    "money_or_percent": (
        "Monthly withdrawal in rupees. Zero is valid and means a pure-growth "
        "projection. Must not exceed the lumpsum. If you have a percentage of "
        "the lumpsum instead, resolve it first: W = lumpsum * percent / 100."
    ),
}


def _parameter_schema(parameter: Parameter) -> dict:
    """One parameter's JSON Schema, with its units and bounds stated."""
    schema = dict(_PARAMETER_SCHEMAS[parameter.kind])
    schema["description"] = f"{parameter.label.capitalize()}. {_PARAMETER_NOTES[parameter.kind]}"
    return schema


def _input_schema(spec: CalculatorSpec) -> dict:
    """An object schema over the calculator's parameters. All are required."""
    return {
        "type": "object",
        "properties": {
            parameter.name: _parameter_schema(parameter)
            for parameter in spec.parameters
        },
        "required": [parameter.name for parameter in spec.parameters],
        "additionalProperties": False,
    }


def tool_definitions() -> list[dict]:
    """Every calculator as an MCP tool definition, in registry order."""
    return [
        {
            "name": spec.id,
            "title": spec.title,
            "description": _TOOL_DESCRIPTIONS[spec.id],
            "inputSchema": _input_schema(spec),
        }
        for spec in CALCULATORS.values()
    ]


TOOLS: list[dict] = tool_definitions()
