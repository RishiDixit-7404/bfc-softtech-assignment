"""Unit tests for the number/text boundary in chat/formatting.py.

The money figures asserted here come from TEST_VECTORS.md; the parser cases
are language, not finance - "5 lakh" is 500,000 by definition of the word.
"""

import pytest

from calculators.errors import InvalidAmountError
from calculators.validation import validate_amount
from chat.formatting import (
    compose,
    format_money,
    format_money_above,
    format_rate,
    format_tenure,
    format_years,
    parse_money,
    parse_rate,
    parse_withdrawal,
    parse_years,
    parse_yes_no,
    render_error,
    strip_questions,
)


@pytest.mark.parametrize(
    "span,expected",
    [
        ("10000", 10_000.0),
        ("10,000", 10_000.0),
        ("₹5,00,000", 500_000.0),
        ("Rs 10,000", 10_000.0),
        ("rs. 2500", 2_500.0),
        ("INR 3000", 3_000.0),
        ("5 lakh", 500_000.0),
        ("5lakh", 500_000.0),
        ("1.5 lakhs", 150_000.0),
        ("2cr", 20_000_000.0),
        ("2 crore", 20_000_000.0),
        ("50k", 50_000.0),
        ("8000 per month", 8_000.0),
        ("₹6,000 a month", 6_000.0),
    ],
)
def test_parse_money_reads_the_shapes_people_type(span, expected):
    assert parse_money(span) == pytest.approx(expected)


@pytest.mark.parametrize(
    "span", ["", "soon", "a lot", "five lakh", "10 bananas", "12.5.3", "-500"]
)
def test_parse_money_refuses_rather_than_guesses(span):
    """A refused span leaves the slot unfilled and gets asked again."""
    assert parse_money(span) is None


@pytest.mark.parametrize(
    "span,expected",
    [("9%", 9.0), ("9 %", 9.0), ("8.5", 8.5), ("12 percent", 12.0), ("9% p.a.", 9.0)],
)
def test_parse_rate_reads_percentages_as_written(span, expected):
    assert parse_rate(span) == pytest.approx(expected)


@pytest.mark.parametrize("span", ["", "high", "nine", "9 lakh", "9%-ish"])
def test_parse_rate_refuses_rather_than_guesses(span):
    assert parse_rate(span) is None


@pytest.mark.parametrize(
    "span,expected",
    [("10", 10.0), ("10 years", 10.0), ("1 year", 1.0), ("5yrs", 5.0), ("18 months", 1.5)],
)
def test_parse_years_reads_periods(span, expected):
    assert parse_years(span) == pytest.approx(expected)


@pytest.mark.parametrize(
    "span,expected",
    [("8000", ("money", 8_000.0)), ("0.8%", ("percent", 0.8)), ("0.8 percent", ("percent", 0.8))],
)
def test_parse_withdrawal_distinguishes_rupees_from_percent(span, expected):
    assert parse_withdrawal(span) == expected


@pytest.mark.parametrize("text,expected", [("yes", True), ("Yes, please", True), ("no", False), ("Nope.", False)])
def test_parse_yes_no_reads_a_confirmation(text, expected):
    assert parse_yes_no(text) is expected


@pytest.mark.parametrize("text", ["wait, what is an EMI?", "not sure yet", "8.5", "hold on"])
def test_parse_yes_no_declines_to_read_anything_else(text):
    """A digression must not be mistaken for a refusal at confirmation."""
    assert parse_yes_no(text) is None


@pytest.mark.parametrize(
    "amount,expected",
    [
        (0, "₹0.00"),
        (100, "₹100.00"),
        (1_000, "₹1,000.00"),
        (100_000, "₹1,00,000.00"),
        (1_000_000, "₹10,00,000.00"),
        (849_614.446908, "₹8,49,614.45"),
        (622_245.296261, "₹6,22,245.30"),
        (2_245.296261, "₹2,245.30"),
    ],
)
def test_format_money_uses_indian_grouping_to_two_decimals(amount, expected):
    assert format_money(amount) == expected


def test_format_money_above_clears_the_bound_it_is_given():
    """TEST_VECTORS.md L4: the minimum viable EMI on 5,00,000 at 9%."""
    assert format_money_above(3_603.661658) == "₹3,604"


def test_format_money_above_is_not_ceil_on_a_whole_rupee():
    """The bound is exclusive, so ceil(3,603.00) = 3,603 would not repay it."""
    assert format_money_above(3_603.0) == "₹3,604"


def test_render_error_does_not_forbid_a_zero_the_validator_allows():
    """A zero withdrawal is a valid pure-growth SWP, so only the sign is wrong.

    Telling the user it "has to be more than zero" would contradict the rule
    the calculator actually applied, and send them looking for a value that
    was never required.
    """
    with pytest.raises(InvalidAmountError) as exc:
        validate_amount(-500, "monthly withdrawal", allow_zero=True)

    assert render_error(exc.value) == (
        "The monthly withdrawal cannot be negative - I have -₹500.00."
    )


def test_render_error_does_forbid_zero_where_the_validator_forbids_it():
    with pytest.raises(InvalidAmountError) as exc:
        validate_amount(0, "loan amount")

    assert render_error(exc.value) == (
        "The loan amount has to be more than zero - I have ₹0.00."
    )


@pytest.mark.parametrize(
    "months,expected",
    [(63, "5 years & 3 months"), (90, "7 years & 6 months"), (12, "1 year"), (1, "1 month"), (0, "0 months")],
)
def test_format_tenure_reads_as_years_and_months(months, expected):
    assert format_tenure(months) == expected


def test_format_rate_and_years_drop_trailing_zeros():
    assert format_rate(9.0) == "9%"
    assert format_rate(8.5) == "8.5%"
    assert format_years(10.0) == "10 years"
    assert format_years(1) == "1 year"


def test_strip_questions_removes_a_question_the_model_asked():
    prose = "An EMI is a fixed monthly payment. Would you like an example?"
    assert strip_questions(prose) == "An EMI is a fixed monthly payment."


def test_strip_questions_keeps_something_when_the_whole_answer_is_a_question():
    assert "?" not in strip_questions("Have you considered a shorter tenure?")


def test_compose_produces_exactly_one_question():
    message = compose("Updated the rate to 8%. Shall I go on?", "What EMI do you plan to pay?")
    assert message.count("?") == 1
    assert message.endswith("What EMI do you plan to pay?")


def test_compose_rejects_a_message_that_would_ask_twice():
    """The invariant fails at the seam rather than reaching a person."""
    with pytest.raises(ValueError):
        compose("", "How much is the loan? And the EMI?")
