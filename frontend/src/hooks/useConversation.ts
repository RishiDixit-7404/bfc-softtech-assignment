/**
 * All of the conversation's state, in one place.
 *
 * Components below this take props and render them. This hook is the only
 * thing that holds a session id, the only thing that calls the API, and the
 * only thing that decides whether the composer is usable - so the rule about
 * when a user can type is one rule in one file, not a condition repeated in
 * three components.
 *
 * The state machine on the Python side lives in `chat/session.py` and this
 * knows nothing about it. There is no mirror of `COLLECTING` or `CONFIRMING`
 * here, and there must not be: the server decides what to ask next and says so
 * in the reply. This tracks only what a browser has to - is a request in
 * flight, and did the last one fail.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  type ChatApi,
  NetworkError,
  UnknownSessionError,
  createChatApi,
} from "../api/client";
import { calculatorNamesFrom } from "../lib/calculators";

export type Speaker = "user" | "bot";

export interface Turn {
  readonly id: number;
  readonly speaker: Speaker;
  readonly text: string;
}

/**
 * `starting` - opening the session, nothing on screen yet
 * `ready`    - waiting for the user
 * `sending`  - a request is in flight
 * `lost`     - the session is gone; only starting over can help
 */
export type Status = "starting" | "ready" | "sending" | "lost";

export interface Problem {
  /** `transient` is worth retrying; `lost` is not. */
  readonly kind: "transient" | "lost";
  readonly message: string;
}

export interface Conversation {
  readonly turns: readonly Turn[];
  readonly status: Status;
  readonly problem: Problem | null;
  /** The three calculators, taken from the greeting. Empty until it arrives. */
  readonly calculators: readonly string[];
  readonly canSend: boolean;
  send: (message: string) => void;
  restart: () => void;
  dismissProblem: () => void;
}

const RETRY_HINT = "Try that again, or start a new conversation.";

const LOST_SESSION_MESSAGE =
  "This conversation is no longer on the server - it restarts when the server " +
  "does, and nothing is kept between runs. Start a new one to carry on.";

function describe(error: unknown): Problem {
  if (error instanceof UnknownSessionError) {
    return { kind: "lost", message: LOST_SESSION_MESSAGE };
  }
  if (error instanceof NetworkError) {
    return {
      kind: "transient",
      message: `The server is not responding. Check that it is running. ${RETRY_HINT}`,
    };
  }
  if (error instanceof Error) {
    return { kind: "transient", message: `${error.message} ${RETRY_HINT}` };
  }
  return { kind: "transient", message: `Something went wrong. ${RETRY_HINT}` };
}

export function useConversation(api?: ChatApi): Conversation {
  // Memoised, and this is load-bearing. As a default *parameter*
  // - `api: ChatApi = createChatApi()` - a fresh client was built on every
  // render, which gave `open` a new identity, which re-ran the mount effect,
  // which opened another session and appended another greeting, forever. It
  // never showed up in a test because every test injects a stable stub, and it
  // was found by booting the built bundle with no `api` at all.
  const client = useMemo(() => api ?? createChatApi(), [api]);

  const [turns, setTurns] = useState<readonly Turn[]>([]);
  const [status, setStatus] = useState<Status>("starting");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [calculators, setCalculators] = useState<readonly string[]>([]);

  const sessionId = useRef<string | null>(null);
  const nextId = useRef(0);
  // Set on unmount, and on restart, so a reply that arrives late cannot write
  // into a conversation the user has already replaced.
  const generation = useRef(0);

  const append = useCallback((speaker: Speaker, text: string): void => {
    setTurns((current) => [...current, { id: nextId.current++, speaker, text }]);
  }, []);

  const open = useCallback(
    async (mine: number): Promise<void> => {
      setStatus("starting");
      setProblem(null);
      try {
        const opened = await client.openSession();
        if (generation.current !== mine) return;

        sessionId.current = opened.session_id;
        setCalculators(calculatorNamesFrom(opened.reply));
        append("bot", opened.reply);
        setStatus("ready");
      } catch (error) {
        if (generation.current !== mine) return;
        // Nothing was opened, so there is no session to lose - whatever the
        // cause, the recovery is the same and it is worth retrying.
        setProblem({ ...describe(error), kind: "transient" });
        setStatus("ready");
      }
    },
    [client, append],
  );

  useEffect(() => {
    const mine = generation.current;
    void open(mine);
    return () => {
      generation.current += 1;
    };
  }, [open]);

  const send = useCallback(
    (message: string): void => {
      const text = message.trim();
      if (text === "" || status === "sending" || status === "lost") return;

      const id = sessionId.current;
      if (id === null) {
        setProblem({
          kind: "transient",
          message: `There is no conversation open yet. ${RETRY_HINT}`,
        });
        return;
      }

      const mine = generation.current;
      append("user", text);
      setStatus("sending");
      setProblem(null);

      void (async () => {
        try {
          const answered = await client.send(id, text);
          if (generation.current !== mine) return;
          append("bot", answered.reply);
          setStatus("ready");
        } catch (error) {
          if (generation.current !== mine) return;
          const trouble = describe(error);
          setProblem(trouble);
          // The user's own words stay on screen either way. Losing what
          // somebody just typed because a request failed is its own bug.
          setStatus(trouble.kind === "lost" ? "lost" : "ready");
        }
      })();
    },
    [client, append, status],
  );

  const restart = useCallback((): void => {
    generation.current += 1;
    sessionId.current = null;
    setTurns([]);
    setCalculators([]);
    void open(generation.current);
  }, [open]);

  const dismissProblem = useCallback((): void => setProblem(null), []);

  return {
    turns,
    status,
    problem,
    calculators,
    canSend: status === "ready",
    send,
    restart,
    dismissProblem,
  };
}
