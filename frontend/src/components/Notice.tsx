/**
 * Something went wrong, said plainly, with the way out attached.
 *
 * Two rules. It never appears without an action - a dead input and no
 * explanation is the failure this component exists to prevent. And it is not
 * a turn: putting an error in the transcript would make it look like the bot
 * said it, which invites the user to reply to it.
 */

import type { Problem } from "../hooks/useConversation";

interface NoticeProps {
  problem: Problem;
  onRestart: () => void;
  onDismiss: () => void;
}

export function Notice({ problem, onRestart, onDismiss }: NoticeProps) {
  return (
    <div className="notice" role="alert">
      <p className="notice__message">{problem.message}</p>
      <div className="notice__actions">
        <button className="button button--quiet" type="button" onClick={onRestart}>
          Start a new conversation
        </button>
        {problem.kind === "transient" && (
          <button className="button button--plain" type="button" onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}
