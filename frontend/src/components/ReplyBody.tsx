/**
 * A bot reply, laid out as the structure it already has.
 *
 * Every string reaching a DOM node here is a substring of the reply. React
 * escapes text children, so the bot echoing a user's own words back - which it
 * does, at the confirmation step - cannot become markup.
 */

import { parseReply } from "../lib/replyStructure";

export function ReplyBody({ text }: { text: string }) {
  const blocks = parseReply(text);

  return (
    <>
      {blocks.map((block, index) =>
        block.kind === "list" ? (
          <ul className="reply-list" key={index}>
            {block.items.map((item, position) => (
              <li key={position}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="reply-paragraph" key={index}>
            {block.lines.map((line, position) => (
              <span key={position}>
                {position > 0 && <br />}
                {line}
              </span>
            ))}
          </p>
        ),
      )}
    </>
  );
}
