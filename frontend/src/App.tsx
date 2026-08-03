/**
 * Composition, and the one piece of state that is genuinely the view's own:
 * what is currently typed in the box.
 *
 * Everything else - turns, session, status, failures - belongs to
 * `useConversation`. This file wires it to components and holds no logic worth
 * testing on its own, which is the intent.
 */

import { useCallback, useState } from "react";

import type { ChatApi } from "./api/client";
import { CalculatorChips } from "./components/CalculatorChips";
import { Composer } from "./components/Composer";
import { Notice } from "./components/Notice";
import { Transcript } from "./components/Transcript";
import { useConversation } from "./hooks/useConversation";

/** `api` is injected by tests. In the browser the default client is used. */
interface AppProps {
  api?: ChatApi;
}

export function App({ api }: AppProps = {}) {
  const conversation = useConversation(api);
  const [draft, setDraft] = useState("");
  const [focusSignal, setFocusSignal] = useState(0);

  const submit = useCallback(
    (text: string): void => {
      if (!conversation.canSend || text.trim() === "") return;
      conversation.send(text);
      setDraft("");
      setFocusSignal((count) => count + 1);
    },
    [conversation],
  );

  const busy = conversation.status === "sending" || conversation.status === "starting";

  return (
    <div className="shell">
      <header className="masthead">
        <div className="masthead__measure">
          <p className="masthead__title">Personal finance assistant</p>
          <p className="masthead__subtitle">
            Loan tenure, SIP and SWP, worked out one question at a time.
          </p>
        </div>
      </header>

      <main className="main">
        <Transcript turns={conversation.turns} thinking={busy} />
      </main>

      <footer className="footer">
        <div className="footer__measure">
          {conversation.problem !== null && (
            <Notice
              problem={conversation.problem}
              onRestart={conversation.restart}
              onDismiss={conversation.dismissProblem}
            />
          )}

          {conversation.turns.length <= 1 && (
            <CalculatorChips
              names={conversation.calculators}
              disabled={!conversation.canSend}
              onChoose={submit}
            />
          )}
        </div>

        <Composer
          value={draft}
          disabled={!conversation.canSend}
          onChange={setDraft}
          onSubmit={() => submit(draft)}
          focusSignal={focusSignal}
        />
      </footer>
    </div>
  );
}
