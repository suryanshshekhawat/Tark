import { useEffect, useState } from "react";

const FULL_TEXT = "Tark.";
const TYPE_INTERVAL_MS = 110;

/** The landing hero wordmark: types itself out, then the cursor blinks a
 * few times and disappears for good — it does not blink forever. */
export function TypingWordmark() {
  const [count, setCount] = useState(0);
  const [cursorGone, setCursorGone] = useState(false);
  const typingDone = count >= FULL_TEXT.length;

  useEffect(() => {
    if (typingDone) return;
    const timer = setTimeout(() => setCount((c) => c + 1), TYPE_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [count, typingDone]);

  return (
    <h1 className="wordmark-hero">
      {FULL_TEXT.slice(0, count)}
      {!cursorGone && (
        <span
          className={`wordmark-cursor${typingDone ? " cursor-fade-out" : ""}`}
          aria-hidden="true"
          onAnimationEnd={() => {
            if (typingDone) setCursorGone(true);
          }}
        />
      )}
    </h1>
  );
}
