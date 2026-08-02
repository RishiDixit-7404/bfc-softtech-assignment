"""Every call the conversation makes to a language model.

Three calls, three narrow jobs:

:func:`classify`      what kind of message is this
:func:`extract_spans` which literal fragments of it look like slot values
:func:`answer`        prose for a finance question

The model never returns a number this layer trusts. Extraction returns the
*characters the user typed*; ``chat/formatting.py`` decides what they mean, and
a span that is not a verbatim fragment of the message is dropped as invented.
That is the difference between a model reading a message and a model writing
one.

Keeping all three here means ``chat/session.py`` holds state logic and nothing
else, and that the whole state machine can be driven by a stub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from calculators import CALCULATORS, CalculatorSpec

from . import prompts
from .formatting import strip_questions
from .llm import LLM, LLMError


class Intent(Enum):
    """What the user's message is for."""

    CALCULATION = "calculation"
    FINANCE_QA = "finance_qa"
    OFF_TOPIC = "off_topic"


@dataclass(frozen=True)
class Route:
    """A classified message. ``calculator_id`` is set only for CALCULATION."""

    intent: Intent
    calculator_id: str | None = None


# Labels the model may reply with. The calculator labels are derived from the
# registry so a new calculator cannot be routable but unadvertised, or the
# reverse.
_CALCULATOR_LABELS = {key.upper(): key for key in CALCULATORS}
_LABELS = tuple(_CALCULATOR_LABELS) + ("FINANCE_QA", "OFF_TOPIC")


def classify(llm: LLM, message: str) -> Route:
    """Route a message to a calculator, a finance answer, or a refusal.

    An unrecognisable reply falls back to ``FINANCE_QA``: this is a finance
    bot, and answering a question that should have been declined is a smaller
    failure than declining one that should have been answered.

    Raises:
        LLMError: the provider failed. The caller decides what to say; state
            is never discarded because of it.
    """
    reply = llm.generate(
        system=prompts.CLASSIFY_SYSTEM,
        user=prompts.CLASSIFY_USER_TEMPLATE.format(message=message),
        task="classify",
    )

    label = _first_label(reply)
    if label in _CALCULATOR_LABELS:
        return Route(Intent.CALCULATION, _CALCULATOR_LABELS[label])
    if label == "OFF_TOPIC":
        return Route(Intent.OFF_TOPIC)
    return Route(Intent.FINANCE_QA)


def _first_label(reply: str) -> str:
    """The earliest known label appearing in the reply, as a whole word."""
    text = reply.upper()
    hits = [
        (match.start(), label)
        for label in _LABELS
        for match in [re.search(rf"\b{label}\b", text)]
        if match is not None
    ]
    return min(hits)[1] if hits else "FINANCE_QA"


def extract_spans(
    llm: LLM,
    spec: CalculatorSpec,
    message: str,
    known: tuple[str, ...] = (),
    pending: str | None = None,
) -> dict[str, str]:
    """Pull the literal spans that look like values for ``spec``'s slots.

    Args:
        llm: The model.
        spec: The calculator in flight, whose parameters name the slots.
        message: The user's message, verbatim.
        known: Slots already filled, so the model can be told what a value in
            this message would be *correcting*.
        pending: The slot the user was just asked for. Naming it makes a bare
            answer far less likely to be filed under the wrong slot — though
            the caller does not rely on that, and overrides it outright when
            the message is nothing but a value.

    Returns:
        Slot name to the exact text the user wrote. Slots the model invented,
        renamed, or paraphrased are dropped - a dropped span is re-asked,
        which is recoverable, while a fabricated one is not.

    Never raises: a model that is down or babbling yields no spans, and the
    caller falls back to reading the message as the pending slot.
    """
    slot_lines = "\n".join(
        f"- {parameter.name}: {parameter.label} "
        f"({prompts.KIND_DESCRIPTIONS[parameter.kind]})"
        for parameter in spec.parameters
    )
    known_line = f"Already collected: {', '.join(known)}\n\n" if known else ""
    pending_line = f"The user was just asked for: {pending}\n\n" if pending else ""

    try:
        reply = llm.generate(
            system=prompts.EXTRACT_SYSTEM,
            user=prompts.EXTRACT_USER_TEMPLATE.format(
                title=spec.title,
                slots=slot_lines,
                known=known_line,
                pending=pending_line,
                message=message,
            ),
            task="extract",
        )
    except LLMError:
        return {}

    valid_slots = {parameter.name for parameter in spec.parameters}
    spans = {}
    for slot, span in _json_object(reply).items():
        if slot in valid_slots and isinstance(span, str) and _is_verbatim(span, message):
            spans[slot] = span.strip()
    return spans


def answer(llm: LLM, message: str) -> str:
    """Answer a finance question in prose, with any question of its own removed.

    Raises:
        LLMError: the provider failed.
    """
    reply = llm.generate(
        system=prompts.ANSWER_SYSTEM,
        user=prompts.ANSWER_USER_TEMPLATE.format(message=message),
        task="answer",
    )
    return strip_questions(reply).strip() or prompts.NO_ANSWER


def _json_object(reply: str) -> dict:
    """Read the JSON object out of a model reply, tolerating fences and prose."""
    text = reply.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _squash(text: str) -> str:
    """Lower-case and drop the characters a model is likely to normalise away."""
    return re.sub(r"[\s,₹]", "", text.lower())


def _is_verbatim(span: str, message: str) -> bool:
    """True when the span really is a fragment of what the user typed."""
    squashed = _squash(span)
    return bool(squashed) and squashed in _squash(message)
