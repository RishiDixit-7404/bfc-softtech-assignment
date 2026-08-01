"""Exception hierarchy for the calculator layer.

Two branches, deliberately:

``ValidationError``
    The input itself is impossible — a negative amount, a rate outside 0-100.
    Upstream recovery is to re-ask that one field.

``InfeasibleScenarioError``
    Every input is individually legal, but the scenario has no solution.
    Upstream recovery is to explain why and ask which value to revise.

Errors carry structured attributes rather than rendered strings. ``str(exc)``
is a plain-number fallback for logs; the chat layer reads the attributes and
formats currency at the presentation boundary.
"""

from __future__ import annotations


class CalculatorError(Exception):
    """Base for every error this package raises. Upstream catches only this."""


class ValidationError(CalculatorError):
    """An input value is outside the domain the calculator accepts."""

    def __init__(self, message: str, *, field: str, value: object) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


class InvalidAmountError(ValidationError):
    """A money amount is missing, non-numeric, or outside its allowed range."""

    def __init__(
        self,
        message: str,
        *,
        field: str,
        value: object,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> None:
        super().__init__(message, field=field, value=value)
        self.minimum = minimum
        self.maximum = maximum


class InvalidRateError(ValidationError):
    """A percentage is non-numeric or outside 0-100 inclusive."""

    def __init__(
        self,
        message: str,
        *,
        field: str,
        value: object,
        min_rate: float = 0.0,
        max_rate: float = 100.0,
    ) -> None:
        super().__init__(message, field=field, value=value)
        self.min_rate = min_rate
        self.max_rate = max_rate


class InvalidPeriodError(ValidationError):
    """A period in years is non-numeric or outside 0 < years <= 100."""

    def __init__(
        self,
        message: str,
        *,
        field: str,
        value: object,
        min_years: float = 0.0,
        max_years: float = 100.0,
    ) -> None:
        super().__init__(message, field=field, value=value)
        self.min_years = min_years
        self.max_years = max_years


class InfeasibleScenarioError(CalculatorError):
    """Inputs are valid, but no answer exists for the scenario they describe."""


class EmiTooLowError(InfeasibleScenarioError):
    """EMI does not exceed the monthly interest, so the loan is never repaid.

    ``minimum_emi`` is ``P * r`` at full precision. The presentation layer
    rounds it *up* before showing it: an EMI equal to the interest is still
    too low, so rounding down would print an unpayable target.
    """

    def __init__(
        self,
        message: str,
        *,
        principal: float,
        emi: float,
        monthly_interest: float,
        minimum_emi: float,
    ) -> None:
        super().__init__(message)
        self.principal = principal
        self.emi = emi
        self.monthly_interest = monthly_interest
        self.minimum_emi = minimum_emi
