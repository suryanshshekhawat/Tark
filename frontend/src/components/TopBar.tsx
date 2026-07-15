import { useState } from "react";

const HOW_TO_USE_STEPS = [
  "Paste a LaTeX proof (or pick an example).",
  "Preview the rendered proof and confirm it looks right.",
  "Verify — Claude decomposes it into statements, Lean/SymPy check each one.",
  "Hover a statement to see the matching span highlighted in the source, and vice versa.",
];

export function TopBar({
  onBack,
  showWordmark = true,
}: {
  onBack?: () => void;
  showWordmark?: boolean;
}) {
  const [howToUseOpen, setHowToUseOpen] = useState(false);

  return (
    <div className="topbar-wrap">
      <header className="topbar">
        {showWordmark && <span className="wordmark">Tark.</span>}
      </header>

      <div className="topbar-sub">
        <div
          className="how-to-use"
          onMouseEnter={() => setHowToUseOpen(true)}
          onMouseLeave={() => setHowToUseOpen(false)}
        >
          <button
            type="button"
            className="how-to-use-link"
            onFocus={() => setHowToUseOpen(true)}
            onBlur={() => setHowToUseOpen(false)}
            aria-expanded={howToUseOpen}
          >
            How to use ?
          </button>
          {howToUseOpen && (
            <ol className="how-to-use-popover">
              {HOW_TO_USE_STEPS.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          )}
        </div>

        {onBack && (
          <button type="button" className="back-button" onClick={onBack}>
            ← back
          </button>
        )}
      </div>
    </div>
  );
}
