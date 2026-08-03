/**
 * The three calculators, as buttons.
 *
 * Pressing one sends its label as an ordinary message. No new endpoint, no
 * client-side routing, no knowledge of what a calculator is - the server
 * classifies "Loan tenure" exactly as it would if it had been typed, which is
 * the whole reason a chip is safe to add.
 *
 * They disappear once the conversation is under way: a shortcut for the first
 * message is useful, and a row of buttons offering to start over halfway
 * through collecting an EMI is not.
 */

interface CalculatorChipsProps {
  names: readonly string[];
  disabled: boolean;
  onChoose: (name: string) => void;
}

export function CalculatorChips({ names, disabled, onChoose }: CalculatorChipsProps) {
  if (names.length === 0) return null;

  return (
    <div className="chips">
      <span className="chips__label" id="chips-label">
        Start with
      </span>
      <ul className="chips__list" aria-labelledby="chips-label">
        {names.map((name) => (
          <li key={name}>
            <button
              className="chip"
              type="button"
              disabled={disabled}
              onClick={() => onChoose(name)}
            >
              {name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
