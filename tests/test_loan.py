"""TEST_VECTORS.md sections 1, 1.3 and 6.1 — loan tenure.

Every expected value is taken verbatim from TEST_VECTORS.md.
"""

import math

import pytest

from calculators.errors import (
    CalculatorError,
    EmiTooLowError,
    InvalidAmountError,
    InvalidRateError,
)
from calculators.loan import loan_tenure
from calculators.rates import monthly_rate

MONEY_TOLERANCE = 1e-4

# TEST_VECTORS.md section 1.1: P, E, R, n exact, ceil, years, months
VALID = {
    "L1": (500_000, 10_000, 9.0, 62.223905, 63, 5, 3),
    "L2": (1_000_000, 15_000, 8.5, 89.219033, 90, 7, 6),
    "L3": (250_000, 5_000, 12.0, 68.115878, 69, 5, 9),
}

# TEST_VECTORS.md section 1.3: final_payment, total_paid.
FINAL_PAYMENT = {"L1": 2_245.296261, "L2": 3_294.224396, "L3": 581.814006}
TOTAL_PAID = {"L1": 622_245.296261, "L2": 1_338_294.224396, "L3": 340_581.814006}

# TEST_VECTORS.md section 1.2: P, E, R, minimum viable EMI (P*r)
EMI_TOO_LOW = {
    "L4": (500_000, 3_000, 9.0, 3_603.661658),
    "L5": (1_000_000, 5_000, 8.5, 6_821.493366),
    "L6": (250_000, 2_000, 12.0, 2_372.198234),
}

# TEST_VECTORS.md section 6.1: zero-rate loans.
ZERO_RATE = {
    "L11a": (500_000, 10_000, 50.0, 50, 4, 2),
    "L11b": (250_000, 5_000, 50.0, 50, 4, 2),
}


@pytest.mark.parametrize("case", VALID)
def test_L1_L3_tenure_matches_vectors(case):
    p, e, r, exact, months, years, remaining = VALID[case]
    result = loan_tenure(p, e, r)

    assert result.months_exact == pytest.approx(exact, abs=1e-6)
    assert result.months == months
    assert result.years == years
    assert result.remaining_months == remaining
    assert result.monthly_rate == pytest.approx(monthly_rate(r), abs=1e-12)
    assert result.is_zero_rate is False


@pytest.mark.parametrize("case", VALID)
def test_L1_L3_tenure_is_ceiled_not_truncated(case):
    """A borrower cannot make 0.22 of a payment, so the term rounds up."""
    p, e, r, exact, months, _years, _remaining = VALID[case]
    assert loan_tenure(p, e, r).months == math.ceil(exact) == months


@pytest.mark.parametrize("case", VALID)
def test_L1_L3_total_paid_accounts_for_a_partial_final_payment(case):
    p, e, r, _exact, months, _years, _remaining = VALID[case]
    result = loan_tenure(p, e, r)

    assert result.final_payment == pytest.approx(
        FINAL_PAYMENT[case], abs=MONEY_TOLERANCE
    )
    assert result.total_paid == pytest.approx(TOTAL_PAID[case], abs=MONEY_TOLERANCE)
    assert result.total_paid == pytest.approx(
        (months - 1) * e + result.final_payment, abs=MONEY_TOLERANCE
    )
    assert 0.0 < result.final_payment < e


@pytest.mark.parametrize("case", VALID)
def test_L1_L3_total_paid_is_below_the_naive_months_times_emi(case):
    """months * emi charges a full final instalment that is never paid."""
    p, e, r, _exact, months, _years, _remaining = VALID[case]
    assert loan_tenure(p, e, r).total_paid < months * e


@pytest.mark.parametrize("case", VALID)
def test_L1_L3_cross_checked_by_amortisation(case):
    """Independent oracle: amortise month by month and count the payments."""
    p, e, r, _exact, months, _years, _remaining = VALID[case]
    rate = monthly_rate(r)

    balance, paid = float(p), 0
    while balance > 0:
        balance = balance * (1.0 + rate) - e
        paid += 1
        assert paid <= 1200, "loan is not amortising"

    assert paid == months


@pytest.mark.parametrize("case", EMI_TOO_LOW)
def test_L4_L6_emi_below_monthly_interest_is_rejected(case):
    p, e, r, minimum = EMI_TOO_LOW[case]

    with pytest.raises(EmiTooLowError) as exc:
        loan_tenure(p, e, r)

    assert exc.value.minimum_emi == pytest.approx(minimum, abs=MONEY_TOLERANCE)
    assert exc.value.monthly_interest == pytest.approx(minimum, abs=MONEY_TOLERANCE)
    assert exc.value.emi == e
    assert exc.value.principal == p
    # The message must name the minimum viable EMI, rounded up.
    assert f"{math.ceil(minimum):,}" in str(exc.value)


def test_L7_emi_exactly_equal_to_interest_is_rejected():
    """The boundary is inclusive: E == P*r holds the balance flat forever."""
    principal = 500_000
    emi = principal * monthly_rate(9.0)

    with pytest.raises(EmiTooLowError):
        loan_tenure(principal, emi, 9.0)


@pytest.mark.parametrize("bad", [0, -1, -500_000])
def test_L8_non_positive_principal_is_rejected(bad):
    with pytest.raises(InvalidAmountError) as exc:
        loan_tenure(bad, 10_000, 9.0)
    assert exc.value.field == "loan amount"


@pytest.mark.parametrize("bad", [0, -1, -10_000])
def test_L9_non_positive_emi_is_rejected(bad):
    with pytest.raises(InvalidAmountError) as exc:
        loan_tenure(500_000, bad, 9.0)
    assert exc.value.field == "EMI"


@pytest.mark.parametrize("bad", [-0.1, -1, 100.1, 150])
def test_L10_rate_outside_zero_to_hundred_is_rejected(bad):
    with pytest.raises(InvalidRateError) as exc:
        loan_tenure(500_000, 10_000, bad)
    assert "0" in str(exc.value) and "100" in str(exc.value)


@pytest.mark.parametrize("case", ZERO_RATE)
def test_L11_zero_rate_loan_degenerates_to_principal_over_emi(case):
    p, e, exact, months, years, remaining = ZERO_RATE[case]
    result = loan_tenure(p, e, 0)

    assert result.months_exact == pytest.approx(exact, abs=1e-9)
    assert result.months == months
    assert result.years == years
    assert result.remaining_months == remaining
    assert result.is_zero_rate is True
    assert result.monthly_rate == 0.0
    # No growth, so the borrower repays exactly the principal.
    assert result.total_paid == pytest.approx(p, abs=MONEY_TOLERANCE)


def test_L11_zero_rate_raises_no_arithmetic_error():
    """log(1 + 0) is 0 — the closed form must never be evaluated here."""
    try:
        loan_tenure(500_000, 10_000, 0)
    except (ZeroDivisionError, ValueError, OverflowError) as exc:  # pragma: no cover
        pytest.fail(f"zero-rate loan leaked an arithmetic error: {exc!r}")


def test_L11_zero_rate_partial_final_month_still_rounds_up():
    """P/E = 50.5 months: the final instalment is the leftover half."""
    result = loan_tenure(505_000, 10_000, 0)

    assert result.months_exact == pytest.approx(50.5, abs=1e-9)
    assert result.months == 51
    assert result.final_payment == pytest.approx(5_000.0, abs=MONEY_TOLERANCE)
    assert result.total_paid == pytest.approx(505_000.0, abs=MONEY_TOLERANCE)


def test_loan_errors_are_calculator_errors():
    with pytest.raises(CalculatorError):
        loan_tenure(500_000, 3_000, 9.0)
