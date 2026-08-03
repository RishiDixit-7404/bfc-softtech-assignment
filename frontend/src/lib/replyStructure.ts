/**
 * Reading the *shape* of a reply, and nothing else.
 *
 * The server sends plain text with a consistent structure: blocks separated by
 * a blank line, and within a block, lines that begin with "- " are list items.
 * That is the whole grammar. Turning it into paragraphs and a real <ul> is
 * presentation - the same words, laid out so they can be scanned.
 *
 * What this module deliberately does not do is look at any *value*. It never
 * matches a ₹, a digit, a percent sign or a date; it never rounds, regroups or
 * reformats. `chat/formatting.py` produced every number in the string and is
 * the only thing in the system allowed to decide how one looks. A frontend that
 * pulled "₹6,22,245.30" out of a sentence to restyle it would be a second
 * opinion about money, and there is only ever one.
 *
 * The consequence worth noticing: the strings that come out of here are always
 * substrings of the string that went in, minus a leading "- " and surrounding
 * whitespace. A test asserts exactly that.
 */

/** A run of lines that belong together. */
export type Block =
  | { readonly kind: "paragraph"; readonly lines: readonly string[] }
  | { readonly kind: "list"; readonly items: readonly string[] };

/** The only markup the server emits: a list item marker at the start of a line. */
const BULLET = "- ";

/** A blank line, or a line of nothing but whitespace, separates blocks. */
const BLOCK_BREAK = /\n[ \t]*\n/;

function isBullet(line: string): boolean {
  return line.startsWith(BULLET);
}

/**
 * Strip the marker, and only the marker.
 *
 * Note that bullets contain " - " inside them - "Loan tenure - how long a loan
 * takes to clear" - so only a *leading* marker counts. Splitting on every " - "
 * would quietly cut sentences in half.
 */
function withoutBullet(line: string): string {
  return line.slice(BULLET.length).trim();
}

function parseBlock(chunk: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];

  const flush = (): void => {
    if (paragraph.length > 0) {
      blocks.push({ kind: "paragraph", lines: paragraph });
      paragraph = [];
    }
    if (list.length > 0) {
      blocks.push({ kind: "list", items: list });
      list = [];
    }
  };

  for (const raw of chunk.split("\n")) {
    const line = raw.trimEnd();
    if (line.trim() === "") continue;

    if (isBullet(line.trimStart())) {
      if (paragraph.length > 0) flush();
      list.push(withoutBullet(line.trimStart()));
    } else {
      if (list.length > 0) flush();
      paragraph.push(line.trim());
    }
  }

  flush();
  return blocks;
}

/**
 * Split a reply into the blocks it is already made of.
 *
 * Returns an empty array for an empty or whitespace-only reply, which the
 * caller renders as nothing rather than as an empty bubble.
 */
export function parseReply(text: string): Block[] {
  if (text.trim() === "") return [];
  return text.split(BLOCK_BREAK).flatMap(parseBlock);
}
