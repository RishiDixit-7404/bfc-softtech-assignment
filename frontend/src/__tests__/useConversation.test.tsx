/**
 * The hook's send/receive cycle and every way it can fail.
 *
 * A stub `ChatApi` stands in for the server, which is the point of the client
 * being an injected interface rather than a module-level `fetch` call.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  type ChatApi,
  NetworkError,
  ServerError,
  UnknownSessionError,
} from "../api/client";
import { useConversation } from "../hooks/useConversation";

const GREETING = `I can run three calculators for you:
- Loan tenure - how long a loan takes to clear
- SIP for a target amount - the monthly investment needed
- SWP (systematic withdrawals) - how a lumpsum holds up

Where would you like to start?`;

function stubApi(overrides: Partial<ChatApi> = {}): ChatApi {
  return {
    openSession: vi.fn(async () => ({ session_id: "abc123", reply: GREETING })),
    send: vi.fn(async () => ({
      session_id: "abc123",
      reply: "How much is the loan?",
    })),
    ...overrides,
  };
}

async function readyConversation(api: ChatApi = stubApi()) {
  const rendered = renderHook(() => useConversation(api));
  await waitFor(() => expect(rendered.result.current.status).toBe("ready"));
  return rendered;
}

describe("useConversation", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // Regression, and the reason it is first. Every other test here injects a
  // stub, so none of them ever ran the path the browser runs: no `api`
  // argument at all. With the client built as a default parameter it was
  // rebuilt on every render, which changed `open`'s identity, which re-ran the
  // mount effect, which opened another session - forever. The built page
  // stacked 84 copies of the greeting before anyone looked.
  it("opens exactly one session when no client is injected", async () => {
    const fetchSpy = vi.fn(async (_path: string) => ({
      ok: true,
      status: 200,
      json: async () => ({ session_id: "real", reply: GREETING }),
    }));
    vi.stubGlobal("fetch", fetchSpy);

    const { result, rerender } = renderHook(() => useConversation());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    rerender();
    rerender();
    await waitFor(() => expect(result.current.turns).toHaveLength(1));

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0]?.[0]).toBe("/session");
  });

  it("opens a session on mount and shows the greeting", async () => {
    const api = stubApi();
    const { result } = await readyConversation(api);

    expect(api.openSession).toHaveBeenCalledTimes(1);
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0]).toMatchObject({
      speaker: "bot",
      text: GREETING,
    });
    expect(result.current.problem).toBeNull();
    expect(result.current.canSend).toBe(true);
  });

  it("takes the calculator names from the greeting", async () => {
    const { result } = await readyConversation();

    expect(result.current.calculators).toEqual([
      "Loan tenure",
      "SIP for a target amount",
      "SWP (systematic withdrawals)",
    ]);
  });

  it("shows the user's turn immediately and the reply when it arrives", async () => {
    const api = stubApi();
    const { result } = await readyConversation(api);

    act(() => result.current.send("loan tenure"));

    // The user's own words are on screen before the server has answered.
    expect(result.current.turns.at(-1)).toMatchObject({
      speaker: "user",
      text: "loan tenure",
    });
    expect(result.current.status).toBe("sending");
    expect(result.current.canSend).toBe(false);

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(api.send).toHaveBeenCalledWith("abc123", "loan tenure");
    expect(result.current.turns.at(-1)).toMatchObject({
      speaker: "bot",
      text: "How much is the loan?",
    });
  });

  it("trims the message and ignores an empty one", async () => {
    const api = stubApi();
    const { result } = await readyConversation(api);

    act(() => result.current.send("   "));
    expect(api.send).not.toHaveBeenCalled();
    expect(result.current.turns).toHaveLength(1);

    act(() => result.current.send("  5 lakh  "));
    expect(api.send).toHaveBeenCalledWith("abc123", "5 lakh");
  });

  it("refuses a second send while one is in flight", async () => {
    const api = stubApi();
    const { result } = await readyConversation(api);

    act(() => result.current.send("first"));
    act(() => result.current.send("second"));

    expect(api.send).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  describe("failure", () => {
    it("reports an unreachable server and keeps what the user typed", async () => {
      const api = stubApi({
        send: vi.fn(async () => {
          throw new NetworkError("nope");
        }),
      });
      const { result } = await readyConversation(api);

      act(() => result.current.send("5 lakh"));
      await waitFor(() => expect(result.current.problem).not.toBeNull());

      expect(result.current.problem?.kind).toBe("transient");
      expect(result.current.problem?.message).toContain("not responding");
      expect(result.current.turns.at(-1)).toMatchObject({ text: "5 lakh" });
      // Retryable, so the composer stays usable.
      expect(result.current.canSend).toBe(true);
    });

    it("treats a 404 as a lost session and stops accepting messages", async () => {
      const api = stubApi({
        send: vi.fn(async () => {
          throw new UnknownSessionError("gone");
        }),
      });
      const { result } = await readyConversation(api);

      act(() => result.current.send("5 lakh"));
      await waitFor(() => expect(result.current.status).toBe("lost"));

      expect(result.current.problem?.kind).toBe("lost");
      expect(result.current.problem?.message).toContain("no longer on the server");
      expect(result.current.canSend).toBe(false);

      // And retrying really is refused, rather than merely discouraged.
      act(() => result.current.send("again"));
      expect(api.send).toHaveBeenCalledTimes(1);
    });

    it("reports any other status without pretending to know what it means", async () => {
      const api = stubApi({
        send: vi.fn(async () => {
          throw new ServerError(500);
        }),
      });
      const { result } = await readyConversation(api);

      act(() => result.current.send("5 lakh"));
      await waitFor(() => expect(result.current.problem).not.toBeNull());

      expect(result.current.problem?.message).toContain("HTTP 500");
      expect(result.current.problem?.kind).toBe("transient");
    });

    it("stays usable when the very first session cannot be opened", async () => {
      const api = stubApi({
        openSession: vi.fn(async () => {
          throw new NetworkError("down");
        }),
      });
      const { result } = await readyConversation(api);

      expect(result.current.problem?.kind).toBe("transient");
      expect(result.current.turns).toHaveLength(0);
    });

    it("explains rather than silently dropping a send with no session", async () => {
      const api = stubApi({
        openSession: vi.fn(async () => {
          throw new NetworkError("down");
        }),
      });
      const { result } = await readyConversation(api);

      act(() => result.current.send("hello"));

      expect(api.send).not.toHaveBeenCalled();
      expect(result.current.problem?.message).toContain("no conversation open");
    });
  });

  describe("restart", () => {
    it("opens a fresh session and clears the transcript", async () => {
      const api = stubApi({
        send: vi.fn(async () => {
          throw new UnknownSessionError("gone");
        }),
      });
      const { result } = await readyConversation(api);

      act(() => result.current.send("5 lakh"));
      await waitFor(() => expect(result.current.status).toBe("lost"));

      act(() => result.current.restart());
      await waitFor(() => expect(result.current.status).toBe("ready"));

      expect(api.openSession).toHaveBeenCalledTimes(2);
      expect(result.current.turns).toHaveLength(1);
      expect(result.current.turns[0]).toMatchObject({ speaker: "bot" });
      expect(result.current.problem).toBeNull();
      expect(result.current.canSend).toBe(true);
    });
  });

  it("dismisses a transient problem without touching the transcript", async () => {
    const api = stubApi({
      send: vi.fn(async () => {
        throw new NetworkError("nope");
      }),
    });
    const { result } = await readyConversation(api);

    act(() => result.current.send("5 lakh"));
    await waitFor(() => expect(result.current.problem).not.toBeNull());

    act(() => result.current.dismissProblem());

    expect(result.current.problem).toBeNull();
    expect(result.current.turns).toHaveLength(2);
  });
});
