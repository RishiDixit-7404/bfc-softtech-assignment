# SPEC — Take-Home Task: Financial Chatbot with Interactive Calculators

> **Status:** Source of truth. Transcribed verbatim from the provided PDF.
> Do not edit to match the implementation. If the implementation disagrees with
> this file, the implementation is wrong — or the disagreement is a deliberate,
> documented decision recorded in `DECISIONS.md`.

**Level:** Fresher  **Time:** 2 days  **Effort:** ~8–10 hours

---

## The Task

Build a chatbot that discusses **financial topics only** (savings, loans, investing,
interest, budgeting, etc.) and can run **three interactive calculators** on request.
If asked anything off-topic, it should politely decline and steer the user back to
finance.

On start, the bot should tell the user it can calculate:

1. Loan Tenure
2. SIP for a target amount
3. SWP (Systematic Withdrawals)

---

## Behavior

- General finance questions → answered conversationally by the LLM (Ollama or
  Gemini, candidate's choice).
- Off-topic questions (weather, coding help, general trivia, etc.) → politely
  refuse and redirect to finance topics.
- Calculation requests → the bot must **ask for missing inputs one at a time**
  (interactively — *not* all at once as a form), confirm the values back to the
  user, then compute and show the result clearly.
- **Note: Integrate any two calculators from the choices below.**

---

## Calculator 1 — Loan Tenure

**Ask for:** loan amount (P), EMI amount (E), annual interest rate (R)

```
        log( E / (E - P·r) )
n  =  ------------------------
             log(1 + r)
```

where `r` is the **monthly** rate:

```
r = (1 + R/100)^(1/12) - 1
```

This is only valid when `E - P·r > 0` (i.e. EMI must exceed the monthly interest,
otherwise the loan never gets paid off — **the bot should detect this and tell the
user rather than crash or return nonsense**).

**Show your answer in years & months.** Eg: `1.5 => 1 year & 6 months`

---

## Calculator 2 — SIP for a Target Amount

**Ask for:** target amount, expected annual return rate (R), investment period (years)

Monthly rate:

```
r = (1 + R/100)^(1/12) - 1
```

Result:

```
             Target × r
SIP  =  --------------------  × (1 + r)
         (1 + r)^(n×12) - 1
```

where `n` is the investment period in **years**.

---

## Calculator 3 — SWP (Systematic Withdrawal Plan)

**Ask for:** lumpsum amount (P), investment period (years), expected annual return
rate (R), and withdrawal amount (**either a fixed monthly amount or a % of the
lumpsum — bot should accept either**)

Monthly rate:

```
r = (1 + R/100)^(1/12) - 1
```

```
                        (1 + r)^n - 1
FV  =  P(1 + r)^n  -  W · -------------
                              r
```

Report all three: **final balance (FV)**, **total withdrawn** (`W × n`), and
**total profit** (`FV + total withdrawn − P`).

---

## Requirements

- Validate inputs (no negative amounts, sane rate ranges, the EMI-vs-interest edge
  case above) and give a clear message instead of crashing.
- Simple UI is fine — **a minimal web page is expected**.
- Reasonably organized code (**calculators separated from chat/LLM logic**).

---

## MCP Angle (bonus, not required)

If you want to go further: expose the three calculators as **MCP tools** instead of
local function calls, and have the chatbot (as an MCP client) invoke them that way.
This isn't required to pass, but candidates who attempt it show stronger alignment
with how we actually want this integrated long-term.

---

## What to Submit

- GitHub repo or zip.
- `README.md`: how to run it, which LLM you used, and 2–3 example conversations
  covering:
  1. a general finance question,
  2. an off-topic question being declined,
  3. one full calculator walkthrough.

---

## Not Required

- No dependency on any data they provide — this task is fully self-contained.
- No user accounts, persistence, or auth.

---

*This file is a verbatim transcription of the provided task PDF. It is committed
so that the implementation can be read against a fixed, unedited statement of
requirements.*
