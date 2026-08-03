/**
 * The only module that knows the server exists.
 *
 * Components receive props; the hook receives this. Nothing in `components/`
 * calls `fetch`, which is what makes every one of them renderable from a
 * literal in a test.
 *
 * Failures are separated by what the user should do about them, the same
 * reasoning `chat/llm.py` applies to provider errors. "The server is not
 * running" and "this conversation is gone" both leave the input unusable, but
 * one is fixed by retrying and the other never is, so they cannot share a
 * message.
 */

import type { ConversationReply } from "./types";

/** Base for anything this module raises. Callers catch this. */
export class ApiError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = new.target.name;
  }
}

/** The request never reached a server, or the server never answered. */
export class NetworkError extends ApiError {}

/** HTTP 404: the session id is not one the server is holding. Retrying cannot help. */
export class UnknownSessionError extends ApiError {}

/** Any other non-2xx. Carries the status for the message, not for branching. */
export class ServerError extends ApiError {
  readonly status: number;

  constructor(status: number) {
    super(`The server answered with HTTP ${status}.`);
    this.status = status;
  }
}

/** A 2xx body that is not the documented shape. */
export class MalformedReplyError extends ApiError {}

export interface ChatApi {
  /** Start a conversation. Resolves with its id and its opening message. */
  openSession(): Promise<ConversationReply>;
  /** Send one message to an existing conversation. */
  send(sessionId: string, message: string): Promise<ConversationReply>;
}

type FetchLike = typeof globalThis.fetch;

/**
 * Check the body is the contract before handing it to the UI.
 *
 * A missing field would otherwise surface as `undefined` rendered into the
 * transcript, which looks like the bot said nothing rather than like a bug.
 */
function asConversationReply(body: unknown): ConversationReply {
  if (typeof body !== "object" || body === null) {
    throw new MalformedReplyError("The server's reply was not an object.");
  }

  const { session_id: sessionId, reply } = body as Record<string, unknown>;
  if (typeof sessionId !== "string" || typeof reply !== "string") {
    throw new MalformedReplyError(
      "The server's reply did not carry a session id and a message.",
    );
  }

  return { session_id: sessionId, reply };
}

export function createChatApi(fetchImpl: FetchLike = globalThis.fetch): ChatApi {
  async function post(path: string, body: unknown): Promise<ConversationReply> {
    let response: Response;
    try {
      response = await fetchImpl(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (cause) {
      // fetch rejects only for transport failures; an HTTP error is a
      // resolved response and is handled below.
      throw new NetworkError("The server could not be reached.", { cause });
    }

    if (response.status === 404) {
      throw new UnknownSessionError("The server is not holding that conversation.");
    }
    if (!response.ok) {
      throw new ServerError(response.status);
    }

    try {
      return asConversationReply(await response.json());
    } catch (cause) {
      if (cause instanceof MalformedReplyError) throw cause;
      throw new MalformedReplyError("The server's reply was not valid JSON.");
    }
  }

  return {
    openSession: () => post("/session", {}),
    send: (sessionId, message) =>
      post("/chat", { session_id: sessionId, message }),
  };
}
