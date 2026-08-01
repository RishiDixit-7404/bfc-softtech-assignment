"""TEST_VECTORS.md section 4 — cross-cutting guard tests.

These assert structural properties of the codebase rather than numbers. They
are what stops a correct implementation from quietly decaying later.
"""

import math
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from calculators import CALCULATORS
from calculators.errors import CalculatorError
from calculators.loan import loan_tenure
from calculators.sip import sip_for_target
from calculators.swp import resolve_withdrawal, swp_projection

ROOT = Path(__file__).resolve().parent.parent
CALCULATORS_DIR = ROOT / "calculators"


def _source_files(directory: Path):
    return sorted(directory.rglob("*.py"))


def _shipped_files():
    """Every .py file that ships, excluding the test suite itself."""
    skip = {"tests", ".git", ".venv", "venv", "__pycache__"}
    return [
        path
        for path in ROOT.rglob("*.py")
        if not skip & set(path.relative_to(ROOT).parts)
    ]


def test_G1_monthly_rate_is_defined_exactly_once():
    """One definition, or the formula drifts between calculators."""
    definitions = [
        path.relative_to(ROOT)
        for path in _shipped_files()
        if re.search(r"^\s*def monthly_rate\b", path.read_text(), re.MULTILINE)
    ]

    assert definitions == [Path("calculators/rates.py")]


@pytest.mark.parametrize("pattern", [r"R/12\b", r"R/1200\b", r"/\s*12\s*\*"])
def test_G2_no_naive_monthly_rate_in_calculators(pattern):
    """The nominal-rate regression, caught at the source level."""
    offenders = [
        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
        for path in _source_files(CALCULATORS_DIR)
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if re.search(pattern, line)
    ]

    assert offenders == []


def test_G3_calculators_never_import_the_layers_above_them():
    """The dependency arrow runs one way: chat -> calculators, never back."""
    forbidden = re.compile(r"^\s*(?:from|import)\s+(chat|app)\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(ROOT))
        for path in _source_files(CALCULATORS_DIR)
        if forbidden.search(path.read_text())
    ]

    assert offenders == []


INVALID_CALLS = [
    (loan_tenure, (0, 10_000, 9.0)),
    (loan_tenure, (500_000, 0, 9.0)),
    (loan_tenure, (500_000, 10_000, 150)),
    (loan_tenure, (500_000, 3_000, 9.0)),
    (loan_tenure, ("five lakh", 10_000, 9.0)),
    (sip_for_target, (0, 12.0, 10)),
    (sip_for_target, (1_000_000, 12.0, 0)),
    (sip_for_target, (1_000_000, -5, 10)),
    (sip_for_target, (1_000_000, 12.0, "ten")),
    (swp_projection, (0, 10, 9.0, 8_000)),
    (swp_projection, (1_000_000, 10, 9.0, 2_000_000)),
    (swp_projection, (1_000_000, 10, 101, 8_000)),
    (swp_projection, (1_000_000, 0, 9.0, 8_000)),
    (swp_projection, (1_000_000, 10, 9.0, None)),
]


@pytest.mark.parametrize("function, args", INVALID_CALLS)
def test_G4_every_failure_is_a_calculator_error(function, args):
    """Uniform error handling upstream: one base class to catch."""
    with pytest.raises(CalculatorError):
        function(*args)


def test_G4_percent_resolution_also_raises_calculator_errors():
    with pytest.raises(CalculatorError):
        resolve_withdrawal(1_000_000, percent=150)


VALID_CALLS = [
    (loan_tenure, (500_000, 10_000, 9.0)),
    (loan_tenure, (1_000_000, 15_000, 8.5)),
    (loan_tenure, (250_000, 5_000, 12.0)),
    (loan_tenure, (500_000, 10_000, 0)),
    (loan_tenure, (250_000, 5_000, 0)),
    (sip_for_target, (1_000_000, 12.0, 10)),
    (sip_for_target, (5_000_000, 10.0, 15)),
    (sip_for_target, (200_000, 8.0, 3)),
    (sip_for_target, (200_000, 0, 3)),
    (sip_for_target, (1_000_000, 0, 10)),
    (swp_projection, (1_000_000, 10, 9.0, 8_000)),
    (swp_projection, (2_000_000, 5, 10.0, 20_000)),
    (swp_projection, (500_000, 10, 8.0, 6_000)),
    (swp_projection, (300_000, 10, 8.0, 6_000)),
    (swp_projection, (1_000_000, 10, 9.0, 0)),
    (swp_projection, (1_000_000, 5, 0, 6_000)),
    (swp_projection, (500_000, 10, 0, 6_000)),
]


@pytest.mark.parametrize("function, args", VALID_CALLS)
def test_G5_no_result_field_is_nan_or_infinite(function, args):
    """Don't crash, don't lie: every reported number is a real number."""
    result = function(*args)
    assert is_dataclass(result)

    for field in fields(result):
        value = getattr(result, field.name)
        if isinstance(value, float):
            assert math.isfinite(value), f"{field.name} is {value}"


def test_registry_parameters_match_the_function_signatures():
    """The chat layer fills slots by name; a rename here must not go unseen."""
    import inspect

    for spec in CALCULATORS.values():
        signature = inspect.signature(spec.function)
        assert [p.name for p in spec.parameters] == list(signature.parameters)
