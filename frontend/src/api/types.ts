/**
 * The server's contract, which this phase does not change.
 *
 * Two endpoints, `POST /session` and `POST /chat`, both answering with the
 * same object. `reply` is a plain string: the entire bot message, already
 * worded and already formatted, produced by `chat/` and passed through
 * `app.py` untouched.
 *
 * There is deliberately no richer payload - no structured result, no field
 * list, no pre-split figures. If the interface ever seems to need one, the
 * interface is asking to do a job that belongs to `chat/formatting.py`.
 */
export interface ConversationReply {
  readonly session_id: string;
  readonly reply: string;
}
