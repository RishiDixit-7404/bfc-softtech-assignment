/**
 * The calculator names, taken from the greeting the server actually sent.
 *
 * The greeting lists the three calculators, and `chat/prompts.py` builds that
 * list from the calculator registry so it cannot advertise one that does not
 * exist. Deriving the chips from the same sentence inherits that property: add
 * a fourth calculator on the Python side and a fourth chip appears, with
 * nothing here to update. Hard-coding three labels in TypeScript would put a
 * copy of the registry in a second language, and the copy would go stale.
 *
 * A chip sends its label as an ordinary message on the ordinary /chat
 * endpoint. There is no new route and no special case - it is a shortcut for
 * typing, which is all a chip should ever be.
 */

import { parseReply } from "./replyStructure";

/** Separates a calculator's name from its blurb in the greeting. */
const NAME_BLURB_SEPARATOR = " - ";

/**
 * Names from the first list in `greeting`, or an empty array if it has none.
 *
 * Empty is a normal outcome, not an error: a reply that is not the greeting
 * has no such list, and the caller simply renders no chips.
 */
export function calculatorNamesFrom(greeting: string): string[] {
  const firstList = parseReply(greeting).find((block) => block.kind === "list");
  if (firstList === undefined) return [];

  return firstList.items
    .map((item) => {
      const end = item.indexOf(NAME_BLURB_SEPARATOR);
      return (end === -1 ? item : item.slice(0, end)).trim();
    })
    .filter((name) => name !== "");
}
