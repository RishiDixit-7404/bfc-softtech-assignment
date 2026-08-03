/**
 * The conversation so far.
 *
 * `role="log"` with `aria-live="polite"` announces new turns without
 * interrupting whatever a screen reader is already saying, and
 * `aria-relevant="additions"` keeps it from re-reading the whole history each
 * time one arrives. `aria-busy` while a request is in flight tells assistive
 * technology that more is coming.
 *
 * The newest turn is scrolled into view by an anchor element after the list,
 * rather than by setting scrollTop, so the browser handles the smooth-versus-
 * instant decision from the user's own motion preference.
 *
 * That scroll is guarded on the *method*, not just the ref. An exception thrown
 * from an effect is not contained to the effect - React unwinds the tree and
 * the page renders empty - so keeping the newest message in view must never be
 * able to cost the whole transcript. Every browser has `scrollIntoView`; test
 * DOMs and older embedded webviews do not, and a blank page is a bad trade for
 * a convenience.
 */

import { useEffect, useRef } from "react";

import type { Turn as TurnModel } from "../hooks/useConversation";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { Turn } from "./Turn";

interface TranscriptProps {
  turns: readonly TurnModel[];
  thinking: boolean;
}

export function Transcript({ turns, thinking }: TranscriptProps) {
  const anchor = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const target = anchor.current;
    if (typeof target?.scrollIntoView === "function") {
      target.scrollIntoView({ block: "end" });
    }
  }, [turns.length, thinking]);

  return (
    <div
      className="transcript"
      role="log"
      aria-label="Conversation"
      aria-live="polite"
      aria-relevant="additions"
      aria-busy={thinking}
    >
      <div className="transcript__measure">
        {turns.map((turn) => (
          <Turn key={turn.id} turn={turn} />
        ))}
        {thinking && <ThinkingIndicator />}
        <div className="transcript__anchor" ref={anchor} aria-hidden="true" />
      </div>
    </div>
  );
}
