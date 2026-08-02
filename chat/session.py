"""The slot-filling state machine.

Five states, and the interesting design is in what does *not* move between
them:

``IDLE``               nothing in flight
``COLLECTING``         a calculator is chosen; ``pending_slot`` names the one
                       value being asked for right now
``CONFIRMING``         every slot is filled and echoed; waiting for a yes or no
``AWAITING_EDIT``      the user said no, or the scenario turned out to be
                       infeasible; waiting to hear which value to change
``CONFIRMING_SWITCH``  a different calculator was named mid-flow; waiting for a
                       yes or no before anything is discarded

Four rules hold the whole thing together.

**A digression is not a transition.** When the user asks what an EMI is in the
middle of collecting one, the answer is composed and the pending question is
re-posed. ``state``, ``slots`` and ``pending_slot`` are not touched. The
digression is a message the session answers, not a place the session goes.

**Nothing is discarded without a yes.** The one exception to the paragraph
above is a mid-flow message the classifier reads as a *different* calculator.
That is a genuine request often enough to honour, and a misread digression
often enough - "by the way, what is a SIP" - that honouring it silently would
throw a half-filled form away on the strength of one classification. So it is
offered rather than taken: the session moves to ``CONFIRMING_SWITCH``, keeps
every slot and the outstanding question, and declining puts it back exactly
where it was. ``_begin`` is the only method that clears ``slots``, and after
start-up the only way to reach it is a yes.

**Every inbound message goes through extraction, in every state.** A correction
is therefore not a special case with its own branch - it is an extraction that
happens to overwrite a slot that already had a value. Nothing about "actually
make it 8%" resets ``state`` or clears ``slots``, because no code path exists
that could.

**One question per message.** Enforced structurally: questions come from
``chat/prompts.py``, every message is assembled by ``formatting.compose``, and
``compose`` refuses anything but exactly one question mark.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from calculators import (
    CALCULATORS,
    CalculatorError,
    CalculatorSpec,
    InfeasibleScenarioError,
    Parameter,
    ValidationError,
    resolve_withdrawal,
)
from calculators.validation import validate_amount, validate_rate, validate_years

from . import prompts
from .formatting import (
    compose,
    format_rate,
    format_slot_value,
    parse_money,
    parse_rate,
    parse_withdrawal,
    parse_years,
    parse_yes_no,
    render_confirmation,
    render_error,
    render_loan,
    render_sip,
    render_swp,
)
from .llm import (
    LLM,
    LLMError,
    LLMMisconfiguredError,
    LLMQuotaError,
    LLMResponseError,
    LLMTimeoutError,
)
from .router import Intent, answer, classify, extract_spans


class State(Enum):
    """Where the conversation is. See the module docstring."""

    IDLE = "idle"
    COLLECTING = "collecting"
    CONFIRMING = "confirming"
    AWAITING_EDIT = "awaiting_edit"
    CONFIRMING_SWITCH = "confirming_switch"


def _failure_copy(failure: LLMError) -> str:
    """Which sentence a provider failure earns.

    Five causes, five messages, because the right next move differs in each:
    "took too long" invites a retry, "allowance used up" says wait until
    tomorrow, and "no model configured" says stop trying and fix the setup.
    Collapsing them would send someone in the wrong direction. The exception
    itself never reaches them.
    """
    if isinstance(failure, LLMQuotaError):
        return prompts.LLM_QUOTA
    if isinstance(failure, LLMTimeoutError):
        return prompts.LLM_TIMEOUT
    if isinstance(failure, LLMResponseError):
        return prompts.LLM_MALFORMED
    if isinstance(failure, LLMMisconfiguredError):
        return prompts.LLM_MISCONFIGURED
    return prompts.LLM_UNAVAILABLE


class _Rejected(Exception):
    """A span could not be read as a value. Carries what to tell the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class _PendingSwitch:
    """A calculator change that has been offered and not yet answered.

    ``resume_state`` is where the session goes back to on a no, which is why
    declining costs nothing: the offer never moved anything but ``state``.
    """

    calculator_id: str
    text: str
    resume_state: State


@dataclass
class Session:
    """One conversation. Cheap to construct, holds no I/O of its own."""

    llm: LLM
    state: State = State.IDLE
    calculator_id: str | None = None
    slots: dict[str, float] = field(default_factory=dict)
    pending_slot: str | None = None
    withdrawal_percent: float | None = None
    pending_switch: _PendingSwitch | None = None

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def greeting(self) -> str:
        """The opening message, built from the registry so it cannot drift."""
        lines = [prompts.GREETING_INTRO]
        for spec in CALCULATORS.values():
            blurb = prompts.GREETING_BLURBS.get(spec.id)
            lines.append(f"- {spec.title}" + (f" - {blurb}" if blurb else ""))
        return compose("\n".join(lines), prompts.GREETING_QUESTION)

    def handle(self, message: str) -> str:
        """Take one user message and return the bot's reply.

        A provider failure is reported and the turn ends; the conversation
        keeps every value it had, because losing a half-filled form to a
        network blip is not an acceptable way to fail.
        """
        text = (message or "").strip()
        if not text:
            return self.greeting() if self.state is State.IDLE else self._resume()

        try:
            return self._turn(text)
        except LLMError as failure:
            copy = _failure_copy(failure)
            return copy if self.state is State.IDLE else self._resume(copy)

    # ------------------------------------------------------------------
    # Turn handling
    # ------------------------------------------------------------------

    def _turn(self, text: str) -> str:
        if self.state is State.IDLE:
            return self._turn_idle(text)
        return self._turn_in_flow(text)

    def _turn_idle(self, text: str) -> str:
        route = classify(self.llm, text)

        if route.intent is Intent.CALCULATION and route.calculator_id:
            return self._begin(route.calculator_id, text)
        if route.intent is Intent.FINANCE_QA:
            return answer(self.llm, text)
        return prompts.DECLINE

    def _turn_in_flow(self, text: str) -> str:
        # Extraction runs first and runs always. A correction is just an
        # extraction that overwrites a slot, which is why no branch below can
        # reset the flow.
        updates, rejections = self._absorb(text)
        if updates or rejections:
            return self._advance(self._acknowledge(updates, rejections))

        if self.state is State.CONFIRMING:
            verdict = parse_yes_no(text)
            if verdict is True:
                return self._compute()
            if verdict is False:
                return self._request_edit(prompts.EDIT_INTRO)

        if self.state is State.CONFIRMING_SWITCH and self.pending_switch is not None:
            verdict = parse_yes_no(text)
            if verdict is True:
                return self._take_switch()
            if verdict is False:
                return self._decline_switch()

        if self.state is State.AWAITING_EDIT:
            slot = self._match_slot(text)
            if slot is not None:
                self.state = State.COLLECTING
                self.pending_slot = slot
                return compose("", self._slot_question(slot))

        return self._digress(text)

    def _digress(self, text: str) -> str:
        """Handle a message that carries no values, without moving state."""
        route = classify(self.llm, text)

        if route.intent is Intent.CALCULATION:
            if route.calculator_id and route.calculator_id != self.calculator_id:
                return self._offer_switch(route.calculator_id, text)
            return self._resume()

        if route.intent is Intent.OFF_TOPIC:
            return self._resume(prompts.DECLINE_INLINE)
        return self._resume(answer(self.llm, text))

    # ------------------------------------------------------------------
    # Changing calculator mid-flow
    # ------------------------------------------------------------------

    def _offer_switch(self, calculator_id: str, text: str) -> str:
        """Offer a different calculator. Discards nothing until it is accepted.

        Starting it outright would throw away every collected value on the
        strength of one classification, and "by the way, what is a SIP"
        classifies as SIP often enough for that to be a real loss. Only
        ``state`` moves; ``slots`` and ``pending_slot`` stay exactly as they
        are, so a no costs the user nothing but the turn.

        The triggering message is kept so that any values it carried - "let's
        do a SIP for 10 lakh instead" - are still filled if the switch happens.
        """
        resume_state = (
            self.pending_switch.resume_state
            if self.pending_switch is not None
            else self.state
        )
        self.pending_switch = _PendingSwitch(calculator_id, text, resume_state)
        self.state = State.CONFIRMING_SWITCH

        return compose(
            prompts.switch_offer(self._spec.title), self._switch_question()
        )

    def _take_switch(self) -> str:
        """The user said yes. This is the only in-flow path that clears slots."""
        switch = self.pending_switch
        assert switch is not None  # guarded by the caller
        previous = self._spec.title

        return self._begin(
            switch.calculator_id,
            switch.text,
            prompts.switch_confirmed(
                CALCULATORS[switch.calculator_id].title, previous
            ),
        )

    def _decline_switch(self) -> str:
        """The user said no. Put the state back and re-pose the same question."""
        switch = self.pending_switch
        assert switch is not None  # guarded by the caller
        title = self._spec.title

        self.pending_switch = None
        self.state = switch.resume_state
        return self._resume(prompts.switch_declined(title))

    def _begin(self, calculator_id: str, text: str, prose: str = "") -> str:
        """Start a calculator and fill whatever the same message already gave."""
        self.calculator_id = calculator_id
        self.state = State.COLLECTING
        self.slots = {}
        self.pending_slot = None
        self.withdrawal_percent = None
        self.pending_switch = None

        updates, rejections = self._absorb(text)
        acknowledgement = self._acknowledge(updates, rejections)
        return self._advance(" ".join(part for part in (prose, acknowledgement) if part))

    # ------------------------------------------------------------------
    # Slot filling
    # ------------------------------------------------------------------

    def _absorb(self, text: str) -> tuple[dict[str, tuple[float | None, float]], list[str]]:
        """Read every value this message carries into the slots.

        Returns:
            ``(updates, rejections)`` where ``updates`` maps slot name to
            ``(previous, new)`` - previous is ``None`` for a first fill and a
            number for a correction - and ``rejections`` are messages about
            spans that could not be used.
        """
        spec = self._spec
        spans = extract_spans(
            self.llm, spec, text, tuple(self.slots), self.pending_slot
        )

        guessing = False
        if self.pending_slot is not None and self._is_bare_value(text):
            # The message is nothing but a value, and we know which question
            # it answers: the one just asked. Observed against a live model
            # filing "10,000" under `principal` while the pending slot was
            # `emi` — which silently overwrote the loan amount and left the
            # EMI empty. D12 refuses the model's numbers; a slot assignment
            # is no more trustworthy, and here Python knows better.
            spans = {self.pending_slot: text}
        elif not spans and self.pending_slot is not None:
            # Nothing extracted, but a question is outstanding: the message may
            # still be the answer. Read it as one, and if it does not parse say
            # nothing - it is then handled as whatever it actually was.
            spans = {self.pending_slot: text}
            guessing = True

        updates: dict[str, tuple[float | None, float]] = {}
        rejections: list[str] = []

        for parameter in spec.parameters:
            span = spans.get(parameter.name)
            if span is None:
                continue
            try:
                self._fill(parameter, span, updates)
            except _Rejected as rejected:
                if not guessing:
                    rejections.append(rejected.message)

        self._reresolve_percent(updates)
        return updates, rejections

    def _fill(
        self,
        parameter: Parameter,
        span: str,
        updates: dict[str, tuple[float | None, float]],
    ) -> None:
        """Parse, validate and store one span.

        Validation reuses ``calculators.validation`` rather than restating the
        rules, so a slot can never accept a value the calculator would refuse.

        Raises:
            _Rejected: the span is not a number of the right shape, or is a
                number the calculator's own guards turn down.
        """
        try:
            value = self._read(parameter, span)
        except ValidationError as invalid:
            raise _Rejected(render_error(invalid)) from invalid

        if value is None:
            return  # A percentage banked until the lumpsum is known.

        previous = self.slots.get(parameter.name)
        if previous == value:
            return

        self.slots[parameter.name] = value
        updates[parameter.name] = (previous, value)

    @staticmethod
    def _parse_for(parameter: Parameter, span: str) -> object | None:
        """Parse a span according to a parameter's kind. No validation here."""
        if parameter.kind == "rate":
            return parse_rate(span)
        if parameter.kind == "years":
            return parse_years(span)
        if parameter.kind == "money_or_percent":
            return parse_withdrawal(span)
        return parse_money(span)

    def _is_bare_value(self, text: str) -> bool:
        """True when the whole message is just a value for the pending slot.

        "10,000" is; "make the loan 10,000" is not, and neither is "actually
        make it 9%" while an EMI is pending - those carry a slot of their own
        and are left to the extractor.
        """
        parameter = self._parameter(self.pending_slot)
        return parameter is not None and self._parse_for(parameter, text) is not None

    def _read(self, parameter: Parameter, span: str) -> float | None:
        """Turn one span into a validated value for ``parameter``.

        Returns ``None`` only for a withdrawal given as a percentage before
        the lumpsum is known: the percentage is remembered and resolved as
        soon as there is a lumpsum to apply it to.
        """
        parsed = self._parse_for(parameter, span)
        if parsed is None:
            raise _Rejected(self._unreadable(parameter, span))

        if parameter.kind == "rate":
            return validate_rate(parsed, parameter.label)
        if parameter.kind == "years":
            return validate_years(parsed, parameter.label)
        if parameter.kind == "money_or_percent":
            return self._read_withdrawal(parameter, parsed)
        return validate_amount(parsed, parameter.label)

    def _read_withdrawal(self, parameter: Parameter, reading: tuple) -> float | None:
        """Accept an SWP withdrawal as rupees or as a percent of the lumpsum.

        The percentage is resolved through ``calculators.resolve_withdrawal``
        so both input forms converge on one computation, and the resolved
        rupee figure is echoed at confirmation - a user who meant "0.8% a
        year" catches it before the result rather than after.
        """
        form, number = reading
        if form == "money":
            self.withdrawal_percent = None
            return validate_amount(number, parameter.label, allow_zero=True)

        validate_rate(number, "withdrawal percentage")
        self.withdrawal_percent = number
        lumpsum = self.slots.get("lumpsum")
        if lumpsum is None:
            return None
        return resolve_withdrawal(lumpsum, percent=number)

    def _reresolve_percent(
        self, updates: dict[str, tuple[float | None, float]]
    ) -> None:
        """Keep a percentage-based withdrawal true to the current lumpsum.

        Covers both the percentage given before the lumpsum and the lumpsum
        corrected after the percentage.
        """
        if self.withdrawal_percent is None or "lumpsum" not in self.slots:
            return

        resolved = resolve_withdrawal(
            self.slots["lumpsum"], percent=self.withdrawal_percent
        )
        previous = self.slots.get("monthly_withdrawal")
        if previous == resolved:
            return

        self.slots["monthly_withdrawal"] = resolved
        updates["monthly_withdrawal"] = (previous, resolved)

    def _unreadable(self, parameter: Parameter, span: str) -> str:
        return prompts.REJECTED_SPAN.format(label=parameter.label, span=span.strip())

    # ------------------------------------------------------------------
    # Asking, confirming, computing
    # ------------------------------------------------------------------

    def _advance(self, prefix: str = "") -> str:
        """Ask for the next missing slot, or confirm if none are missing.

        Any offered switch lapses here: a value landing in the calculator in
        flight is the user carrying on with it.
        """
        self.pending_switch = None
        missing = [
            parameter.name
            for parameter in self._spec.parameters
            if parameter.name not in self.slots
        ]
        if missing:
            self.state = State.COLLECTING
            self.pending_slot = missing[0]
            return compose(prefix, self._slot_question(missing[0]))

        self.state = State.CONFIRMING
        self.pending_slot = None
        return compose(prefix, self._confirmation())

    def _confirmation(self) -> str:
        return render_confirmation(self._spec, self.slots, self._notes())

    def _notes(self) -> dict[str, str]:
        """Annotations shown beside a value, so a derived figure is not silent."""
        if self.withdrawal_percent is None:
            return {}
        return {
            "monthly_withdrawal": (
                f"{format_rate(self.withdrawal_percent)} of the lumpsum"
            )
        }

    def _request_edit(self, prose: str) -> str:
        """Hold every value and ask which one to change."""
        self.state = State.AWAITING_EDIT
        self.pending_slot = None
        self.pending_switch = None
        return compose(prose, self._edit_question())

    def _compute(self) -> str:
        """Run the calculator and present the result, or the reason there is none."""
        spec = self._spec
        try:
            result = spec.function(**self.slots)
        except InfeasibleScenarioError as infeasible:
            # Every input was individually legal, so nothing is thrown away:
            # the user picks one value to revise and the rest stand.
            return self._request_edit(render_error(infeasible))
        except ValidationError as invalid:
            return self._reask_invalid(invalid)
        except CalculatorError as unexpected:  # pragma: no cover - defensive
            return self._request_edit(render_error(unexpected))

        body = self._render(result)
        self._reset()
        return compose(body, prompts.ANYTHING_ELSE)

    def _reask_invalid(self, invalid: ValidationError) -> str:
        """A value only the calculator could reject - drop it and ask again.

        Reached for rules that need more than one slot to check, such as a
        withdrawal larger than the lumpsum.
        """
        slot = self._slot_for_label(invalid.field)
        if slot is None:
            return self._request_edit(render_error(invalid))

        self.slots.pop(slot, None)
        if slot == "monthly_withdrawal":
            self.withdrawal_percent = None
        self.state = State.COLLECTING
        self.pending_slot = slot
        return compose(render_error(invalid), self._slot_question(slot))

    def _render(self, result: object) -> str:
        """Hand the result to its renderer. No arithmetic happens on the way."""
        if self.calculator_id == "loan_tenure":
            return render_loan(result)
        if self.calculator_id == "sip":
            return render_sip(
                result,
                self.slots["target"],
                self.slots["years"],
                self.slots["annual_rate_pct"],
            )
        return render_swp(
            result, self.slots["lumpsum"], self.slots["monthly_withdrawal"]
        )

    def _reset(self) -> None:
        self.state = State.IDLE
        self.calculator_id = None
        self.slots = {}
        self.pending_slot = None
        self.withdrawal_percent = None
        self.pending_switch = None

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def _resume(self, prose: str = "") -> str:
        """Re-pose the outstanding question. Changes nothing about the state."""
        if self.state is State.IDLE:
            return compose(prose, prompts.GREETING_QUESTION)
        return compose(prose, self._pending_question())

    def _pending_question(self) -> str:
        if self.state is State.AWAITING_EDIT:
            return self._edit_question()
        if self.state is State.CONFIRMING:
            return self._confirmation()
        if self.state is State.CONFIRMING_SWITCH:
            return self._switch_question()

        if self.pending_slot is not None:
            return self._slot_question(self.pending_slot)
        missing = [  # pragma: no cover - defensive; _advance always sets one
            parameter.name
            for parameter in self._spec.parameters
            if parameter.name not in self.slots
        ]
        return (
            self._slot_question(missing[0]) if missing else self._confirmation()
        )

    def _slot_question(self, slot: str) -> str:
        return prompts.SLOT_QUESTIONS[(self._spec.id, slot)]

    def _switch_question(self) -> str:
        if self.pending_switch is None:  # pragma: no cover - defensive
            raise RuntimeError("no switch has been offered")
        return prompts.switch_question(
            CALCULATORS[self.pending_switch.calculator_id].title
        )

    def _edit_question(self) -> str:
        return prompts.edit_question(
            tuple(parameter.label for parameter in self._spec.parameters)
        )

    def _acknowledge(
        self,
        updates: dict[str, tuple[float | None, float]],
        rejections: list[str],
    ) -> str:
        """Say what was rejected and what was changed. Never asks anything."""
        parts = list(rejections)
        for parameter in self._spec.parameters:
            change = updates.get(parameter.name)
            if change is None or change[0] is None:
                continue  # A first fill needs no announcement.
            parts.append(
                prompts.UPDATED.format(
                    label=parameter.label,
                    value=format_slot_value(parameter.kind, change[1]),
                )
            )
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    @property
    def _spec(self) -> CalculatorSpec:
        if self.calculator_id is None:  # pragma: no cover - defensive
            raise RuntimeError("no calculator is in flight")
        return CALCULATORS[self.calculator_id]

    def _parameter(self, name: str | None) -> Parameter | None:
        if name is None or self.calculator_id is None:
            return None
        for parameter in self._spec.parameters:
            if parameter.name == name:
                return parameter
        return None

    def _slot_for_label(self, label: str) -> str | None:
        for parameter in self._spec.parameters:
            if parameter.label == label:
                return parameter.name
        return None

    def _match_slot(self, text: str) -> str | None:
        """Which slot the user named. ``None`` if none, or more than one.

        Matching is scoped to the calculator in flight, so a word shared
        across calculators is unambiguous here. A word that fits two slots of
        the *same* calculator is treated as no match - asking again is better
        than editing the wrong value.
        """
        lowered = text.lower()
        matched = {
            parameter.name
            for parameter in self._spec.parameters
            if any(
                re.search(rf"\b{re.escape(word)}\b", lowered)
                for word in (parameter.label.lower(),)
                + prompts.SLOT_ALIASES.get(parameter.name, ())
            )
        }
        return matched.pop() if len(matched) == 1 else None
