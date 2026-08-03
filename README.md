# Finance chatbot with interactive calculators

A chatbot that talks about personal finance and runs three calculators — **loan
tenure**, **SIP for a target amount**, and **SWP** — collecting their inputs one
question at a time rather than presenting a form.

The language model classifies intent, pulls values out of what you typed, and
phrases replies. **It never does arithmetic.** Every number in a reply came from
a pure, separately tested function in `backend/calculators/`.

---

## Run it

**Python only. No Node, no build step** — the frontend's build output is
committed, so the server has a page to serve out of the box.

```bash
git clone https://github.com/RishiDixit-7404/bfc-softtech-assignment.git
cd bfc-softtech-assignment/backend

python3 -m venv ../.venv && source ../.venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # put your Gemini key in it
set -a; source .env; set +a

python app.py                 # http://127.0.0.1:8000
```

```bash
pytest -q                     # 411 tests, from the root or from backend/
```

---

## Layout

```
├── README.md          this file — what the project is
├── SPEC.md            the client's brief, transcribed verbatim
│
├── backend/           Python. The server, the conversation, and all the maths.
│   ├── README.md      ← how it works, the formulas, the design decisions
│   ├── app.py         FastAPI: routes, session id, serialization. No logic.
│   ├── chat/          intent routing, slot-filling state machine, LLM adapter
│   ├── calculators/   pure functions. Deterministic. The only place maths exists.
│   ├── mcp_tools/     the same calculators exposed as MCP tools over stdio
│   ├── tests/         411 tests. No API key, no network, no env var needed.
│   ├── ui/            committed frontend build, served by app.py
│   └── TEST_VECTORS.md   independently verified ground truth for every formula
│
└── frontend/          Vite + React + TypeScript. Builds into backend/ui.
    ├── README.md      ← the stack, the constraints, the design
    └── src/
```

Two documents worth reading before the code, both in
**[backend/README.md](backend/README.md)**: the SIP formula in `SPEC.md`
multiplies where a standard annuity-due solve divides, and the spec asks for
three calculators in one paragraph and two in another. Both are handled
deliberately rather than silently.

---

## How the pieces fit

```
frontend/  ──build──►  backend/ui/  ──HTTP──►  app.py  ──►  chat/  ──►  calculators/
React + TS             committed              routes,      routing,     pure
reads the shape        output, no             no logic,    slots,       functions.
of a reply,            external request       no maths     prompts      All maths.
never its values                                            │             ▲
                                                            └►mcp_tools/──┘
                                                              same calculators
                                                              as MCP tools (opt.)
```

**The dependency arrow never reverses.** `calculators/` imports nothing from
`chat/`, `app` or `mcp_tools/`, and the frontend never computes, re-rounds or
re-groups a number — both are enforced by tests, not by convention. So every
formula can be read against `SPEC.md` without knowing a chatbot exists, and there
is exactly one place in the system with an opinion about what a rupee looks like.

| | |
| --- | --- |
| **[backend/README.md](backend/README.md)** | the formulas and their edge cases, the conversation state machine, the MCP tool server, the test strategy |
| **[frontend/README.md](frontend/README.md)** | the stack, why the build output is committed, what the frontend is forbidden from doing, the design choices |
| **[SPEC.md](SPEC.md)** | the task as given |
| **[backend/TEST_VECTORS.md](backend/TEST_VECTORS.md)** | every expected value, computed from the spec's closed form and cross-checked by month-by-month simulation |

---

## What is deliberately not here

No authentication, no database, no user accounts, no persistence. `SPEC.md`
excludes them; a conversation lives in process memory for as long as the server
runs, and no longer.
