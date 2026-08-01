"""Calculator 1 — loan tenure.

    n = log( E / (E - P*r) ) / log(1 + r)      # n is in MONTHS

Valid only while ``E - P*r > 0``: an EMI that does not exceed the monthly
interest never touches the principal, and the closed form takes the log of a
non-positive number. That case is detected before the arithmetic runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import EmiTooLowError
from .rates import monthly_rate
from .validation import validate_amount

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class LoanTenure:
    """Result of a loan-tenure calculation.

    Attributes:
        months_exact: Unrounded n, e.g. 62.223905. The honest figure.
        months: ``ceil(months_exact)`` — a borrower cannot make 0.22 of a
            payment, so the loan runs one further (partial) month.
        years, remaining_months: ``months`` split for display, per the spec's
            "1.5 => 1 year & 6 months" example.
        final_payment: The last instalment, which is smaller than the EMI
            because ``months`` was rounded up.
        total_paid: ``(months - 1) * emi + final_payment``. Not ``months * emi``
            — that overstates the cost by charging a full final instalment.
        is_zero_rate: True on the R = 0 path, where the closed form degenerates.
    """

    months_exact: float
    months: int
    years: int
    remaining_months: int
    final_payment: float
    total_paid: float
    monthly_rate: float
    is_zero_rate: bool


def loan_tenure(
    principal: object, emi: object, annual_rate_pct: object
) -> LoanTenure:
    """Months needed to repay ``principal`` at a fixed ``emi``.

    Args:
        principal: Loan amount P, greater than zero.
        emi: Monthly instalment E, greater than zero.
        annual_rate_pct: Annual interest rate R, 0-100 inclusive.

    Returns:
        A :class:`LoanTenure`.

    Raises:
        InvalidAmountError: principal or EMI is non-numeric or <= 0.
        InvalidRateError: rate is non-numeric or outside 0-100.
        EmiTooLowError: ``E - P*r <= 0``. The boundary is inclusive — an EMI
            exactly equal to the monthly interest holds the balance flat
            forever, which is just as unrepayable as one below it.
    """
    p = validate_amount(principal, "loan amount")
    e = validate_amount(emi, "EMI")
    r = monthly_rate(annual_rate_pct)

    if r == 0.0:
        # A 0% loan is legitimate input, and log(1 + 0) is 0 — the closed form
        # divides by zero. It degenerates to simple division.
        months_exact = p / e
    else:
        monthly_interest = p * r
        if e - monthly_interest <= 0.0:
            raise EmiTooLowError(
                f"An EMI of {e:,.2f} does not cover the monthly interest of "
                f"{monthly_interest:,.2f} on a loan of {p:,.2f}. The balance "
                f"would never fall, so the loan is never repaid. The EMI has "
                f"to be above {math.ceil(monthly_interest):,}.",
                principal=p,
                emi=e,
                monthly_interest=monthly_interest,
                minimum_emi=monthly_interest,
            )
        months_exact = math.log(e / (e - monthly_interest)) / math.log(1.0 + r)

    months = math.ceil(months_exact)
    final_payment = _final_payment(p, e, r, months)

    return LoanTenure(
        months_exact=months_exact,
        months=months,
        years=months // _MONTHS_PER_YEAR,
        remaining_months=months % _MONTHS_PER_YEAR,
        final_payment=final_payment,
        total_paid=(months - 1) * e + final_payment,
        monthly_rate=r,
        is_zero_rate=r == 0.0,
    )


def _final_payment(p: float, e: float, r: float, months: int) -> float:
    """The last instalment: whatever is still owed after ``months - 1`` EMIs.

    Rounding the tenure up means the final month is partial. Charging a full
    EMI for it overstates the total cost by up to one instalment.
    """
    if r == 0.0:
        outstanding = p - (months - 1) * e
    else:
        grown = (1.0 + r) ** (months - 1)
        outstanding = (p * grown - e * ((grown - 1.0) / r)) * (1.0 + r)

    # The balance is settled by this payment, so it cannot be negative; only
    # float noise can push it a hair below zero on an exact-integer tenure.
    return max(0.0, outstanding)
