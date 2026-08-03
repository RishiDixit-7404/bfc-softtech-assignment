"""The one and only monthly-rate definition in this repository.

``SPEC.md`` gives the effective annual-to-monthly conversion:

    r = (1 + R/100)^(1/12) - 1

This is *not* the naive nominal division that appears in most EMI snippets.
The two differ materially — at R = 12 the effective monthly rate is
0.0094887929 against a naive 0.01 — and every number downstream inherits the
error. Any other monthly-rate expression anywhere in this codebase is a bug.
"""

from __future__ import annotations

from .validation import validate_rate

_MONTHS_PER_YEAR = 12.0


def monthly_rate(annual_rate_pct: object) -> float:
    """Effective monthly rate for an annual percentage rate.

    Args:
        annual_rate_pct: Annual rate as a percentage, 0-100 inclusive.

    Returns:
        The effective monthly rate as a decimal fraction. Exactly ``0.0``
        when the annual rate is zero — ``1.0 ** x`` is exactly 1.0, so the
        degenerate case needs no special branch here. Callers must still
        branch on it, because the closed forms divide by it.

    Raises:
        InvalidRateError: rate is non-numeric or outside 0-100.
    """
    rate = validate_rate(annual_rate_pct)
    return (1.0 + rate / 100.0) ** (1.0 / _MONTHS_PER_YEAR) - 1.0
