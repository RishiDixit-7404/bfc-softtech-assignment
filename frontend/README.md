# Frontend

**Vite + React 19 + TypeScript.** Source here, building into `../backend/ui`,
which `backend/app.py` serves.

**You do not need any of this to run the app.** The build output is committed, so
`cd backend && python app.py` is enough. You need what follows only to *change*
the interface.

```bash
npm install
npm run dev        # localhost:5173, proxying /session and /chat to :8000
npm test           # Vitest + React Testing Library, 44 tests
npm run build      # type-checks, then writes ../backend/ui
```

`npm run dev` expects `python app.py` running on port 8000; the proxy is two lines
of `vite.config.ts` and exists only for development. The built page talks to its
own origin and makes no external request at all.

---

## Why the build output is committed

Committing build output is usually wrong: unreadable diffs, conflicts in minified
bundles, and a repository that can disagree with itself about what its source
produces.

Here the reviewer's path has to be `pip install && python app.py`. If
`backend/ui/` were ignored, cloning and starting the server would give a 404 from
`StaticFiles`, and the fix would be to install a Node toolchain and run a build —
for a submission whose actual subject is three financial formulas and a
slot-filling state machine. Making a Python reviewer install npm to see the page
is a worse failure than a noisy diff.

It also keeps `app.py` honest. It already mounted the directory beside it, so
replacing the entire frontend changed no Python at all.

The costs are accepted rather than denied:

- **The output can go stale** — it is only correct if someone ran `npm run build`
  before committing. Mitigated by landing `frontend/` and `backend/ui/` in the
  same commit, and by `backend/tests/test_ui_build.py` failing if the build is
  missing or references a file that is not there.
- **Bundle diffs are unreadable.** Accepted; hashed filenames at least make a
  rebuild obvious rather than a silent overwrite.
- **Two test suites.** `pytest -q` covers Python and asserts the *artifact*;
  `npm test` covers the frontend and needs Node. The Python suite is the one that
  must never require a toolchain, which is why the no-external-request assertion
  lives there.

`node_modules` and Vite's caches are not committed.

---

## What the frontend is not allowed to do

`backend/chat/formatting.py` owns money. It produced every `₹6,22,245.30` in
Indian grouping at the presentation boundary, and it stays the only thing in the
system with an opinion on how an amount looks. So the frontend reads the **shape**
of a reply and never its values:

| Presentation — fine | Business logic — not |
| --- | --- |
| a blank line becomes a paragraph break | parsing a `₹` figure out of a sentence |
| a leading `- ` becomes a real `<li>` | re-rounding, re-grouping, abbreviating to lakh |
| `tabular-nums` so amounts align in a column | computing a total the server did not send |

`src/lib/replyStructure.ts` matches exactly two things — a blank line, and a
leading `"- "` — and no digit, `₹` or percent sign anywhere. Every string it emits
is a substring of the string it was given. Three tests hold that line: two compare
the emitted fragments against the input, and one extracts every `[₹0-9.,%&]`
character from the rendered DOM and requires it to be identical to the reply.

Turning `- ` into a real `<li>` is presentation — same characters, better
structure, and a screen reader can navigate a result as a list. Pulling
`₹6,22,245.30` out of a sentence to render it in a different weight would not be:
that is a second implementation of the money rules, in a second language, and the
two would eventually disagree about a rounding case.

The API contract is unchanged for the same reason. `POST /session` and
`POST /chat` both return `{session_id, reply}` with `reply` a plain string — no
structured result, no field list, no pre-split figures. A frontend that needed
those would be a frontend asking to do arithmetic.

---

## Structure

```
src/
  api/client.ts          typed fetch; the only module that knows the server exists
  api/types.ts           the {session_id, reply} contract
  hooks/useConversation  all session state: turns, status, failures. No component fetches.
  lib/replyStructure.ts  pure: text -> paragraphs and list items. Touches no value.
  lib/calculators.ts     pure: greeting -> chip labels
  components/            props in, DOM out. Transcript, Turn, ReplyBody,
                         Composer, CalculatorChips, ThinkingIndicator, Notice
  App.tsx                composition, plus the one piece of view state: the draft
  styles.css             both themes, one measure, one focus ring
```

Failures are separated by what the user should do about them, the same reasoning
`backend/chat/llm.py` applies to provider errors: `NetworkError`,
`UnknownSessionError`, `ServerError` and `MalformedReplyError` are distinct
because "the server is not running" is worth retrying and "this conversation is
gone" never is.

There is no mirror of the backend's state machine here. `COLLECTING` and
`CONFIRMING` live in `chat/session.py`; the server decides what to ask next and
says so in the reply. This tracks only what a browser has to — is a request in
flight, and did the last one fail.

---

## Design

- **Conversation, not chat bubbles.** Turns are separated by a rule and a small
  caps speaker label. A result is a short table of amounts, and a tinted rounded
  rectangle is a worse place to read one than a plain column is.
- **One 65ch measure** and `font-variant-numeric: tabular-nums` on the whole
  transcript, so figures align vertically down the page. For a screen full of
  currency that is the single most useful typographic decision available.
- **Both themes chosen, not inverted.** The dark background is a warm near-black,
  and the accent lightens for it, because `#1f4b7a` has 9:1 contrast on white and
  2:1 on charcoal. Every pair clears WCAG AA.
- **Real states.** The field is disabled with a "Working that out" indicator while
  a request is in flight; live replies take one to four seconds. A fetch failure
  and a 404 unknown session get different messages, and neither leaves a dead
  input without an explanation and a way out beside it.
- **Chips derived from the greeting**, not hard-coded, so they inherit the
  property that `chat/prompts.py` builds that list from the calculator registry.
  Add a fourth calculator in Python and a fourth chip appears. Each sends its
  label as an ordinary message on the ordinary endpoint — no new route, no
  special case.
- **Accessibility.** Keyboard-only end to end, one `:focus-visible` ring never
  removed, `role="log"` with `aria-live="polite"` and `aria-busy` on the
  transcript, a real `<label>` for the input, and `prefers-reduced-motion`
  honoured. Responsive to 360px with no horizontal scroll.
- **No external request.** System font stack, no CDN, no analytics. Asserted from
  Python, against the committed artifact, in `backend/tests/test_ui_build.py`.

---

## Tests

```bash
npm test
```

44 tests over four files: the hook's send/receive cycle and every error path, the
structure parser against real captured replies, what reaches the DOM, and the
keyboard interactions end to end.

Two of them are regressions worth naming, because both shipped bugs that the
suite as it then stood could not see — each was found by booting the *built*
bundle outside a browser:

- **The scroll-into-view effect used to call the method unguarded.** Where a DOM
  does not provide `scrollIntoView`, the effect threw, React unwound the tree, and
  the page rendered completely empty. A stub in `vitest.setup.ts` had been hiding
  exactly that. The stub is gone, the call is guarded, and a test deletes the
  method and asserts the transcript still renders.
- **The API client was built as a default parameter**, so it was rebuilt on every
  render, which changed the mount effect's identity, which opened another session
  — forever. The built page stacked 84 copies of the greeting. Every test injected
  a stable stub, so none of them ran the path a browser runs. There is now one
  that renders the hook with no client at all and asserts a single `/session`
  call.
