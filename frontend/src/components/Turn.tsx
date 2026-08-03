/**
 * One turn of the conversation.
 *
 * Not a bubble. Turns are told apart by a small caps label and, for the user,
 * a rule down the left edge - enough to scan who said what without wrapping
 * every sentence in a coloured box. Replies here are structured text with
 * figures in them, and a tinted rounded rectangle is a worse place to read a
 * table of amounts than a plain column is.
 */

import type { Turn as TurnModel } from "../hooks/useConversation";
import { ReplyBody } from "./ReplyBody";

const SPEAKER_LABEL: Record<TurnModel["speaker"], string> = {
  user: "You",
  bot: "Assistant",
};

export function Turn({ turn }: { turn: TurnModel }) {
  return (
    <article className={`turn turn--${turn.speaker}`}>
      <h2 className="turn__speaker">{SPEAKER_LABEL[turn.speaker]}</h2>
      <div className="turn__body">
        {turn.speaker === "bot" ? (
          <ReplyBody text={turn.text} />
        ) : (
          <p className="reply-paragraph">{turn.text}</p>
        )}
      </div>
    </article>
  );
}
