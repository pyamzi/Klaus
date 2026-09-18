import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { HIGHLIGHT_INKS, type Highlight } from "./highlights";

interface ContextMenuProps {
  x: number;
  y: number;
  /** The highlight under the cursor, if the right-click hit one — decides
   * whether Remove Highlight / the swatch row are enabled/shown. */
  hit: Highlight | null;
  /** Whether there is a live text selection — Copy and Highlight's disabled
   * state (parity spec: items disable rather than disappear). */
  hasSelection: boolean;
  onCopy: () => void;
  onHighlight: () => void;
  onRemoveHighlight: () => void;
  onSetColor: (color: string) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onActualSize: () => void;
  onClose: () => void;
}

/**
 * The stage's right-click menu, per docs/reference/klausmate-viewer-parity.md's
 * "Context menu" section (narrowed for KB-013 — see that card for the items
 * deliberately left out). Self-contained like a native context menu: unlike
 * FindBar, nothing else on screen needs to know it is open, so it owns its
 * own close-on-Escape/click-outside and viewport clamping.
 */
export default function ContextMenu({
  x,
  y,
  hit,
  hasSelection,
  onCopy,
  onHighlight,
  onRemoveHighlight,
  onSetColor,
  onZoomIn,
  onZoomOut,
  onActualSize,
  onClose,
}: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Clamp to the viewport after the first render, once the menu's real size
  // is known — a raw (x, y) can otherwise open off-screen near an edge.
  useLayoutEffect(() => {
    const el = menuRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos({
      left: Math.max(4, Math.min(x, window.innerWidth - rect.width - 4)),
      top: Math.max(4, Math.min(y, window.innerHeight - rect.height - 4)),
    });
  }, [x, y]);

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const fire = (action: () => void) => () => {
    action();
    onClose();
  };

  return (
    <div
      ref={menuRef}
      className="context-menu"
      role="menu"
      style={{ left: pos.left, top: pos.top }}
      // A mousedown inside the menu must not collapse the page selection —
      // Copy and Highlight both read it at click time.
      onMouseDown={(e) => e.preventDefault()}
    >
      <button role="menuitem" disabled={!hasSelection} onClick={fire(onCopy)}>
        Copy
      </button>
      <button role="menuitem" disabled={!hasSelection} onClick={fire(onHighlight)}>
        Highlight
      </button>
      {hit && (
        <div className="context-menu-swatches" role="group" aria-label="Highlight color">
          {HIGHLIGHT_INKS.map((ink) => (
            <button
              key={ink}
              type="button"
              className={ink === hit.color ? "context-menu-swatch selected" : "context-menu-swatch"}
              style={{ background: ink }}
              aria-label={`Set highlight color to ${ink}`}
              aria-checked={ink === hit.color}
              role="menuitemradio"
              onClick={fire(() => onSetColor(ink))}
            />
          ))}
        </div>
      )}
      <button role="menuitem" disabled={!hit} onClick={fire(onRemoveHighlight)}>
        Remove Highlight
      </button>
      <div className="context-menu-separator" role="separator" />
      <button role="menuitem" onClick={fire(onZoomIn)}>
        Zoom In (Cmd+=)
      </button>
      <button role="menuitem" onClick={fire(onZoomOut)}>
        Zoom Out (Cmd+-)
      </button>
      <button role="menuitem" onClick={fire(onActualSize)}>
        Actual Size (Cmd+0)
      </button>
    </div>
  );
}
