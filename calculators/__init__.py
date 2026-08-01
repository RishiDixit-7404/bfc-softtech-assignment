"""Pure financial calculators.

This package imports nothing from ``chat/``, ``app``, or any LLM SDK, and it
never will — the dependency arrow runs one way only. Every formula here can be
read against ``SPEC.md`` without knowing that a chatbot exists.

``CALCULATORS`` is the registry the chat layer routes through. It carries the
function and its parameter metadata (name, kind, units) but no question text:
how to *ask* for a value is a conversation concern and lives in
``chat/prompts.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .errors import (
    CalculatorError,
    EmiTooLowError,
    InfeasibleScenarioError,
    InvalidAmountError,
    InvalidPeriodError,
    InvalidRateError,
    ValidationError,
)
from .loan import LoanTenure, loan_tenure
from .rates import monthly_rate
from .sip import SipPlan, sip_for_target
from .swp import SwpProjection, resolve_withdrawal, swp_projection

__all__ = [
    "CALCULATORS",
    "CalculatorError",
    "CalculatorSpec",
    "EmiTooLowError",
    "InfeasibleScenarioError",
    "InvalidAmountError",
    "InvalidPeriodError",
    "InvalidRateError",
    "LoanTenure",
    "Parameter",
    "SipPlan",
    "SwpProjection",
    "ValidationError",
    "loan_tenure",
    "monthly_rate",
    "resolve_withdrawal",
    "sip_for_target",
    "swp_projection",
]


@dataclass(frozen=True)
class Parameter:
    """One argument a calculator needs.

    ``kind`` tells the chat layer how to parse and echo the value:
    ``money``, ``rate``, ``years``, or ``money_or_percent``.
    """

    name: str
    label: str
    kind: str


@dataclass(frozen=True)
class CalculatorSpec:
    """A calculator plus the parameters it requires, in the order to ask."""

    id: str
    title: str
    function: Callable[..., object]
    parameters: tuple[Parameter, ...]


CALCULATORS: dict[str, CalculatorSpec] = {
    "loan_tenure": CalculatorSpec(
        id="loan_tenure",
        title="Loan tenure",
        function=loan_tenure,
        parameters=(
            Parameter("principal", "loan amount", "money"),
            Parameter("emi", "EMI", "money"),
            Parameter("annual_rate_pct", "annual interest rate", "rate"),
        ),
    ),
    "sip": CalculatorSpec(
        id="sip",
        title="SIP for a target amount",
        function=sip_for_target,
        parameters=(
            Parameter("target", "target amount", "money"),
            Parameter("annual_rate_pct", "expected annual return", "rate"),
            Parameter("years", "investment period", "years"),
        ),
    ),
    "swp": CalculatorSpec(
        id="swp",
        title="SWP (systematic withdrawals)",
        function=swp_projection,
        parameters=(
            Parameter("lumpsum", "lumpsum amount", "money"),
            Parameter("years", "investment period", "years"),
            Parameter("annual_rate_pct", "expected annual return", "rate"),
            Parameter("monthly_withdrawal", "monthly withdrawal", "money_or_percent"),
        ),
    ),
}
