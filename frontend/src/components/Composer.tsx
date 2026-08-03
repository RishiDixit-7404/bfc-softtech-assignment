/**
 * The input.
 *
 * A textarea rather than an input, because Shift+Enter has to produce a
 * newline and an `<input>` cannot hold one. Enter alone submits. It grows with
 * its content up to a few lines and then scrolls, so a long message is visible
 * without the composer eating the transcript.
 *
 * Focus returns here after every send, since the next thing a user does is
 * almost always type again. The button keeps a real label rather than an icon:
 * this is one action and it is worth naming.
 */

import { useEffect, useRef, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react";

const MAX_ROWS_HEIGHT_PX = 160;

interface ComposerProps {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** Bumped by the parent after each send, to pull focus back. */
  focusSignal: number;
}

export function Composer({
  value,
  disabled,
  onChange,
  onSubmit,
  focusSignal,
}: ComposerProps) {
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!disabled) field.current?.focus();
  }, [disabled, focusSignal]);

  // Height follows content. Reset first, or the box can only ever grow. A
  // scrollHeight of 0 means nothing has been laid out yet - in jsdom, always -
  // so leave the stylesheet's height alone rather than collapsing the field.
  useEffect(() => {
    const element = field.current;
    if (element === null) return;
    element.style.height = "auto";
    if (element.scrollHeight > 0) {
      element.style.height = `${Math.min(element.scrollHeight, MAX_ROWS_HEIGHT_PX)}px`;
    }
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <div className="composer__measure">
        <label className="composer__label" htmlFor="message">
          Your message
        </label>
        <div className="composer__row">
          <textarea
            className="composer__field"
            id="message"
            name="message"
            ref={field}
            rows={1}
            value={value}
            disabled={disabled}
            autoComplete="off"
            spellCheck={false}
            placeholder="Ask a question, or give a value"
            aria-describedby="composer-hint"
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
              onChange(event.target.value)
            }
            onKeyDown={handleKeyDown}
          />
          <button
            className="button button--primary"
            type="submit"
            disabled={disabled || value.trim() === ""}
          >
            Send
          </button>
        </div>
        <p className="composer__hint" id="composer-hint">
          Enter sends. Shift+Enter starts a new line.
        </p>
      </div>
    </form>
  );
}
