"""The error boundary: results and exceptions, across JSON, without loss.

A direct call raises ``EmiTooLowError`` and ``chat/formatting.py`` reaches into
it for ``minimum_emi``, ``monthly_interest`` and ``principal`` to compose a
sentence with three correctly-grouped rupee figures in it. Put a process
boundary in the middle and the obvious thing happens: the exception becomes a
string, the chat layer gets ``"An EMI of 3,000.00 does not cover..."`` with the
grouping already wrong, and the structured recovery — land in ``AWAITING_EDIT``
holding every other slot — has nothing left to work with.

So this module moves the *structure*, and the presentation layer never learns
that a boundary exists.

**Results.** Every calculator returns a frozen dataclass of floats, ints and
bools. ``dataclasses.asdict`` and the class name are enough to rebuild it
exactly: ``json`` round-trips a float through its shortest repr, so the
reconstructed ``final_balance`` is the same float, not a near one. A test
asserts equality rather than approximate equality for that reason.

**Errors.** Every ``CalculatorError`` subclass takes ``(message, **structured)``
and stores each structured field as an attribute of the same name. That makes
``vars(exc)`` the exact inverse of the constructor, and reconstruction is
``cls(message, **data)`` for every one of them. The property is load-bearing,
so ``tests/test_mcp.py`` asserts it for every subclass rather than trusting it
— including for subclasses that do not exist yet.

The class is looked up in a registry built by walking ``CalculatorError``'s
subclass tree, which has two consequences worth stating. A new error type is
transportable the moment it is defined, with nothing to remember to register.
And nothing outside that tree can be constructed from wire data, whatever the
payload claims.

Nothing here formats money, and nothing here decides what a user sees. Both are
still ``chat/formatting.py``'s job, working on exactly the objects it worked on
before.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

from calculators import CalculatorError, LoanTenure, SipPlan, SwpProjection


class WireError(Exception):
    """A payload could not be encoded or rebuilt.

    Always a programming error at the seam or a malformed peer, never a
    calculator outcome — those are :class:`CalculatorError` and cross intact.
    """


# Result types are enumerated: there are three, they are the three the registry
# dispatches to, and a fourth appearing without a line here should fail rather
# than be guessed at.
RESULT_TYPES: dict[str, type] = {
    cls.__name__: cls for cls in (LoanTenure, SipPlan, SwpProjection)
}


def _subclass_tree(root: type) -> list[type]:
    """``root`` and every class beneath it, depth first."""
    found = [root]
    for child in root.__subclasses__():
        found.extend(_subclass_tree(child))
    return found


def error_types() -> dict[str, type]:
    """Name to class for every error a calculator can raise.

    Computed on each call rather than cached at import: a subclass defined
    after this module loads is still transportable, and the registry cannot
    silently fall behind ``calculators/errors.py``.
    """
    return {cls.__name__: cls for cls in _subclass_tree(CalculatorError)}


def _json_safe(payload: dict, what: str) -> dict:
    """Refuse to put anything on the wire that will not come back the same.

    ``allow_nan`` is off because ``NaN`` and ``Infinity`` are not JSON, and a
    peer that accepted them would be reconstructing a number the calculators
    guarantee they never produce.
    """
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as unserialisable:
        raise WireError(
            f"{what} carries a value JSON cannot represent: {unserialisable}"
        ) from unserialisable
    return payload


def encode_result(result: object) -> dict:
    """A calculator's return value as a JSON object."""
    if not is_dataclass(result) or type(result).__name__ not in RESULT_TYPES:
        raise WireError(f"not a calculator result: {type(result).__name__}")

    return _json_safe(
        {"type": type(result).__name__, "fields": asdict(result)},
        f"{type(result).__name__} result",
    )


def decode_result(payload: object) -> object:
    """Rebuild the dataclass ``encode_result`` was given. Identical, not similar."""
    if not isinstance(payload, dict):
        raise WireError(f"result payload is not an object: {payload!r}")

    cls = RESULT_TYPES.get(payload.get("type"))
    if cls is None:
        raise WireError(f"unknown result type: {payload.get('type')!r}")

    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise WireError(f"result payload has no fields object: {payload!r}")

    try:
        return cls(**fields)
    except TypeError as mismatch:
        raise WireError(f"{cls.__name__} cannot be rebuilt: {mismatch}") from mismatch


def encode_error(error: CalculatorError) -> dict:
    """A calculator exception as a JSON object, structure intact.

    ``vars(error)`` is every field the constructor was given, because that is
    what those constructors do with them. ``message`` is kept separately since
    it is the one argument that is positional.
    """
    if not isinstance(error, CalculatorError):
        raise WireError(f"not a calculator error: {type(error).__name__}")

    return _json_safe(
        {
            "type": type(error).__name__,
            "message": str(error),
            "data": dict(vars(error)),
        },
        f"{type(error).__name__}",
    )


def decode_error(payload: object) -> CalculatorError:
    """Rebuild the exception, as the class it was, with every attribute back.

    Returns rather than raises, so the caller decides where in its own control
    flow the exception belongs.
    """
    if not isinstance(payload, dict):
        raise WireError(f"error payload is not an object: {payload!r}")

    cls = error_types().get(payload.get("type"))
    if cls is None:
        # Refusing here is the whole point: only classes under CalculatorError
        # can arrive this way, whatever a peer puts in the field.
        raise WireError(f"unknown error type: {payload.get('type')!r}")

    message = payload.get("message")
    if not isinstance(message, str):
        raise WireError(f"error payload has no message: {payload!r}")

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise WireError(f"error payload has a non-object data field: {payload!r}")

    try:
        return cls(message, **data)
    except TypeError as mismatch:
        raise WireError(f"{cls.__name__} cannot be rebuilt: {mismatch}") from mismatch
