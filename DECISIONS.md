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
and reproduced independently before use; `final_payment` is pinned by asserting
the relationship above rather than by an invented literal, since
`TEST_VECTORS.md` §1.1 carries no column for either yet.

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
returned exactly as specified; the presentation layer suppresses them in favour
of the depletion report when `depleted` is true.

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
`minimum_emi = P·r` at full precision; the message states it rounded **up**,
because rounding down would print a target that is still too low.

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

§3 defines `total_profit = FV + total_withdrawn − P`. §3.3's narrative describes
W5's profit as ₹2,86,932, which is `FV + total_withdrawn` with the `− P` term
dropped; the formula gives ₹-13,068.14.

**Decision:** the formula block is authoritative and is what the code
implements. The test asserts the profit composed from the §3 and §6.4 vectors
rather than from the prose, so no new constant is introduced either way. Raised
with the repository owner rather than coded around.
