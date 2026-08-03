/**
 * The interactions a keyboard user actually performs.
 *
 * Driven through the real components with a stub API, so the wiring between
 * the hook and the composer is exercised rather than described.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { type ChatApi, UnknownSessionError } from "../api/client";
import type { ConversationReply } from "../api/types";

const GREETING = `I can run three calculators for you:
- Loan tenure - how long a loan takes to clear
- SIP for a target amount - the monthly investment needed
- SWP (systematic withdrawals) - how a lumpsum holds up

Where would you like to start?`;

function stubApi(overrides: Partial<ChatApi> = {}): ChatApi {
  return {
    openSession: vi.fn(async () => ({ session_id: "s1", reply: GREETING })),
    send: vi.fn(async (_id: string, message: string) => ({
      session_id: "s1",
      reply: `You said: ${message}`,
    })),
    ...overrides,
  };
}

async function mounted(api: ChatApi = stubApi()) {
  const user = userEvent.setup();
  render(<App api={api} />);
  await screen.findByText(/Where would you like to start/);
  return { user, api };
}

describe("App", () => {
  it("sends on Enter and clears the field", async () => {
    const { user, api } = await mounted();
    const field = screen.getByLabelText("Your message");

    await user.type(field, "loan tenure{Enter}");

    await waitFor(() => expect(api.send).toHaveBeenCalledWith("s1", "loan tenure"));
    expect(field).toHaveValue("");
    await screen.findByText("You said: loan tenure");
  });

  it("inserts a newline on Shift+Enter instead of sending", async () => {
    const { user, api } = await mounted();
    const field = screen.getByLabelText("Your message");

    await user.type(field, "first{Shift>}{Enter}{/Shift}second");

    expect(api.send).not.toHaveBeenCalled();
    expect(field).toHaveValue("first\nsecond");
  });

  it("returns focus to the field after sending", async () => {
    const { user } = await mounted();
    const field = screen.getByLabelText("Your message");

    await user.type(field, "hello{Enter}");
    await screen.findByText("You said: hello");

    expect(field).toHaveFocus();
  });

  it("disables the field while a reply is in flight", async () => {
    let release: (() => void) | undefined;
    const api = stubApi({
      send: vi.fn(
        () =>
          new Promise<ConversationReply>((resolve) => {
            release = () => resolve({ session_id: "s1", reply: "done" });
          }),
      ),
    });
    const { user } = await mounted(api);
    const field = screen.getByLabelText("Your message");

    await user.type(field, "hello{Enter}");

    expect(field).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Working that out");

    release?.();
    await screen.findByText("done");
    expect(field).toBeEnabled();
  });

  it("offers the calculators as buttons that send their own label", async () => {
    const { user, api } = await mounted();

    await user.click(screen.getByRole("button", { name: "Loan tenure" }));

    expect(api.send).toHaveBeenCalledWith("s1", "Loan tenure");
  });

  it("hides the chips once the conversation is under way", async () => {
    const { user } = await mounted();

    expect(screen.getByRole("button", { name: "Loan tenure" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Loan tenure" }));
    await screen.findByText("You said: Loan tenure");

    expect(screen.queryByRole("button", { name: "Loan tenure" })).toBeNull();
  });

  it("explains a lost session and offers a way back", async () => {
    const api = stubApi({
      send: vi.fn(async () => {
        throw new UnknownSessionError("gone");
      }),
    });
    const { user } = await mounted(api);

    await user.type(screen.getByLabelText("Your message"), "hello{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/no longer on the server/);
    // Never a dead input with no explanation: the field is disabled, and the
    // thing to do about it is on screen next to the reason.
    expect(screen.getByLabelText("Your message")).toBeDisabled();

    const restart = screen.getByRole("button", { name: "Start a new conversation" });
    await user.click(restart);

    await waitFor(() => expect(api.openSession).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText("Your message")).toBeEnabled();
  });

  it("puts focus in the field on load, so typing needs no click", async () => {
    await mounted();

    expect(screen.getByLabelText("Your message")).toHaveFocus();
  });

  it("can be driven with the keyboard alone from the greeting to a reply", async () => {
    const { user, api } = await mounted();
    const chip = screen.getByRole("button", { name: "Loan tenure" });

    // Walk the tab order rather than assuming a position. The bound is what
    // makes an unreachable chip fail the test instead of hanging it.
    for (let step = 0; step < 8 && document.activeElement !== chip; step += 1) {
      await user.tab();
    }
    expect(chip).toHaveFocus();

    await user.keyboard("{Enter}");
    await waitFor(() => expect(api.send).toHaveBeenCalledWith("s1", "Loan tenure"));
    await screen.findByText("You said: Loan tenure");
  });
});
