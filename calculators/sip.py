"""Calculator 2 — monthly SIP needed to reach a target.

``SPEC.md`` states the formula as:

                 Target * r
    SIP  =  --------------------  x  (1 + r)          # n in YEARS
             (1 + r)^(n*12) - 1

The trailing ``x (1 + r)`` is implemented verbatim. It is *not* the standard
annuity-due solve, which divides by ``(1 + r)`` instead; the spec's result
overshoots the target by exactly ``(1 + r)^2``. See ``DECISIONS.md`` and
``TEST_VECTORS.md`` section 2.1 — the deviation is asserted by a test rather
than silently corrected here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidPeriodError
from .rates import monthly_rate
from .validation import validate_amount, validate_years

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class SipPlan:
    """Result of a SIP calculation.

    Attributes:
        monthly_investment: The spec formula's answer — the graded number.
        months: ``round(years * 12)``. Rounded for the same reason
            :func:`swp_projection` rounds: contributions are whole months, and
            "10 months" arrives here as 0.8333… years, whose product with 12
            is 9.999999999999998.
        total_invested: Nominal outlay, ``monthly_investment * months``.
        is_zero_rate: True on the R = 0 path, where the closed form degenerates.
    """

    monthly_investment: float
    months: int
    total_invested: float
    monthly_rate: float
    is_zero_rate: bool


def sip_for_target(
    target: object, annual_rate_pct: object, years: object
) -> SipPlan:
    """Monthly contribution needed to reach ``target`` in ``years``.

    Args:
        target: Desired maturity amount, greater than zero.
        annual_rate_pct: Expected annual return R, 0-100 inclusive.
        years: Investment period, 0 < years <= 100.

    Returns:
        A :class:`SipPlan`.

    Raises:
        InvalidAmountError: target is non-numeric or <= 0.
        InvalidRateError: rate is non-numeric or outside 0-100.
        InvalidPeriodError: years is invalid, or shorter than one whole month.
    """
    amount = validate_amount(target, "target amount")
    period = validate_years(years, "investment period")
    r = monthly_rate(annual_rate_pct)

    months = round(period * _MONTHS_PER_YEAR)
    if months < 1:
        # validate_years only rules out years <= 0, which leaves periods too
        # short to contain a single contribution. swp_projection refuses the
        # same window; a plan of zero instalments is not a smaller plan.
        raise InvalidPeriodError(
            f"investment period must cover at least one month — "
            f"{period:g} years does not.",
            field="investment period",
            value=period,
        )

    if r == 0.0:
        # (1 + 0)^n - 1 is 0, so the closed form divides by zero. With no
        # growth the contribution is simply the target split across the term.
        monthly_investment = amount / months
    else:
        growth = (1.0 + r) ** months - 1.0
        monthly_investment = (amount * r / growth) * (1.0 + r)

    return SipPlan(
        monthly_investment=monthly_investment,
        months=months,
        total_invested=monthly_investment * months,
        monthly_rate=r,
        is_zero_rate=r == 0.0,
    )
