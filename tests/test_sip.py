"""TEST_VECTORS.md sections 2 and 6.2 — SIP for a target amount.

The spec formula multiplies by (1 + r) where an annuity-due solve divides.
It is implemented verbatim; the deviation is documented by assertion here and
in prose in DECISIONS.md D2.
"""

import pytest

from calculators.errors import (
    InvalidAmountError,
    InvalidPeriodError,
    InvalidRateError,
)
from calculators.rates import monthly_rate
from calculators.sip import sip_for_target

MONEY_TOLERANCE = 1e-4

# TEST_VECTORS.md section 2: target, R, years, SIP per the spec formula.
SPEC = {
    "S1": (1_000_000, 12.0, 10, 4_548.680236),
    "S2": (5_000_000, 10.0, 15, 12_648.881856),
    "S3": (200_000, 8.0, 3, 4_986.621222),
}

# TEST_VECTORS.md section 2.1: spec, ordinary annuity, annuity-due.
DISCREPANCY = {
    "S1": (4_548.680236, 4_505.924452, 4_463.570555),
    "S2": (12_648.881856, 12_548.815836, 12_449.541445),
    "S3": (4_986.621222, 4_954.742261, 4_923.067099),
}

# TEST_VECTORS.md section 6.2: zero-rate SIPs.
ZERO_RATE = {
    "S6a": (200_000, 3, 5_555.555556),
    "S6b": (1_000_000, 10, 8_333.333333),
}


@pytest.mark.parametrize("case", SPEC)
def test_sip_matches_spec_formula(case):
    """The graded behaviour: SPEC.md as written, including the x (1 + r)."""
    target, rate, years, expected = SPEC[case]
    result = sip_for_target(target, rate, years)

    assert result.monthly_investment == pytest.approx(expected, abs=MONEY_TOLERANCE)
    assert result.months == pytest.approx(years * 12)
    assert result.total_invested == pytest.approx(
        expected * years * 12, abs=MONEY_TOLERANCE
    )
    assert result.is_zero_rate is False


@pytest.mark.parametrize("case", DISCREPANCY)
def test_sip_spec_overshoots_annuity_due_by_one_plus_r_squared(case):
    """Identifies the deviation precisely rather than hand-waving at it.

    An annuity-due solve divides by (1 + r); the spec multiplies. The gap is
    therefore exactly (1 + r) squared, at every rate and every term.
    """
    target, rate, years, _ = SPEC[case]
    spec_value, ordinary, due = DISCREPANCY[case]
    r = monthly_rate(rate)

    computed = sip_for_target(target, rate, years).monthly_investment

    assert computed == pytest.approx(spec_value, abs=MONEY_TOLERANCE)
    assert computed / due == pytest.approx((1.0 + r) ** 2, abs=1e-8)
    assert computed / ordinary == pytest.approx(1.0 + r, abs=1e-8)


def test_sip_spec_value_simulates_to_the_documented_overshoot():
    """S1 contributed monthly then compounded 120 times reaches 1,019,067.62.

    Independent oracle for section 2.1: the overshoot against the ₹10,00,000
    target is real money, not a rounding artefact.
    """
    target, rate, years, _ = SPEC["S1"]
    contribution = sip_for_target(target, rate, years).monthly_investment
    r = monthly_rate(rate)

    balance = 0.0
    for _ in range(years * 12):
        balance = (balance + contribution) * (1.0 + r)

    assert balance == pytest.approx(1_019_067.62, abs=1e-2)
    assert balance - target == pytest.approx(19_067.62, abs=1e-2)


@pytest.mark.parametrize("bad", [0, -1, -200_000])
def test_S4_non_positive_target_is_rejected(bad):
    with pytest.raises(InvalidAmountError) as exc:
        sip_for_target(bad, 12.0, 10)
    assert exc.value.field == "target amount"


@pytest.mark.parametrize("bad", [0, -1, -10, 101])
def test_S5_period_outside_range_is_rejected(bad):
    with pytest.raises(InvalidPeriodError) as exc:
        sip_for_target(1_000_000, 12.0, bad)
    assert exc.value.field == "investment period"


@pytest.mark.parametrize("bad", [0.01, 0.04])
def test_S5_a_period_shorter_than_one_month_is_rejected(bad):
    """validate_years only rules out years <= 0, which leaves this gap.

    swp_projection already refuses the same window. A plan holding zero
    contributions is not a shorter plan, and splitting a target across 0.12
    months is not an answer to any question a person asked.
    """
    with pytest.raises(InvalidPeriodError) as exc:
        sip_for_target(1_000_000, 12.0, bad)
    assert exc.value.field == "investment period"


def test_S5_one_whole_month_is_the_shortest_accepted_period():
    """1/12 of a year times 12 is 0.9999999999999999, which must round to 1."""
    assert sip_for_target(1_000_000, 12.0, 1 / 12).months == 1


@pytest.mark.parametrize("case", ZERO_RATE)
def test_S6_zero_rate_degenerates_to_target_over_months(case):
    target, years, expected = ZERO_RATE[case]
    result = sip_for_target(target, 0, years)

    assert result.monthly_investment == pytest.approx(expected, abs=MONEY_TOLERANCE)
    assert result.is_zero_rate is True
    assert result.monthly_rate == 0.0
    # With no growth the contributions must sum to exactly the target.
    assert result.total_invested == pytest.approx(target, abs=MONEY_TOLERANCE)


def test_S6_zero_rate_raises_no_arithmetic_error():
    try:
        sip_for_target(200_000, 0, 3)
    except (ZeroDivisionError, OverflowError) as exc:  # pragma: no cover
        pytest.fail(f"zero-rate SIP leaked an arithmetic error: {exc!r}")


@pytest.mark.parametrize("bad", [100.1, 150, -1])
def test_S7_rate_outside_zero_to_hundred_is_rejected(bad):
    with pytest.raises(InvalidRateError) as exc:
        sip_for_target(1_000_000, bad, 10)
    assert "0" in str(exc.value) and "100" in str(exc.value)
