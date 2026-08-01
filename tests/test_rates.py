"""TEST_VECTORS.md section 0 — the monthly rate.

If this file is wrong, every other number in the repository is wrong.
"""

import pytest

from calculators.errors import InvalidRateError
from calculators.rates import monthly_rate

RATE_TOLERANCE = 1e-6

# TEST_VECTORS.md section 0.
VECTORS = [
    (8.0, 0.0064340301, 0.0066666667),
    (8.5, 0.0068214934, 0.0070833333),
    (9.0, 0.0072073233, 0.0075000000),
    (10.0, 0.0079741404, 0.0083333333),
    (12.0, 0.0094887929, 0.0100000000),
]


@pytest.mark.parametrize("annual, expected, _naive", VECTORS)
def test_monthly_rate_matches_vectors(annual, expected, _naive):
    assert monthly_rate(annual) == pytest.approx(expected, abs=RATE_TOLERANCE)


@pytest.mark.parametrize("annual, _expected, naive", VECTORS)
def test_monthly_rate_is_not_the_naive_division(annual, _expected, naive):
    """The effective rate must differ from R/1200 at every tested rate."""
    assert monthly_rate(annual) != pytest.approx(naive, abs=RATE_TOLERANCE)


def test_monthly_rate_guard_twelve_percent_is_not_one_percent():
    """Section 0's named guard. If this fails, someone reintroduced R/1200."""
    assert monthly_rate(12.0) != 0.01


def test_monthly_rate_at_zero_is_exactly_zero():
    assert monthly_rate(0) == 0.0


def test_monthly_rate_accepts_both_boundaries():
    assert monthly_rate(0.0) == 0.0
    assert monthly_rate(100.0) > 0.0


@pytest.mark.parametrize("bad", [-0.1, -1, 100.1, 101, 1000])
def test_monthly_rate_rejects_out_of_range(bad):
    with pytest.raises(InvalidRateError) as exc:
        monthly_rate(bad)
    assert "0" in str(exc.value) and "100" in str(exc.value)


@pytest.mark.parametrize("bad", ["nine", None, float("nan"), float("inf")])
def test_monthly_rate_rejects_non_numeric(bad):
    with pytest.raises(InvalidRateError):
        monthly_rate(bad)
