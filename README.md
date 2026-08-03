# Finance chatbot with interactive calculators

A chatbot that talks about personal finance and runs three calculators — loan
tenure, SIP for a target amount, and SWP — collecting their inputs one question
at a time rather than presenting a form. The model classifies intent, pulls
values out of what you typed, and phrases replies; **it never does arithmetic**.
Every number in a reply came from a pure, separately tested function in
`calculators/`.

---

## Run it

**Python only. No Node, no build step.**

```bash
git clone https://github.com/RishiDixit-7404/bfc-softtech-assignment.git
cd bfc-softtech-assignment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # put your Gemini key in it
set -a; source .env; set +a   # export it (survives spaces in values)

python app.py                 # http://127.0.0.1:8000
```

The frontend's **build output is committed** to `ui/`, so that block is the whole
story. Sources are in `frontend/`; you need them only to *change* the interface.

No key? `export LLM_PROVIDER=ollama OLLAMA_MODEL=qwen2.5:7b-instruct` with
`ollama serve` running. Without either, the server still starts and the page
still loads — the first message says what is missing instead of showing a stack
trace.

> **Gemini free tier: 20 requests/day, per model.** A turn costs one to three,
> so a free key is good for ~7 turns before returning 429. The bot reports that
> as a spent allowance and keeps every value you gave it. `GEMINI_MODEL` switches
> model when one model's daily 20 is gone.

---

## Two things in the spec worth reading first

**The SIP formula multiplies where a standard annuity-due solve divides.**
`SPEC.md` gives `SIP = (Target·r / ((1+r)^(n·12) − 1)) × (1 + r)`; the
conventional form divides. The spec's version overshoots the target by exactly
`(1+r)²` — ₹19,067.62 against a ₹10,00,000 goal. **Implemented verbatim**,
because it is the client's stated requirement, with two tests pinning it: one
asserts the spec value, one asserts the ratio against the annuity-due value, so
the deviation is demonstrably understood rather than transcribed. Reasoning in
`calculators/sip.py`.

**The spec asks for three calculators and two calculators.** The intro promises
all three and requires the bot to say so on start-up; the note under *Behavior*
says "integrate any two". Two would make the mandated start-up message advertise
something that does not exist, so **all three are implemented**.

---

## Division of labour

| The model does | The model never does |
| --- | --- |
| classify: calculator, finance question, or off-topic | any arithmetic |
| return the *literal span* a value appears in — `"5 lakh"`, `"9%"` | interpret that span into a number |
| phrase a finance answer | decide what to ask next |

A model answering `500000` to "5 lakh" guesses right; one answering `5000000`
guesses wrong in a way nothing downstream can detect. So `chat/formatting.py`
converts in Python, and a span that is not a verbatim fragment of the message is
dropped as invented. Half a number is not a fragment either: commas are squashed
before comparing, which makes `5` a substring of `5,00,000`, so the check also
requires no digit sit hard against either end. `₹5.00` for a five lakh loan reads
as a typo rather than a bug, which is what makes it the more dangerous mistake.

**Gemini by default** via the `gemini-flash-latest` alias — an alias because
`gemini-2.5-flash` is still listed by the API but 404s for keys issued today, and
a submission read months from now should not fail on a model rotation. Neither
provider uses a vendor SDK: both expose a JSON endpoint and this app needs one
thing from them, so both go through `urllib` and a single `post_json` seam.
`requirements.txt` carries no LLM dependency as a result.

---

## Architecture

```
  frontend/  ──build──►  ui/  ──HTTP──►  app.py  ──►  chat/  ──►  calculators/
  React + TS             committed       routes,      routing,     pure
  reads shape,           output, no      no logic,    slots,       functions.
  never values           external req.   no math      prompts      All math.
                                                        │              ▲
                                                        └► mcp_tools/ ─┘
                                                           same calculators
                                                           as MCP tools (opt.)
```

**The dependency arrow never reverses.** `calculators/` imports nothing from
`chat/`, `app` or `mcp_tools/`, and `mcp_tools/` nothing from `chat/` or `app` —
both are structural assertions in `tests/test_guards.py`, not conventions. Every
formula can be read against `SPEC.md` without knowing a chatbot exists.

| File | Holds |
| --- | --- |
| `calculators/rates.py` | `monthly_rate()`, defined exactly once in the repo |
| `calculators/validation.py` | the amount/rate/period guards, shared so they cannot drift |
| `chat/session.py` | the state machine: `IDLE`, `COLLECTING`, `CONFIRMING`, `AWAITING_EDIT`, `CONFIRMING_SWITCH` |
| `chat/router.py` | every call made to a model — classify, extract, answer |
| `chat/prompts.py` | every word the bot says. Prompt text lives nowhere else |
| `chat/formatting.py` | the number/text boundary, both directions |
| `mcp_tools/wire.py` | the error boundary — exceptions across a process, structure intact |
| `frontend/src/lib/replyStructure.ts` | reply text → paragraphs and list items. Reads no value |

Four rules make it a state machine rather than a form in disguise:

- **One question per message**, enforced structurally: `formatting.compose`
  raises on anything but exactly one question mark.
- **A digression is not a state transition.** `state`, `slots` and
  `pending_slot` are untouched by it.
- **Every message goes through extraction, in every state**, so a correction is
  an extraction overwriting a filled slot rather than a special case.
- **Nothing is discarded without a yes.** Naming a different calculator mid-flow
  would legitimately clear the slots, and "by the way, what is a SIP" classifies
  as SIP often enough that acting on it loses real work — so it is offered, and a
  no restores what it interrupted. A test asserts at the source that only
  `_begin` and `_reset` clear `slots`.

---

## A conversation

Captured output, not written by hand. Ollama `qwen2.5:7b-instruct`, because
Gemini's free tier ran out mid-capture. Abridged; the middle slot-filling turns
are the obvious ones.

```
you: I want to work out my loan tenure
bot: How much is the loan?

you: 5 lakh
bot: What monthly EMI do you plan to pay?

you: wait, what is an EMI?
bot: An EMI stands for Equated Monthly Installment, which is the fixed amount
     you pay monthly to repay a loan, including both interest and principal,
     over a set period.

     What monthly EMI do you plan to pay?
                                            ← digression answered, nothing lost
you: 10,000
bot: What is the annual interest rate?

you: 8%
bot: Here is what I have:
     - loan amount: ₹5,00,000.00
     - EMI: ₹10,000.00
     - annual interest rate: 8%

     Shall I run the loan tenure calculation with those?

you: actually make it 9%
bot: Updated annual interest rate to 9%.

     Here is what I have:
     - loan amount: ₹5,00,000.00
     - EMI: ₹10,000.00
     - annual interest rate: 9%

     Shall I run the loan tenure calculation with those?
                                            ← one value changed, not a restart
you: yes
bot: That loan is cleared in 5 years & 3 months.
     - Payments: 63, rounded up from 62.22 months - the last month is a part payment, not a whole EMI.
     - Final instalment: ₹2,245.30.
     - Total repaid: ₹6,22,245.30.

     Anything else I can work out?
```

That result is vector **L1** from `TEST_VECTORS.md` to the paisa, because the
model never touched the arithmetic. Off-topic messages and injection attempts get
fixed copy from `chat/prompts.py` rather than model output, so there is nothing
for an injection to talk its way past and no system prompt to leak.

---

## Edge cases handled

| Case | Behaviour | Where |
| --- | --- | --- |
| EMI ≤ monthly interest | `EmiTooLowError`, naming the bound (₹3,603.66 on ₹5,00,000 at 9%) **and** a whole rupee that clears it (₹3,604), keeping every other value so one edit rescues the scenario | `calculators/errors.py` |
| Boundary `E == P·r` | Rejected too — an EMI equal to the interest holds the balance flat forever | `calculators/errors.py` |
| SWP corpus runs dry | Depletion month found **by simulation**, never by inverting the formula. Negative balance and the spec's profit suppressed, `actual_withdrawn` reported; the spec's `W × n` appears beside it, labelled unfundable | `calculators/swp.py` |
| `R = 0`, all three | Each closed form degenerates (`log(1)=0`, `(1+r)^n−1=0`, `0/0`). Branched explicitly. At `R=0` SWP profit is exactly `0.0`, asserted as an invariant | `calculators/rates.py` |
| Calculator changed mid-flow | Offered, not taken. Values held until confirmed | `chat/session.py` |
| Correction / digression | Slot overwritten and re-confirmed, or question answered and re-posed. Never restarts | `chat/session.py` |
| Injection attempt | Classified off-topic. Prompt never disclosed; instructions in user input are data | `chat/prompts.py` |
| Unreadable or truncated span | Slot left unfilled and asked again. `"5"` out of `"5,00,000"` refused like a fabrication | `chat/router.py` |
| Withdrawal as a percentage | Resolved through the same function as the rupee path, echoed before computing | `calculators/swp.py` |
| Model down, slow, babbling, unconfigured | Four distinct plain sentences. No traceback, no HTTP status, no provider JSON reaches the user, no collected value lost | `chat/llm.py` |

---

## The calculators as MCP tools

```bash
python -m mcp_tools.server                 # the server on its own
CALCULATOR_TRANSPORT=mcp python app.py     # the bot, calling it as tools
```

`direct` (the default) calls the functions in process; `mcp` starts the server as
a child process and calls the same functions over JSON-RPC 2.0. **The answers are
identical objects, not merely equal numbers** — `pytest -q` passes in both modes.
`calculators/` did not change to make this work, and a guard test asserts the
adapter reaches a calculator only through `CALCULATORS[name].function`.

Tool schemas state units and bounds, taken from `calculators/validation.py`'s own
constants rather than restated. The SIP tool also carries the annuity-due
warning, what it costs, and how to recover the conventional figure — a caller
checking the arithmetic from outside has nowhere else to learn it.

**The interesting part is the error boundary.** `chat/formatting.py` does not
render `str(exc)`; it reads `EmiTooLowError.minimum_emi`, `.monthly_interest` and
`.principal` at full precision and formats them into Indian grouping. Flattening
the exception to a string across a pipe would take all of that away and still
look like it worked. So the wire carries the structure:

```
"structuredContent": {"ok": false, "error": {
    "type": "EmiTooLowError",
    "data": {"principal": 500000.0, "emi": 3000.0,
             "monthly_interest": 3603.6616580683576,
             "minimum_emi":      3603.6616580683576}}}
```

That arrives as an `EmiTooLowError` passing every `isinstance` check, floats
undamaged, rendering the same sentence the direct path renders — a test compares
the two. `chat/session.py` changed by one line to support this, and
`chat/formatting.py` by none.

The protocol is hand-written against the standard library rather than taken from
the `mcp` SDK, which is async throughout against a synchronous state machine and
brings ~12 transitive dependencies to a five-line `requirements.txt`. The cost is
that only the needed slice exists, so it is listed rather than left to be found:
**implemented** — `initialize`, `notifications/initialized`, `ping`,
`tools/list`, `tools/call`, `isError` results, stdio; **not implemented** —
resources, prompts, sampling, completion, progress, cancellation, subscriptions,
the SSE and streamable-HTTP transports, auth. Needing any of those, or needing to
be a *client* of servers written by other people, is what would make the SDK the
right answer instead.

---

## Frontend

**Vite + React 19 + TypeScript**, source in `frontend/`, building to `../ui`.

```bash
cd frontend && npm install
npm run dev        # localhost:5173, proxying /session and /chat to :8000
npm test           # Vitest + React Testing Library, 44 tests
npm run build      # type-checks, then writes ../ui
```

**Why the build output is committed.** Usually wrong; here the reviewer's path
has to be `pip install && python app.py`, and ignoring `ui/` would turn a Python
submission into one needing a Node toolchain to show its own page. It also keeps
`app.py` honest — it already mounted `ui/`, so replacing the entire frontend
changed no Python at all. The costs are accepted rather than denied: `ui/` is
only correct if someone ran `npm run build`, mitigated by landing `frontend/` and
`ui/` in the same commit and by `tests/test_ui_build.py` failing if `ui/` is
missing or references something absent. `node_modules` is not committed.

**What it is not allowed to do.** `chat/formatting.py` owns money and stays the
only thing with an opinion on how an amount looks, so the frontend reads the
*shape* of a reply and never its values:

| Presentation — fine | Business logic — not |
| --- | --- |
| a blank line becomes a paragraph break | parsing a `₹` figure out of a sentence |
| a leading `- ` becomes a real `<li>` | re-rounding, re-grouping, abbreviating to lakh |
| `tabular-nums` so amounts align in a column | computing a total the server did not send |

`replyStructure.ts` matches exactly two things — a blank line and a leading
`"- "` — and no digit, `₹` or percent sign anywhere; every string it emits is a
substring of what it was given. Three tests hold that line, one extracting every
`[₹0-9.,%&]` character from the rendered DOM and requiring it to match the reply.
The API contract is unchanged for the same reason: `{session_id, reply}`, reply a
plain string. A frontend needing a richer payload would be one asking to do
arithmetic.

**Structure.** A typed `api/client.ts` is the only module that knows the server
exists; `hooks/useConversation` owns all session state; components take props and
fetch nothing.

- **Conversation, not chat bubbles** — turns separated by a rule and a small caps
  label. A result is a short table of amounts, and a tinted rounded rectangle is
  a worse place to read one than a plain column.
- **One 65ch measure** and `tabular-nums`, so figures align down the page.
- **Both themes chosen, not inverted** — the accent lightens for dark because
  `#1f4b7a` has 9:1 contrast on white and 2:1 on charcoal. Every pair clears AA.
- **Real states** — field disabled with a "Working that out" indicator in flight.
  A fetch failure and a 404 unknown session get different messages, because
  retrying fixes one and never the other, and neither leaves a dead input without
  an explanation and a way out beside it.
- **Chips derived from the greeting**, so they cannot advertise a calculator that
  does not exist.
- **Accessibility** — keyboard-only end to end, one `:focus-visible` ring never
  removed, `role="log"` with `aria-live` and `aria-busy`, a real `<label>`,
  `prefers-reduced-motion` honoured, responsive to 360px.
- **No external request** — system fonts, no CDN, asserted from Python against
  the committed artifact.

---

## Tests

```bash
pytest -q                            # 411 tests
CALCULATOR_TRANSPORT=mcp pytest -q   # the same 411, over MCP
cd frontend && npm test              # 44 tests, needs Node
```

The Python suite needs **no API key, no network, and no environment variable** —
the model is stubbed, so it runs from a fresh clone. Python 3.10 through 3.13.

- Every numbered case in `TEST_VECTORS.md` — L1–L11, S1–S7, W1–W10, G1–G5 and
  the degenerate-path vectors in §6. Those values were committed *before* any
  implementation existed, so a passing test proves the code matches the spec
  rather than that the expectations were fitted to the code.
- Conversation fixtures C0–C8, through a stub model.
- Structural guards: `monthly_rate` defined exactly once; no named quantity
  divided by 12, 1200 or a months-per-year constant in `calculators/`, with cases
  proving the guard fires on `rate / 1200` *and* leaves `rates.py`'s own
  `** (1 / 12)` alone; no upward imports; every failure a `CalculatorError`; no
  result field ever `NaN` or infinite.
- Transport: unique session ids, replies reaching only their own session, 404 on
  an unknown id, `StaticFiles` at `/` not shadowing the POST routes.
- Both providers: request shape, per-task temperature, every failure mode.
- The committed build: no external URL in any `src`, `href` or `@import`, every
  reference resolving to a file that exists. Deliberately a Python test — `ui/`
  is the one directory nobody writes by hand, so a CDN arriving via a dependency
  shows up only in the bundle, and this is the suite that runs without a
  toolchain.

`TEST_VECTORS.md` is worth reading on its own. Every value was computed from the
`SPEC.md` closed form and independently cross-checked by month-by-month
simulation — amortising the loan, compounding the SIP, draining the SWP — and
where the two disagree, that disagreement is the interesting part.

---

## What is deliberately not here

No authentication, no database, no user accounts, no persistence. `SPEC.md`
excludes them; a conversation lives in process memory for as long as the server
runs, and no longer.
