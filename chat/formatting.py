"""The boundary between numbers and text, in both directions.

*Inbound* — ``parse_money`` and friends turn a raw span the user typed
("5 lakh", "Rs 10,000", "0.8%") into a float. The language model is asked only
for the literal span; the conversion is done here, in Python, because a model
that returns "500000" for "5 lakh" is guessing and a model that returns
"5000000" is wrong in a way nothing downstream can detect. A span this module
rejects leaves the slot unfilled and gets asked again.

*Outbound* — money is formatted here and only here, in Indian grouping to two
decimals, at the moment it is shown. Everything upstream carries full float
precision.

This module also owns the one-question invariant: :func:`compose` is the only
way the state machine joins prose to a question, and it strips any question the
model tried to ask before appending the one the state machine chose.

No arithmetic on financial quantities happens here. The numbers rendered below
come from ``calculators/`` exactly as returned; splitting a month count into
years and months is display, not finance.
"""

from __future__ import annotations

import math
import re

from calculators import (
    CalculatorError,
    CalculatorSpec,
    EmiTooLowError,
    InvalidAmountError,
    LoanTenure,
    SipPlan,
    SwpProjection,
)

from . import prompts

_MONTHS_PER_YEAR = 12

# --------------------------------------------------------------------------
# Inbound: raw span -> float
# --------------------------------------------------------------------------

_MULTIPLIERS = {
    "k": 1e3,
    "thousand": 1e3,
    "thousands": 1e3,
    "l": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "lakh": 1e5,
    "lakhs": 1e5,
    "m": 1e6,
    "million": 1e6,
    "cr": 1e7,
    "crore": 1e7,
    "crores": 1e7,
}

_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-z]*)$")
_NOISE = re.compile(
    r"\b(per month|a month|every month|each month|monthly|"
    r"per annum|per year|a year|annually|p\.?a\.?|rupees|rs)\b"
)
_PERCENT_MARKER = re.compile(r"%|\bpercent\b|\bpct\b|\bper cent\b")

YES = frozenset(
    {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "correct",
     "right", "confirm", "confirmed", "proceed"}
)
NO = frozenset({"no", "n", "nope", "nah", "wrong", "incorrect"})


def _normalise(span: str) -> str:
    """Strip currency marks, separators and conversational noise."""
    text = span.strip().lower()
    text = text.replace("₹", " ").replace(",", "")
    text = re.sub(r"^(rs\.?|inr)\s*", " ", text)
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def parse_money(span: str) -> float | None:
    """Parse a rupee amount. Returns ``None`` if the span is not one.

    Understands plain digits, comma grouping, a leading rupee sign or "Rs",
    and the Indian magnitude words ("5 lakh", "2cr", "50k"). Anything else is
    refused rather than guessed at.
    """
    match = _NUMBER.match(_normalise(span))
    if match is None:
        return None

    value = float(match.group(1))
    suffix = match.group(2)
    if not suffix:
        return value
    if suffix not in _MULTIPLIERS:
        return None
    return value * _MULTIPLIERS[suffix]


def parse_rate(span: str) -> float | None:
    """Parse a percentage. Returns ``None`` if the span is not one.

    The value is returned as written - 9% is ``9.0``, not ``0.09``. Range
    checking belongs to ``calculators.validation``, which owns those rules.
    """
    text = _PERCENT_MARKER.sub(" ", _normalise(span)).strip()
    match = _NUMBER.match(text)
    if match is None or match.group(2):
        return None
    return float(match.group(1))


def parse_years(span: str) -> float | None:
    """Parse a period in years. A period given in months is converted here."""
    text = _normalise(span)
    months = re.match(r"^(\d+(?:\.\d+)?)\s*(months?|mos?)$", text)
    if months is not None:
        return float(months.group(1)) / _MONTHS_PER_YEAR

    text = re.sub(r"\s*(years?|yrs?)$", "", text).strip()
    match = _NUMBER.match(text)
    if match is None or match.group(2):
        return None
    return float(match.group(1))


def parse_withdrawal(span: str) -> tuple[str, float] | None:
    """Parse an SWP withdrawal given either way.

    Returns:
        ``("percent", value)`` or ``("money", value)``, or ``None`` if the
        span is neither.
    """
    if _PERCENT_MARKER.search(span.lower()):
        percent = parse_rate(span)
        return None if percent is None else ("percent", percent)

    amount = parse_money(span)
    return None if amount is None else ("money", amount)


def parse_yes_no(text: str) -> bool | None:
    """Read a confirmation. ``None`` when the message is neither.

    Only the opening word counts, so "not sure" is not a yes and "wait, what
    is an EMI" is not a no - both fall through to be handled as what they are.
    """
    words = re.findall(r"[a-z']+", text.lower())
    if not words:
        return None
    if words[0] in YES:
        return True
    if words[0] in NO:
        return False
    return None


# --------------------------------------------------------------------------
# Outbound: float -> text
# --------------------------------------------------------------------------


def _group_indian(digits: str) -> str:
    """Group digits as 12,34,567 - last three, then pairs."""
    if len(digits) <= 3:
        return digits

    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def format_money(amount: float) -> str:
    """Render a rupee amount as ``₹1,00,000.00``."""
    sign = "-" if amount < 0 else ""
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")
    return f"{sign}₹{_group_indian(whole)}.{fraction}"


def format_money_ceil(amount: float) -> str:
    """Render a rupee amount rounded *up* to the whole rupee.

    Used for a minimum viable EMI: rounding down would print a target that is
    still too low to repay the loan.
    """
    return f"₹{_group_indian(str(math.ceil(amount)))}"


def format_rate(percent: float) -> str:
    """Render a percentage as ``8.5%``."""
    return f"{percent:g}%"


def format_years(years: float) -> str:
    """Render a period as ``10 years``."""
    return f"{years:g} year" + ("" if years == 1 else "s")


def format_tenure(months: int) -> str:
    """Render a whole number of months as ``5 years & 3 months``."""
    years, remainder = divmod(int(months), _MONTHS_PER_YEAR)
    parts = []
    if years:
        parts.append(f"{years} year" + ("" if years == 1 else "s"))
    if remainder or not years:
        parts.append(f"{remainder} month" + ("" if remainder == 1 else "s"))
    return " & ".join(parts)


def format_slot_value(kind: str, value: float) -> str:
    """Render a collected slot value according to its kind."""
    if kind == "rate":
        return format_rate(value)
    if kind == "years":
        return format_years(value)
    return format_money(value)


# --------------------------------------------------------------------------
# Message composition
# --------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def strip_questions(prose: str) -> str:
    """Remove any question the model asked.

    The bot's questions come from the state machine. A model that ignores the
    instruction not to ask one would otherwise put two question marks in a
    message and leave the user unsure which to answer.
    """
    if not prose:
        return ""

    lines = []
    for line in prose.strip().splitlines():
        kept = [part for part in _SENTENCE.split(line.strip()) if "?" not in part]
        lines.append(" ".join(kept).strip())

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned or prose.replace("?", ".").strip()


def compose(prose: str, question: str) -> str:
    """Join optional prose to exactly one question.

    Raises:
        ValueError: the question does not contain exactly one question mark.
            That is a programming error in the state machine, not a user
            error, so it fails at the seam rather than reaching a person.
    """
    if question.count("?") != 1:
        raise ValueError(
            f"a bot message must ask exactly one question - got {question!r}"
        )

    body = strip_questions(prose)
    return f"{body}\n\n{question}" if body else question


# --------------------------------------------------------------------------
# Rendering results and errors
# --------------------------------------------------------------------------


def render_confirmation(
    spec: CalculatorSpec,
    slots: dict[str, float],
    notes: dict[str, str] | None = None,
) -> str:
    """Echo every collected value back, then ask for confirmation once."""
    notes = notes or {}
    lines = [prompts.CONFIRM_PREAMBLE]
    for parameter in spec.parameters:
        value = format_slot_value(parameter.kind, slots[parameter.name])
        note = notes.get(parameter.name)
        lines.append(
            f"- {parameter.label}: {value}" + (f" ({note})" if note else "")
        )

    return compose("\n".join(lines), prompts.confirm_question(spec.title))


def render_loan(result: LoanTenure) -> str:
    """Render a loan tenure, in years and months as the spec asks."""
    lines = [
        f"That loan is cleared in {format_tenure(result.months)}.",
        f"- Payments: {result.months}, rounded up from {result.months_exact:.2f} "
        f"months - the last month is a part payment, not a whole EMI.",
        f"- Final instalment: {format_money(result.final_payment)}.",
        f"- Total repaid: {format_money(result.total_paid)}.",
    ]
    if result.is_zero_rate:
        lines.append("- At 0% interest the term is simply the loan divided by the EMI.")
    return "\n".join(lines)


def render_sip(result: SipPlan, target: float, years: float, rate: float) -> str:
    """Render the monthly contribution a target needs."""
    return "\n".join(
        [
            f"To reach {format_money(target)} in {format_years(years)} at "
            f"{format_rate(rate)}, invest "
            f"{format_money(result.monthly_investment)} a month.",
            f"- Months of investing: {result.months:g}.",
            f"- Total put in: {format_money(result.total_invested)}.",
        ]
    )


def render_swp(result: SwpProjection, lumpsum: float, withdrawal: float) -> str:
    """Render an SWP projection, or the depletion month if the corpus dies.

    When ``depleted`` is true the closed form's final balance is negative and
    its profit figure is unreliable in both directions, so neither is shown -
    the month the money runs out is the answer to the question actually asked.
    """
    if result.depleted:
        year, month = divmod(result.depletion_month - 1, _MONTHS_PER_YEAR)
        return "\n".join(
            [
                f"Withdrawing {format_money(withdrawal)} a month exhausts "
                f"{format_money(lumpsum)} in month {result.depletion_month} of "
                f"{result.months} - that is year {year + 1}, month {month + 1}.",
                f"- Actually withdrawn before it ran dry: "
                f"{format_money(result.actual_withdrawn)}, the final month "
                f"being a part withdrawal.",
                "- The remaining months of the plan cannot be funded. Lower the "
                "withdrawal, shorten the term, or start with more.",
            ]
        )

    return "\n".join(
        [
            f"Withdrawing {format_money(withdrawal)} a month from "
            f"{format_money(lumpsum)} over {result.months} months:",
            f"- Final balance: {format_money(result.final_balance)}.",
            f"- Total withdrawn: {format_money(result.total_withdrawn)}.",
            f"- Total profit: {format_money(result.total_profit)}.",
        ]
    )


def render_error(error: CalculatorError) -> str:
    """Turn a calculator exception into something a person can act on.

    Reads the exception's attributes rather than ``str(exc)`` wherever money
    is involved, so the amounts appear in the same Indian grouping as every
    other figure the bot prints.
    """
    if isinstance(error, EmiTooLowError):
        return (
            f"An EMI of {format_money(error.emi)} does not cover the monthly "
            f"interest of {format_money(error.monthly_interest)} on a loan of "
            f"{format_money(error.principal)}, so the balance would never fall "
            f"and the loan would never be repaid. The EMI has to be above "
            f"{format_money_ceil(error.minimum_emi)}."
        )

    if isinstance(error, InvalidAmountError) and isinstance(error.value, (int, float)):
        amount = format_money(float(error.value))
        if error.maximum is not None and error.value > error.maximum:
            return (
                f"The {error.field} cannot be more than "
                f"{format_money(error.maximum)} - I have {amount}."
            )
        return f"The {error.field} has to be more than zero - I have {amount}."

    return str(error)
