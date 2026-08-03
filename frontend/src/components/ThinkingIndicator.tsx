/**
 * Shown while a reply is on its way.
 *
 * A live call takes one to four seconds, which is long enough that a still
 * screen reads as a broken one. It occupies the same slot a turn would, so the
 * transcript does not jump when the reply replaces it.
 *
 * The three dots fade rather than bounce, and stop entirely under
 * `prefers-reduced-motion` - see styles.css. `role="status"` announces it once;
 * the visible text is the announcement, so there is no second copy to drift.
 */
export function ThinkingIndicator() {
  return (
    <article className="turn turn--bot turn--thinking">
      <h2 className="turn__speaker">Assistant</h2>
      <p className="thinking" role="status">
        <span className="thinking__label">Working that out</span>
        <span className="thinking__dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </p>
    </article>
  );
}
