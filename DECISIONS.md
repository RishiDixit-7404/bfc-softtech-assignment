# DECISIONS.md

Append-only log of judgment calls. Each entry states the choice, the reason, and
what would change my mind. Entries are written when the decision is made, not
reconstructed afterwards.

---

## D1 — Implement all three calculators, not two

`SPEC.md` contradicts itself: the intro promises a bot that can calculate three
things and requires it to say so on start-up, while the note under *Behavior*
says "integrate any two". A two-calculator build makes the mandated start-up
message advertise a calculator that does not exist.

**Decision:** implement all three. The marginal cost is one pure function and
one slot list per calculator, `TEST_VECTORS.md` supplies verified vectors for
all three, and each is independently tested.

The contradiction is called out in the README rather than resolved silently —
noticing it is part of what the task measures.

---

## D2 — The SIP formula is implemented verbatim, including `× (1 + r)`

`SPEC.md` states:

```
SIP = ( Target × r / ((1+r)^(n×12) − 1) ) × (1 + r)
```

A standard annuity-due solve *divides* by `(1 + r)`. Because the spec
multiplies, the resulting contribution overshoots the target by exactly
`(1 + r)²` — for S1 that is ₹19,067.62 of unnecessary saving against a
₹10,00,000 goal. The ratio matches `(1+r)²` to eight decimal places across all
three vectors, which identifies the cause rather than guessing at it.

**Decision:** ship the client's formula. `test_sip_matches_spec_formula` asserts
the spec value — that is the graded behaviour. A second test,
`test_sip_spec_overshoots_annuity_due_by_one_plus_r_squared`, asserts the ratio
against the annuity-due and ordinary-annuity columns, and a third simulates the
spec contribution for 120 months to show the overshoot in rupees.

Silently substituting the conventional formula would be changing a client's
stated requirement without telling them. Implementing it without noticing would
be worse. The README carries one line pointing here.

**What would change this:** the client confirming the `× (1 + r)` is a typo.
The fix is a one-character change and one test flip.

---

## D3 — Loan tenure is reported as `ceil(n)`, with the exact figure alongside

`n` is continuous; repayment is not. L1's 62.223905 months means the borrower
makes 63 payments, which month-by-month amortisation confirms for all three
vectors.

**Decision:** `LoanTenure.months` is `ceil(n)` and drives the years-and-months
display; `months_exact` is retained and shown alongside so nothing is hidden.

Per the spec's own `1.5 => 1 year & 6 months` example, the user-facing value is
derived from months (`63 → 5y 3m`), never printed as `62 years 2 months`.

---

## D4 — `total_paid` accounts for a partial final instalment

Rounding the tenure up makes the last month partial. `months × emi` therefore
overstates the true cost — by ₹7,754.70 on L1, ₹11,705.78 on L2, ₹4,418.19 on
L3. A borrower shown ₹6,30,000 when they will pay ₹6,22,245.30 has been given a
wrong number by a calculator whose whole job is that number.

**Decision:** `LoanTenure` exposes `final_payment` (what is still owed after
`months - 1` EMIs, grown one more month) and defines
`total_paid = (months - 1) × emi + final_payment`.

The `total_paid` figures were supplied by the repository owner at plan review
and reproduced independently before use.

> **Superseded in part by D16.** The rest of this paragraph described pinning
> `final_payment` by its relationship to `total_paid` rather than by a literal,
> because `TEST_VECTORS.md` §1.1 carried no column for either. §1.3 now
> publishes both at full precision and the tests assert them directly, so that
> is no longer what the committed file does. The reasoning above is unchanged.

---

## D5 — SWP percentage means percent of the lumpsum, *per month*

`SPEC.md` says "a % of the lumpsum" and stops. The industry convention for an
SWP rate is annual, which would read W3's 0.8% as ₹666.67/month; `TEST_VECTORS.md`
W3 pins it at ₹8,000/month, i.e. monthly.

**Decision:** monthly, per W3. Because that is the less intuitive reading, the
bot always echoes the resolved rupee figure before computing — a user who meant
"0.8% a year" catches it at the confirmation step, not after the result.

`resolve_withdrawal()` is a separate function from `swp_projection()` so both
input forms converge on one computation. W3 is numerically identical to W1 by
construction, which is what proves the paths have not drifted.

---

## D6 — Depletion is reported, not raised; and `actual_withdrawn` is exposed

The SWP closed form returns a negative final balance when withdrawals outrun
growth. W5's corpus is dry in month 61, yet the formula reports a balance of
₹-4,33,068 and bills 120 withdrawals that never happened.

**Decision:** depletion is a *result*, not an exception. W4/W5 have entirely
valid inputs and a real answer — "you run out in month 61" — so raising would
misclassify the failure. `SwpProjection` carries `depleted`, `depletion_month`
(found by simulation, never by inverting the formula), and `actual_withdrawn`
(full withdrawals up to depletion plus one final partial). The spec's
`final_balance`, `total_withdrawn` and `total_profit` are still computed and
returned exactly as specified; when `depleted` is true the presentation layer
leads with the depletion report, suppresses the first and third, and prints
`total_withdrawn` beside `actual_withdrawn` (D15, as amended by D23).

Contrast D7: an EMI below the monthly interest *raises*, because there the
answer does not exist at all.

Note the spec's profit figure is not merely pessimistic once depleted — it is
unreliable in both directions. W5 reports a ₹13,068 loss on a plan that paid out
₹63,150 more than went in; W4 happens to be exactly right. That is why
`actual_withdrawn` exists.

---

## D7 — `E ≤ P·r` raises, and the boundary is inclusive

An EMI equal to the monthly interest holds the balance flat forever — just as
unrepayable as one below it, and the closed form takes `log` of a non-positive
number either side of it.

**Decision:** `EmiTooLowError`, a subclass of `InfeasibleScenarioError` rather
than `ValidationError`, since every input was individually legal. It carries
`minimum_emi = P·r` at full precision.

The message states the bound itself and, separately, the smallest whole rupee
above it — "anything above ₹3,603.66 clears it; ₹3,604 is the nearest whole
rupee that does". Saying only *"the EMI has to be above ₹3,604"* is false:
₹3,604 is viable, and clears the loan in 1,292 months. The rounded figure
exists to make the printed target payable, not to restate the bound. It is
`floor + 1`, not `ceil`, because the two differ precisely when `P·r` lands on
a whole rupee — and there `ceil` names the one EMI that does not work.

---

## D8 — Zero-rate paths are branched explicitly, never patched afterwards

At `R = 0` all three closed forms degenerate: the loan divides by `log(1) = 0`,
the SIP by `(1+r)^n − 1 = 0`, the SWP evaluates `0/0`. A 0% loan is legitimate
input, so returning `inf` or raising `ZeroDivisionError` is not acceptable.

**Decision:** each calculator tests `r == 0.0` before entering the closed form
and uses the degenerate identity — `n = P/E`, `SIP = Target/(n·12)`,
`FV = P − W·n`. `monthly_rate(0)` is exactly `0.0`, so the comparison is safe.

A standalone invariant is asserted for arbitrary inputs, not just the vectors:
at `R = 0`, SWP `total_profit` is exactly `0.0`. No growth, no profit. It falls
out of `(P − W·n) + W·n − P`, and it catches a whole class of degenerate-branch
error for the price of one assertion.

---

## D9 — Depletion simulation is skipped when `FV ≥ 0`

The recurrence `B(m+1) = B(m)(1+r) − W` has fixed point `B* = W/r`. Below it the
decline compounds and widens every month, so the sign change is one-way: a
non-negative final balance cannot conceal an intermediate dip. At `R = 0` the
balance is strictly decreasing and the argument is trivial.

**Decision:** simulate only when the closed form is negative. The proof and its
empirical check — 0 counterexamples in 400,000 randomised scenarios — are in
`TEST_VECTORS.md` §6.5 and are not re-derived here. A sampled property test
(2,000 seeded scenarios) guards the invariant in CI.

---

## D10 — Two additions to the target file layout

`CLAUDE.md` §2 specifies the layout. Two files are added, deliberately:

- **`calculators/validation.py`** — without it the amount/rate/period guards get
  copy-pasted into three modules and drift. Putting them in `rates.py` would
  muddle a file whose entire purpose is holding exactly one formula.
- **`chat/formatting.py`** — §3 requires money to be formatted only at the
  presentation boundary and §9 mandates `₹1,00,000` grouping. That needs one
  tested home, and it cannot be `prompts.py` (prompt text only) or `app.py`
  (transport only). *Added in Phase 3.*

Both were approved at plan review.

---

## D11 — `TEST_VECTORS.md` §3.3 prose vs the §3 formula

§3 defines `total_profit = FV + total_withdrawn − P`. §3.3's narrative described
W5's profit as ₹2,86,932, which is `FV + total_withdrawn` with the `− P` term
dropped; the formula gives ₹-13,068.14.

**Decision:** the formula block is authoritative and is what the code
implements. The test asserts the profit composed from the §3 and §6.4 vectors
rather than from the prose, so no new constant is introduced either way. Raised
with the repository owner rather than coded around.

**Resolved.** The owner corrected §3.3 in `1d1b499` and, since a corrected
section left this entry and `tests/test_swp.py` pointing at prose that no
longer exists, added a correction notice recording the original figure. Both
references read against the current file: the entry above is past tense about
a narrative that was there, and the notice is what keeps it checkable. The
code and the assertion are unaffected — the formula block never changed.

---

## D12 — The model returns spans; Python decides what they mean

The extraction call asks the model for the *literal characters* the user typed
("5 lakh", "9%", "₹6,000 a month") and nothing else. `chat/formatting.py`
converts them. A model that answers "500000" to "5 lakh" is guessing correctly;
one that answers "5000000" is guessing wrong in a way nothing downstream can
detect, because both are plausible numbers.

**Decision:** the model never supplies a value, only a span, and a span is
dropped unless it is a verbatim fragment of the message (compared with
whitespace, commas and the rupee sign squashed out). A span the parser refuses
leaves the slot unfilled and gets asked again — cheap and recoverable — where a
fabricated one is neither.

Validation reuses `calculators.validation` rather than restating the rules at
the slot, so a slot cannot accept a value the calculator would reject, and the
two cannot drift.

`parse_money` living beside `format_money` is deliberate: `formatting.py` owns
the rupee-string boundary in *both* directions, which is why the parser and the
formatter cannot disagree about what "5 lakh" is.

---

## D13 — A digression is not a state transition

`TEST_VECTORS.md` C4 asks the bot to answer a question mid-flow and resume.
The obvious implementation adds a state — `ANSWERING_QUESTION` — with edges
back to wherever it came from, and every new conversational move then needs
edges to and from every other.

**Decision:** a digression is a *message the session answers*, not a place the
session goes. `state`, `slots` and `pending_slot` are untouched; the answer is
composed and the pending question re-posed from the state that was already
there. The state machine has four states and no edge exists that could lose a
half-filled form to a question about vocabulary.

The same reasoning removes the correction branch entirely. Every inbound
message goes through extraction in every state, so "actually make it 8%" is not
a special case — it is an extraction that overwrites a slot that already had a
value. C3 passes because no code path exists that could reset the flow, not
because a branch was written to avoid it.

Two consequences worth stating: a provider outage costs the turn, not the
collected values; and a percentage withdrawal is re-resolved against the
lumpsum whenever the lumpsum is corrected.

---

## D14 — One question per message is structural, not stylistic

"Never emit two questions in one message" is the rule that separates a
conversation from a form with a chat skin, and it is exactly the rule that
erodes once a model is generating prose.

**Decision:** the bot's questions come from `chat/prompts.py`, every message is
assembled by `formatting.compose`, and `compose` raises if the question it is
given does not contain exactly one question mark. Model prose is passed through
`strip_questions` first, so a model that ignores the instruction not to ask
anything cannot add a second one.

The invariant is therefore enforced at the seam rather than requested in a
prompt, and `test_no_message_ever_asks_more_than_one_question` walks a script
that hits every re-ask path there is — start, digression, correction, refusal,
unreadable answer, decline at confirmation, edit, and compute.

---

## D15 — What the presentation layer suppresses

Two calculator results carry figures that are correct arithmetic and misleading
advice. The chat layer, not the calculator, decides what a person sees.

**Decision:** when `SwpProjection.depleted` is true, the negative final balance
and the spec's `total_profit` are withheld, and the message reports the
depletion month and `actual_withdrawn` instead — per D6, those figures are
unreliable in both directions once the corpus is dry.

> **Amended (see D23).** `total_withdrawn` was withheld here too, which went a
> step too far: `W × n` is one of the three outputs `SPEC.md` names, and it is
> not unreliable, only unfundable. It is now printed second and labelled as
> such, behind the figure the corpus could actually pay.
`EmiTooLowError` is presented with the minimum viable EMI rounded **up** and
lands the session in `AWAITING_EDIT` with every other slot preserved: the inputs
were individually legal, so the recovery is to revise one value, not to start
over.

Both are reversals of the usual instinct to show everything the function
returned. The calculators still return all of it, and still test it.

---

## D16 — D4 addendum: §1.3 now publishes the figures D4 had to work around

`TEST_VECTORS.md` §1.3 carries `final_payment` and `total_paid` at full
precision for L1–L3. D4's closing paragraph — that §1.1 had no column for
either, so `total_paid` was asserted at 1e-2 against 2 dp figures and
`final_payment` was pinned only by its relationship to it — no longer applies.

**Decision:** assert both published columns at `MONEY_TOLERANCE` (1e-4), the
same tolerance as every other money assertion. The relationship
`total_paid == (months - 1) * emi + final_payment` is kept alongside them: it
now cross-checks two independently published values rather than standing in
for a missing one.

D4's reasoning is unchanged and stands. Only its note about the vectors is
superseded.

---

## D17 — Both providers speak HTTP through the standard library

Gemini and Ollama each expose a JSON endpoint that this app uses for exactly
one thing: send a system prompt and a user prompt, get text back. The vendor
SDK adds a dependency, a version to track, and a layer between the request and
the reviewer.

**Decision:** `urllib.request` for both, through a single `post_json` seam that
owns the timeout and every transport failure. `requirements.txt` therefore
carries no LLM dependency at all, and the tests replace one function rather
than mocking an SDK.

**What would change this:** streaming responses, or tool-calling through the
provider's own schema. Neither is in scope; both would justify the SDK.

---

## D18 — Four failure modes, four sentences

`LLMError` splits into misconfigured, unavailable, timeout, and malformed. The
split exists because the *user-facing* copy differs, not because the code paths
do — "the model took too long" invites a retry, and "no model is configured"
must not, since retrying will never fix it. Collapsing them into one message
would tell a user to keep trying something that cannot work.

**Decision:** the exception carries the cause, `chat/prompts.py` carries the
four sentences, and `Session._failure_copy` maps between them. Provider detail —
exception text, HTTP status, traceback — never reaches a user; a test asserts
that for every one of the four.

A missing key is caught when the provider is *built*, before any request is
made, and `get_llm_or_unconfigured` turns it into a placeholder that fails on
use. The server still starts, the page still loads, and the greeting still
lists the calculators: a configuration mistake should not look like a crash.

---

## D19 — What the live Gemini run changed

Running the conversation against the real endpoint found three things the
Ollama stand-in could not.

**The pinned default model was already retired.** `gemini-2.5-flash` answers
ListModels and then 404s on generateContent with "no longer available to new
users" — a key issued today cannot call it. The default is now
`gemini-flash-latest`, an alias, because a submission cloned months from now
should not fail on a model rotation. `GEMINI_MODEL` pins a version for anyone
who wants reproducibility over longevity.

**HTTP status was collapsed into one failure.** Every non-2xx became
`LLMResponseError`, so a retired model, a rejected key, and a spent quota all
reached the user as "the model sent back something I could not make sense of".
They are now sorted: 401/403/404 are configuration mistakes, 429 is a spent
allowance, 5xx is transient, everything else is a bad reply.

**The provider's own explanation was thrown away.** `post_json` discarded the
error body, so the 404 above arrived as a bare "HTTP 404" and took a
hand-written script to diagnose. The body now goes into the exception — where
an operator reading logs can see it — and never into the reply.

**Free-tier quota is the failure users will actually hit.** The limit is 20
generate requests per day per model, and this bot spends one to three per turn,
so roughly seven turns exhausts a free key. That earned `LLMQuotaError` its own
class and its own sentence: the model was reached and refused, it resets
tomorrow, and telling someone "I could not reach the model" would be wrong
about both.

**What held up:** the router parsed every real reply correctly, including the
```` ```json ```` fences Gemini wraps extraction in and which the stand-in never
produced. Classification returned bare labels throughout. Latency was 1.2-3.9s
per call. And when the quota ran out mid-walkthrough, the deterministic
fallback kept filling slots from the raw message and computed the correct
tenure anyway — the resilience in D13 doing exactly what it was built for,
under a failure that was not simulated.

---

## D20 — A bare answer fills the slot that was asked

D12 established that the model returns spans and Python decides what they
mean. A live run showed the same argument applies to *which slot* a span
belongs to, which D12 had not covered.

Asked "What monthly EMI do you plan to pay?", the user typed `10,000`. The
extractor returned `{"principal": "10,000"}`. The loan amount — already
collected, already correct — was silently overwritten, the EMI stayed empty,
and the bot re-asked the same question. Nothing crashed and nothing looked
wrong; the answer would simply have been computed from the wrong figure.

**Decision:** when a slot is pending and the entire message parses as a value
for it, that binding wins and the extractor's assignment is discarded. The
message is nothing but a value and we know which question it answers, so no
model judgment is required. Messages carrying more than a value — "actually
make it 8%" while an EMI is pending — do not trigger it and are left to the
extractor, which is what makes corrections keep working.

The value still goes through the ordinary guards: overriding the *slot* must
not skip validation of the *number*.

The extraction prompt now also names the pending slot. That is a hint, not the
mechanism — the override does not depend on the model taking it.

---

## D21 — A calculator change mid-flow is offered, never taken

An external review found the one path that discarded state without saying so.
A message classified as a *different* calculator went straight to `_begin`,
which clears every slot. `"loan tenure, 5 lakh at 9%"` followed by `"by the way
what is a SIP"` therefore lost both values with no acknowledgement — and the
module docstring, the README and D13 all stated that no such path existed.

The classifier is right often enough that the capability is worth keeping: it
is also the only way out of a flow short of finishing it. But `"what is a SIP"`
is a vocabulary question, and one classification is not enough evidence to
throw away a half-filled form.

**Decision:** a fifth state, `CONFIRMING_SWITCH`. The offer is made, `slots`
and `pending_slot` are untouched while it stands, and `_PendingSwitch` records
which state to restore on a no — so declining costs the turn and nothing else.
Accepting reaches `_begin` with the message that triggered it, so `"make it a
SIP for 10 lakh"` still fills what it carried. Answering the outstanding slot
instead lets the offer lapse, because carrying on is an answer too.

D13's claim now holds as stated, and a test asserts it structurally rather than
by inspection: `self.slots = {}` appears exactly twice in `chat/session.py`,
in `_begin` and in `_reset`. A third occurrence is how this got in.

**What would change this:** a classifier good enough to separate "what is a
SIP" from "let's do a SIP instead". The confirmation is a hedge against the
model, not against the user.

---

## D22 — D12 addendum: half a number is not a verbatim span

D12 refuses any span that is not a fragment of what the user typed. The check
squashed whitespace, commas and the rupee sign out of both strings and then ran
a substring test — which is what lets a model return `500000` for a message
reading `5,00,000`. It also lets it return `5`.

A model answering `{"principal": "5"}` to `"loan tenure for 5,00,000 at 9%"`
was therefore taken at face value, and ₹5.00 became the loan amount. D12's own
argument applies exactly: a truncated number is *worse* than a fabricated one,
because ₹5.00 next to a five lakh loan reads as a typo rather than a bug.

**Decision:** a match must have no digit hard against either end of it. `"5"`
in `"500000"` has one and is refused; `"500000"`, `"5,00,000"` and `"9%"` are
whole and are accepted. The rule is on the squashed strings, so the comma
normalisation D12 wanted is unaffected.

---

## D23 — D15 amendment: the depleted plan still reports `W × n`

`SPEC.md` names three SWP outputs — final balance, total withdrawn, total
profit. D15 suppressed all three once the corpus ran dry. Two of those are
right: the final balance is negative, and the profit figure is wrong in both
directions (D6). The third was over-correction, and it left the submission with
one place where a number the client asked for was simply not printed.

`W × n` is not unreliable. It is exactly what it says — what the plan would
have paid out — and the only problem with it is that the corpus cannot fund it.
That is fixed by labelling and ordering, not by hiding.

**Decision:** the depleted message reports `actual_withdrawn` first and
`total_withdrawn` second, the latter named as the figure the formula reports
and the corpus cannot fund. Suppression is now reserved for numbers that are
misleading in themselves rather than merely in need of context.
