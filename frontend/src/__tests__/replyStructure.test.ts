/**
 * The structure parser, and the guarantee that matters most about it.
 *
 * The fixtures are real replies, copied from the running server, so the shapes
 * asserted here are the shapes that actually arrive.
 */

import { describe, expect, it } from "vitest";

import { parseReply, type Block } from "../lib/replyStructure";

const GREETING = `I can talk through personal finance - saving, borrowing, investing - and I can run three calculators for you:
- Loan tenure - how long a loan takes to clear, from the amount, EMI and rate
- SIP for a target amount - the monthly investment needed to reach a goal in a given time
- SWP (systematic withdrawals) - how a lumpsum holds up while you withdraw from it every month

Where would you like to start?`;

const CONFIRMATION = `Here is what I have:
- loan amount: ₹5,00,000.00
- EMI: ₹10,000.00
- annual interest rate: 9%

Shall I run the loan tenure calculation with those?`;

const RESULT = `That loan is cleared in 5 years & 3 months.
- Payments: 63, rounded up from 62.22 months - the last month is a part payment, not a whole EMI.
- Final instalment: ₹2,245.30.
- Total repaid: ₹6,22,245.30.

Anything else I can work out?`;

const DEPLETED = `Withdrawing ₹6,000.00 a month exhausts ₹3,00,000.00 in month 61 of 120 - that is year 6, month 1.
- Actually withdrawn before it ran dry: ₹3,63,150.66, the final month being a part withdrawal.
- Total withdrawn if the plan had run its 120 months: ₹7,20,000.00. That is the figure the formula reports, and the corpus cannot fund it.
- To make the term reachable: lower the withdrawal, shorten the plan, or start with more.

Anything else I can work out?`;

const REAL_REPLIES = { GREETING, CONFIRMATION, RESULT, DEPLETED };

function textOf(blocks: readonly Block[]): string[] {
  return blocks.flatMap((block) =>
    block.kind === "list" ? [...block.items] : [...block.lines],
  );
}

describe("parseReply", () => {
  it("splits a reply into its paragraphs and lists", () => {
    expect(parseReply(CONFIRMATION)).toEqual([
      { kind: "paragraph", lines: ["Here is what I have:"] },
      {
        kind: "list",
        items: [
          "loan amount: ₹5,00,000.00",
          "EMI: ₹10,000.00",
          "annual interest rate: 9%",
        ],
      },
      {
        kind: "paragraph",
        lines: ["Shall I run the loan tenure calculation with those?"],
      },
    ]);
  });

  it("keeps a dash inside an item, and strips only the leading marker", () => {
    const [, list] = parseReply(GREETING);

    expect(list).toEqual({
      kind: "list",
      items: [
        "Loan tenure - how long a loan takes to clear, from the amount, EMI and rate",
        "SIP for a target amount - the monthly investment needed to reach a goal in a given time",
        "SWP (systematic withdrawals) - how a lumpsum holds up while you withdraw from it every month",
      ],
    });
  });

  it("treats a single blank-line-free reply as one paragraph", () => {
    expect(parseReply("How much is the loan?")).toEqual([
      { kind: "paragraph", lines: ["How much is the loan?"] },
    ]);
  });

  it("keeps consecutive non-bullet lines together as one paragraph", () => {
    expect(parseReply("First line\nSecond line")).toEqual([
      { kind: "paragraph", lines: ["First line", "Second line"] },
    ]);
  });

  it("returns nothing for an empty or whitespace-only reply", () => {
    expect(parseReply("")).toEqual([]);
    expect(parseReply("   \n\n  ")).toEqual([]);
  });

  // The load-bearing property. If this ever fails, the frontend has started
  // having an opinion about the text - which for a reply full of rupee figures
  // means having an opinion about money.
  describe.each(Object.entries(REAL_REPLIES))(
    "leaves %s untouched",
    (_name, reply) => {
      it("emits only substrings of the reply", () => {
        for (const fragment of textOf(parseReply(reply))) {
          expect(reply).toContain(fragment);
        }
      });

      it("keeps every digit, rupee sign and separator the server sent", () => {
        const figures = /[₹0-9.,%&]/g;
        const before = reply.match(figures)?.join("") ?? "";
        // "- " markers carry no figure characters, so the two must match exactly.
        const after = textOf(parseReply(reply)).join("").match(figures)?.join("") ?? "";

        expect(after).toBe(before);
      });
    },
  );
});
