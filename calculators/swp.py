"""Calculator 3 — systematic withdrawal plan.

                            (1 + r)^n - 1
    FV  =  P(1 + r)^n  -  W ---------------          # n is in MONTHS
                                  r

The closed form is happy to return a negative final balance, which would be
reported as a portfolio that "ended with minus three lakh" and, worse, as a
handsome profit. That is arithmetically consistent and financially nonsense,
so depletion is detected and reported instead. See ``DECISIONS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidAmountError, InvalidPeriodError
from .rates import monthly_rate
from .validation import validate_amount, validate_rate, validate_years

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class SwpProjection:
    """Result of an SWP projection.

    Attributes:
        final_balance: Closed-form FV, exactly as ``SPEC.md`` defines it.
            Negative when the corpus runs dry — the presentation layer must
            report ``depletion_month`` instead of showing this.
        total_withdrawn: The spec's ``W * n``. Once depleted this counts
            withdrawals that could not physically have happened; it is
            reported because the spec asks for it, not because it is real.
        total_profit: The spec's ``FV + total_withdrawn - P``. Meaningless
            once depleted, for the same reason.
        actual_withdrawn: What could really be taken — full withdrawals up to
            depletion plus one final partial. Equals ``total_withdrawn`` when
            the portfolio survives the term.
        depleted: True when ``final_balance < 0``.
        depletion_month: 1-based month in which the balance first hits <= 0,
            found by simulation rather than by inverting the formula.
    """

    final_balance: float
    total_withdrawn: float
    total_profit: float
    actual_withdrawn: float
    months: int
    monthly_rate: float
    depleted: bool
    depletion_month: int | None


def resolve_withdrawal(
    lumpsum: object,
    *,
    amount: object | None = None,
    percent: object | None = None,
) -> float:
    """Resolve a withdrawal given either as rupees or as a percent of lumpsum.

    Kept separate from :func:`swp_projection` so both input forms converge on
    one computation rather than drifting into two code paths, and so the chat
    layer can echo the resolved rupee figure back before computing.

    Args:
        lumpsum: The corpus P, greater than zero.
        amount: Monthly withdrawal in rupees. Mutually exclusive with percent.
        percent: Monthly withdrawal as a percent *of the lumpsum*, 0-100.

    Returns:
        The monthly withdrawal in rupees.

    Raises:
        InvalidAmountError: lumpsum invalid, withdrawal negative, or neither
            (or both) of amount and percent supplied.
        InvalidRateError: percent is non-numeric or outside 0-100.
    """
    corpus = validate_amount(lumpsum, "lumpsum amount")

    if (amount is None) == (percent is None):
        raise InvalidAmountError(
            "Give the withdrawal either as a monthly rupee amount or as a "
            "percent of the lumpsum — not both, and not neither.",
            field="monthly withdrawal",
            value=None,
        )

    if percent is not None:
        share = validate_rate(percent, "withdrawal percentage")
        return corpus * share / 100.0

    return validate_amount(amount, "monthly withdrawal", allow_zero=True)


def swp_projection(
    lumpsum: object,
    years: object,
    annual_rate_pct: object,
    monthly_withdrawal: object,
) -> SwpProjection:
    """Project a corpus drawn down by a fixed monthly withdrawal.

    Args:
        lumpsum: Corpus P, greater than zero.
        years: Term, 0 < years <= 100 and at least one whole month.
        annual_rate_pct: Expected annual return R, 0-100 inclusive.
        monthly_withdrawal: Withdrawal W in rupees. Zero is valid — it is a
            pure-growth projection. Use :func:`resolve_withdrawal` first if
            the user gave a percentage.

    Returns:
        A :class:`SwpProjection`.

    Raises:
        InvalidAmountError: lumpsum <= 0, withdrawal negative, or a single
            withdrawal larger than the whole corpus.
        InvalidRateError: rate is non-numeric or outside 0-100.
        InvalidPeriodError: years is invalid or shorter than one month.
    """
    corpus = validate_amount(lumpsum, "lumpsum amount")
    period = validate_years(years, "investment period")
    withdrawal = validate_amount(
        monthly_withdrawal,
        "monthly withdrawal",
        allow_zero=True,
        maximum=corpus,
        maximum_label="the lumpsum",
    )
    r = monthly_rate(annual_rate_pct)

    months = round(period * _MONTHS_PER_YEAR)
    if months < 1:
        raise InvalidPeriodError(
            f"investment period must cover at least one month — "
            f"{period:g} years does not.",
            field="investment period",
            value=period,
        )

    if r == 0.0:
        # ((1 + 0)^n - 1) / 0 is 0/0. With no growth the corpus simply
        # decreases by the withdrawal each month.
        final_balance = corpus - withdrawal * months
    else:
        growth = (1.0 + r) ** months
        final_balance = corpus * growth - withdrawal * ((growth - 1.0) / r)

    total_withdrawn = withdrawal * months
    depleted = final_balance < 0.0

    depletion_month: int | None = None
    actual_withdrawn = total_withdrawn
    if depleted:
        depletion_month, actual_withdrawn = _simulate_depletion(
            corpus, r, withdrawal, months
        )

    return SwpProjection(
        final_balance=final_balance,
        total_withdrawn=total_withdrawn,
        total_profit=final_balance + total_withdrawn - corpus,
        actual_withdrawn=actual_withdrawn,
        months=months,
        monthly_rate=r,
        depleted=depleted,
        depletion_month=depletion_month,
    )


def _simulate_depletion(
    corpus: float, r: float, withdrawal: float, months: int
) -> tuple[int, float]:
    """Find the month the balance first hits <= 0, and what was really taken.

    Only called when the closed form is negative. A non-negative FV cannot
    conceal an intermediate dip: the recurrence ``B(m+1) = B(m)(1+r) - W`` has
    fixed point ``B* = W/r``, below which the decline compounds and widens
    every month, so the sign change is one-way. See ``TEST_VECTORS.md``
    section 6.5, where that is proved and checked against 400,000 randomised
    scenarios.

    Returns:
        ``(depletion_month, actual_withdrawn)``, where ``actual_withdrawn``
        is the full withdrawals taken plus one final partial withdrawal of
        whatever remained.
    """
    balance = corpus
    withdrawn = 0.0

    for month in range(1, months + 1):
        balance *= 1.0 + r
        if balance <= withdrawal:
            # The corpus cannot fund a full withdrawal this month; the saver
            # takes what is left and the plan ends here.
            return month, withdrawn + balance
        balance -= withdrawal
        withdrawn += withdrawal

    # Unreachable while the monotonicity argument above holds; returning the
    # term end keeps the contract total rather than raising on an invariant.
    return months, withdrawn
