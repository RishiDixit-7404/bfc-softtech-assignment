"""Shared input guards.

Every public calculator runs these *before* any arithmetic. They live in one
module so the amount/rate/period rules cannot drift between loan, SIP and SWP.

Each guard returns the coerced ``float`` so callers can use the return value
directly and never touch the raw argument again.
"""

from __future__ import annotations

import math

from .errors import InvalidAmountError, InvalidPeriodError, InvalidRateError

MIN_RATE = 0.0
MAX_RATE = 100.0
MAX_YEARS = 100.0


def _coerce(value: object, field: str, error: type, **kwargs: object) -> float:
    """Convert to float, rejecting non-numeric input and NaN/inf."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error(
            f"{field} must be a number — got {value!r}.",
            field=field,
            value=value,
            **kwargs,
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise error(
            f"{field} must be a finite number — got {value!r}.",
            field=field,
            value=value,
            **kwargs,
        )
    return number


def validate_amount(
    value: object,
    field: str,
    *,
    allow_zero: bool = False,
    maximum: float | None = None,
    maximum_label: str | None = None,
) -> float:
    """Reject non-numeric, NaN/inf, and non-positive money amounts."""
    amount = _coerce(value, field, InvalidAmountError, minimum=0.0, maximum=maximum)

    if allow_zero and amount < 0.0:
        raise InvalidAmountError(
            f"{field} cannot be negative — got {amount:,.2f}.",
            field=field,
            value=amount,
            minimum=0.0,
        )
    if not allow_zero and amount <= 0.0:
        raise InvalidAmountError(
            f"{field} must be greater than zero — got {amount:,.2f}.",
            field=field,
            value=amount,
            minimum=0.0,
        )
    if maximum is not None and amount > maximum:
        label = maximum_label or f"{maximum:,.2f}"
        raise InvalidAmountError(
            f"{field} cannot exceed {label} — got {amount:,.2f}.",
            field=field,
            value=amount,
            maximum=maximum,
        )
    return amount


def validate_rate(value: object, field: str = "interest rate") -> float:
    """Reject any percentage outside 0-100. Both bounds are inclusive."""
    rate = _coerce(value, field, InvalidRateError)

    if rate < MIN_RATE or rate > MAX_RATE:
        raise InvalidRateError(
            f"{field} must be between {MIN_RATE:g} and {MAX_RATE:g} percent — "
            f"got {rate:g}.",
            field=field,
            value=rate,
        )
    return rate


def validate_years(value: object, field: str = "investment period") -> float:
    """Reject any period outside 0 < years <= 100."""
    years = _coerce(value, field, InvalidPeriodError)

    if years <= 0.0 or years > MAX_YEARS:
        raise InvalidPeriodError(
            f"{field} must be more than 0 and at most {MAX_YEARS:g} years — "
            f"got {years:g}.",
            field=field,
            value=years,
        )
    return years
