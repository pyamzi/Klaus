import type { RefObject } from "react";

interface FindBarProps {
  query: string;
  /** Pre-formatted count text — see countLabel() in find.ts. */
  label: string;
  inputRef: RefObject<HTMLInputElement | null>;
  onQueryChange: (query: string) => void;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}

/**
 * The find strip, per docs/reference/klausmate-viewer-parity.md: input,
 * count, prev, next, close. Presentational — the search itself lives in
 * ImpressView so matches can drive which slide is on stage.
 */
export default function FindBar({
  query,
  label,
  inputRef,
  onQueryChange,
  onNext,
  onPrev,
  onClose,
}: FindBarProps) {
  return (
    <div className="find-bar">
      <input
        ref={inputRef}
        type="search"
        className="find-input"
        placeholder="Find in PDF…"
        aria-label="Find in PDF"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        onKeyDown={(e) => {
          // Escape is handled globally in ImpressView so it works wherever
          // focus is — including on these buttons.
          if (e.key === "Enter") {
            e.preventDefault();
            if (e.shiftKey) {
              onPrev();
            } else {
              onNext();
            }
          }
        }}
      />
      <span className="find-count" role="status">{label}</span>
      {/* Glyph buttons need real names: a title tooltip is not a
          screen-reader label, and "‹" describes nothing. */}
      <button onClick={onPrev} aria-label="Previous match" title="Previous match (Shift+Enter)">
        ‹
      </button>
      <button onClick={onNext} aria-label="Next match" title="Next match (Enter)">
        ›
      </button>
      <button onClick={onClose} aria-label="Close find bar" title="Close (Esc)">
        ✕
      </button>
    </div>
  );
}
