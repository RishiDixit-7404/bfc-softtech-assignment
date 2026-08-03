/**
 * What reaches the DOM.
 *
 * Two things are being checked. That the reply's structure becomes real
 * structure - paragraphs, a list, list items - so it can be scanned and
 * navigated by a screen reader. And that not one character of a figure changes
 * on the way, which is the constraint the whole frontend is built around.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Transcript } from "../components/Transcript";
import type { Turn } from "../hooks/useConversation";

const RESULT = `That loan is cleared in 5 years & 3 months.
- Payments: 63, rounded up from 62.22 months - the last month is a part payment, not a whole EMI.
- Final instalment: ₹2,245.30.
- Total repaid: ₹6,22,245.30.

Anything else I can work out?`;

function turns(...texts: [Turn["speaker"], string][]): Turn[] {
  return texts.map(([speaker, text], id) => ({ id, speaker, text }));
}

describe("Transcript", () => {
  it("renders a reply's bullets as a real list", () => {
    render(<Transcript turns={turns(["bot", RESULT])} thinking={false} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent(/^Payments: 63, rounded up from 62\.22 months/);
  });

  it("renders the amounts exactly as the server grouped them", () => {
    render(<Transcript turns={turns(["bot", RESULT])} thinking={false} />);

    // Indian grouping, two decimals, rupee sign - all of it the server's work.
    expect(screen.getByText(/₹6,22,245\.30/)).toBeInTheDocument();
    expect(screen.getByText(/₹2,245\.30/)).toBeInTheDocument();
  });

  it("changes no character of the reply's figures", () => {
    const { container } = render(
      <Transcript turns={turns(["bot", RESULT])} thinking={false} />,
    );

    const figures = /[₹0-9.,%&]/g;
    const rendered = container.textContent ?? "";

    expect(rendered.match(figures)?.join("")).toBe(RESULT.match(figures)?.join(""));
    // And specifically: no reformatting into 622245.3, 622,245.30 or 6.22 lakh.
    expect(rendered).not.toMatch(/622245/);
    expect(rendered).not.toMatch(/622,245/);
  });

  it("keeps the marker out of the rendered text", () => {
    render(<Transcript turns={turns(["bot", RESULT])} thinking={false} />);

    for (const item of screen.getAllByRole("listitem")) {
      expect(item.textContent?.startsWith("- ")).toBe(false);
    }
  });

  it("labels each turn with who said it", () => {
    render(<Transcript turns={turns(["bot", "Hello"], ["user", "5 lakh"])} thinking={false} />);

    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("5 lakh")).toBeInTheDocument();
  });

  it("is an aria-live log so a new reply is announced", () => {
    render(<Transcript turns={turns(["bot", "Hello"])} thinking={false} />);
    const log = screen.getByRole("log", { name: "Conversation" });

    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("aria-relevant", "additions");
    expect(log).toHaveAttribute("aria-busy", "false");
  });

  it("shows a thinking indicator and marks the log busy while waiting", () => {
    render(<Transcript turns={turns(["user", "5 lakh"])} thinking={true} />);

    expect(screen.getByRole("status")).toHaveTextContent("Working that out");
    expect(screen.getByRole("log")).toHaveAttribute("aria-busy", "true");
  });

  // Regression. The scroll-into-view effect used to call the method
  // unguarded; where the DOM does not provide it the effect threw, React
  // unwound the tree, and the page rendered completely empty. Found by booting
  // the committed bundle outside a browser, not by any test that existed then.
  it("still renders when the DOM has no scrollIntoView", () => {
    const original = window.HTMLElement.prototype.scrollIntoView;
    // @ts-expect-error - removing it is the whole point of the test
    delete window.HTMLElement.prototype.scrollIntoView;

    try {
      render(<Transcript turns={turns(["bot", RESULT])} thinking={false} />);
      expect(screen.getByRole("log")).toBeInTheDocument();
      expect(screen.getAllByRole("listitem")).toHaveLength(3);
    } finally {
      if (original !== undefined) {
        window.HTMLElement.prototype.scrollIntoView = original;
      }
    }
  });

  it("does not treat the bot's echo of user text as markup", () => {
    const hostile = "Here is what I have:\n- loan amount: <img src=x onerror=alert(1)>";
    const { container } = render(
      <Transcript turns={turns(["bot", hostile])} thinking={false} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("listitem")).toHaveTextContent(
      "loan amount: <img src=x onerror=alert(1)>",
    );
  });
});
