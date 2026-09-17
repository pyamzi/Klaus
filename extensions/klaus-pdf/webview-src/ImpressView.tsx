import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import FindBar from "./FindBar";
import NotesSidebar from "./NotesSidebar";
import PdfPage from "./PdfPage";
import { fetchPdfBytes } from "./core";
import {
  clampZoom,
  isTypingTarget,
  matchShortcut,
  type Action,
  parsePage,
  zoomIn,
  zoomOut,
  type TargetLike,
} from "./shortcuts";
import { toast } from "./toast";
import { countLabel, cycleIndex, findMatches, type Match, type PageText } from "./find";

const THUMB_WIDTH = 140;
const STAGE_PADDING = 32;
const FIND_DEBOUNCE_MS = 250;
// A slide's text layer only starts rendering once its canvas render promise
// resolves, so a match on a slow page can be several hundred ms away. Watch
// for the layer instead of guessing, and give up rather than watch forever.
const REVEAL_TIMEOUT_MS = 4000;

interface ImpressViewProps {
  pdfId: string;
  name: string;
}

export default function ImpressView({ pdfId, name }: ImpressViewProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [baseSize, setBaseSize] = useState<{ w: number; h: number } | null>(null);
  const [current, setCurrent] = useState(1);
  const [scale, setScale] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [pageDraft, setPageDraft] = useState("1");
  const pageInputRef = useRef<HTMLInputElement>(null);
  const [findOpen, setFindOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pageText, setPageText] = useState<PageText[] | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [matchIndex, setMatchIndex] = useState(-1);
  const findInputRef = useRef<HTMLInputElement>(null);
  const [searchedQuery, setSearchedQuery] = useState("");
  const searchTimer = useRef<number | undefined>(undefined);

  const closeFind = useCallback(() => {
    window.clearTimeout(searchTimer.current);
    setFindOpen(false);
    setQuery("");
    setSearchedQuery("");
    setMatches([]);
    setMatchIndex(-1);
  }, []);

  // Fit obeys the same 0.25-5.0 ladder as the zoom keys, so Cmd+0 can never
  // land outside it. A slide that would need less than 0.25 to fit therefore
  // overflows the stage and scrolls, rather than shrinking off the ladder.
  const fitScale = useCallback((size: { w: number; h: number }) => {
    const stage = stageRef.current;
    if (!stage) return 1;
    return clampZoom(
      Math.min(
        (stage.clientWidth - STAGE_PADDING * 2) / size.w,
        (stage.clientHeight - STAGE_PADDING * 2) / size.h,
      ),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    setDoc(null);
    setBaseSize(null);
    setError(null);
    setCurrent(1);
    closeFind();
    setPageText(null);

    (async () => {
      try {
        const data = await fetchPdfBytes(pdfId);
        task = pdfjs.getDocument({ data });
        const loaded = await task.promise;
        if (cancelled) return;
        const first = await loaded.getPage(1);
        const viewport = first.getViewport({ scale: 1 });
        if (cancelled) return;
        setBaseSize({ w: viewport.width, h: viewport.height });
        setDoc(loaded);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      task?.destroy();
    };
  }, [pdfId, fitScale]);

  // The initial fit must run after the stage has mounted — during loading
  // the component renders the "Opening…" branch and stageRef is null.
  useLayoutEffect(() => {
    if (doc && baseSize) setScale(fitScale(baseSize));
  }, [doc, baseSize, fitScale]);

  // Refit when the panel resizes.
  useEffect(() => {
    if (!baseSize) return;
    const onResize = () => setScale(fitScale(baseSize));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [baseSize, fitScale]);

  // The page field mirrors the slide unless the user is mid-edit.
  useEffect(() => {
    setPageDraft(String(current));
  }, [current]);

  // Cmd+A: select the slide's own text layer, nothing else on the page.
  const selectSlideText = useCallback(() => {
    const layer = stageRef.current?.querySelector(".textLayer");
    const selection = window.getSelection();
    if (!layer || !layer.textContent?.trim() || !selection) {
      toast("no selectable text on this page");
      return;
    }
    const range = document.createRange();
    range.selectNodeContents(layer);
    selection.removeAllRanges();
    selection.addRange(range);
  }, []);

  // Page text is only needed once someone searches, and it costs a pass over
  // the whole document — so load it on first open and keep it.
  useEffect(() => {
    if (!findOpen || !doc || pageText) return;
    let cancelled = false;
    (async () => {
      const pages: PageText[] = [];
      for (let n = 1; n <= doc.numPages; n++) {
        const page = await doc.getPage(n);
        const content = await page.getTextContent();
        if (cancelled) return;
        // Joined with no separator so offsets line up with the text layer's
        // own concatenation, which is what revealMatch() walks.
        pages.push({
          page: n,
          text: content.items.map((item) => ("str" in item ? item.str : "")).join(""),
        });
      }
      if (!cancelled) setPageText(pages);
    })();
    return () => {
      cancelled = true;
    };
  }, [findOpen, doc, pageText]);

  const runSearch = useCallback(
    (text: string): Match[] => {
      const found = pageText ? findMatches(pageText, text) : [];
      setMatches(found);
      setMatchIndex(-1);
      setSearchedQuery(text);
      return found;
    },
    [pageText],
  );

  // Live search, debounced. A fresh query selects no match yet: the label
  // reads "{n} matches" until Enter or Cmd+G moves to one, so typing never
  // yanks the stage out from under you.
  useEffect(() => {
    if (!findOpen) return;
    searchTimer.current = window.setTimeout(() => runSearch(query), FIND_DEBOUNCE_MS);
    return () => window.clearTimeout(searchTimer.current);
  }, [findOpen, query, runSearch]);

  /**
   * Map a page-text offset range onto that page's rendered text layer and
   * select it —
   * the text layer already tints ::selection, so the match shows up without a
   * second highlight mechanism. Silently does nothing if the layer is not
   * ready or the offsets do not line up.
   */
  const revealMatch = useCallback((layer: Element, start: number, end: number) => {
    const selection = window.getSelection();
    if (!selection) return;
    const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
    let consumed = 0;
    let startNode: Text | null = null;
    let startOffset = 0;
    let endNode: Text | null = null;
    let endOffset = 0;
    for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
      const length = node.data.length;
      if (!startNode && consumed + length > start) {
        startNode = node;
        startOffset = start - consumed;
      }
      if (startNode && consumed + length >= end) {
        endNode = node;
        endOffset = end - consumed;
        break;
      }
      consumed += length;
    }
    if (!startNode || !endNode) return;
    const range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    selection.removeAllRanges();
    selection.addRange(range);
    startNode.parentElement?.scrollIntoView({ block: "nearest" });
  }, []);

  // Moving to a match navigates to its slide, then reveals it once that
  // slide's text layer has actually rendered — which may be well after the
  // navigation, so this watches the stage instead of racing a timer.
  useEffect(() => {
    const match = matches[matchIndex];
    const stage = stageRef.current;
    if (!match || !stage) return;
    setCurrent(match.page);

    let done = false;
    const attempt = () => {
      if (done) return;
      // Pinned to the target page: this effect runs before the slide swap
      // commits, so an unpinned ".textLayer" would match the page we are
      // leaving — which is populated — and select against the wrong text.
      const layer = stage.querySelector(`.pdf-page[data-page="${match.page}"] .textLayer`);
      if (!layer?.textContent) return;
      done = true;
      observer.disconnect();
      window.clearTimeout(deadline);
      revealMatch(layer, match.start, match.end);
    };
    const observer = new MutationObserver(attempt);
    observer.observe(stage, { childList: true, subtree: true });
    const deadline = window.setTimeout(() => observer.disconnect(), REVEAL_TIMEOUT_MS);
    attempt();

    return () => {
      done = true;
      observer.disconnect();
      window.clearTimeout(deadline);
    };
  }, [matchIndex, matches, revealMatch]);

  /**
   * Next/previous match. With no matches this lands on -1 and nothing
   * navigates; the count label already says "0 matches", so a toast on top
   * of it would just be noise.
   *
   * Enter within the debounce window has to search what is on screen now —
   * otherwise the first Enter of a search does nothing and a re-typed query
   * jumps to the old query's hit.
   */
  const cycleMatch = useCallback(
    (step: number) => {
      const stale = query !== searchedQuery;
      if (!stale) {
        setMatchIndex((i) => cycleIndex(i, matches.length, step));
        return;
      }
      window.clearTimeout(searchTimer.current);
      const found = runSearch(query);
      setMatchIndex(cycleIndex(-1, found.length, step));
    },
    [matches.length, query, searchedQuery, runSearch],
  );

  const openFind = useCallback(() => {
    setFindOpen(true);
    // The input may be mounting on this very tick.
    window.setTimeout(() => {
      findInputRef.current?.focus();
      findInputRef.current?.select();
    }, 0);
  }, []);

  // Shortcut table per docs/reference/klausmate-viewer-parity.md. Keystrokes
  // aimed at the notes textarea or the page field are left alone.
  useEffect(() => {
    if (!doc || !baseSize) return;
    const last = doc.numPages;
    const findActions: Action[] = ["find", "find-next", "find-prev"];
    const onKey = (e: KeyboardEvent) => {
      // Esc belongs to the find bar whenever it is open, whatever has focus —
      // the buttons and the slide included, not just the input.
      if (findOpen && e.key === "Escape") {
        e.preventDefault();
        closeFind();
        return;
      }
      const action = matchShortcut(e);
      if (!action) return;
      // Find combos are claimed even from the find field; everything else
      // belongs to whatever is being typed in.
      if (isTypingTarget(e.target as TargetLike | null) && !findActions.includes(action)) return;
      e.preventDefault();
      switch (action) {
        case "zoom-in":
          setScale(zoomIn);
          break;
        case "zoom-out":
          setScale(zoomOut);
          break;
        case "zoom-fit":
          setScale(fitScale(baseSize));
          break;
        case "select-page":
          selectSlideText();
          break;
        case "go-to-page":
          pageInputRef.current?.focus();
          pageInputRef.current?.select();
          break;
        case "page-next":
          setCurrent((c) => Math.min(c + 1, last));
          break;
        case "page-prev":
          setCurrent((c) => Math.max(c - 1, 1));
          break;
        case "page-first":
          setCurrent(1);
          break;
        case "page-last":
          setCurrent(last);
          break;
        case "find":
          openFind();
          break;
        case "find-next":
          // Silent no-op while the bar is hidden (parity spec).
          if (findOpen) cycleMatch(1);
          break;
        case "find-prev":
          if (findOpen) cycleMatch(-1);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc, baseSize, fitScale, selectSlideText, openFind, cycleMatch, closeFind, findOpen]);

  const commitPageDraft = () => {
    if (!doc) return;
    const n = parsePage(pageDraft, doc.numPages);
    if (n === null) {
      toast(`page must be between 1 and ${doc.numPages}`);
      setPageDraft(String(current));
      return;
    }
    setCurrent(n);
  };

  if (error) {
    return <div className="viewer-message">Could not open {name}: {error}</div>;
  }
  if (!doc || !baseSize) {
    return <div className="viewer-message">Opening {name}…</div>;
  }

  const thumbScale = THUMB_WIDTH / baseSize.w;
  return (
    <div className="impress">
      <div className="filmstrip">
        {Array.from({ length: doc.numPages }, (_, i) => {
          const n = i + 1;
          return (
            <button
              key={n}
              className={n === current ? "thumb selected" : "thumb"}
              onClick={() => setCurrent(n)}
            >
              <PdfPage
                doc={doc}
                pageNumber={n}
                scale={thumbScale}
                baseWidth={baseSize.w}
                baseHeight={baseSize.h}
                textLayer={false}
              />
              <span className="thumb-num">{n}</span>
            </button>
          );
        })}
      </div>
      <div className="stage-column">
        {findOpen && (
          <FindBar
            query={query}
            label={countLabel(query, matches.length, matchIndex)}
            inputRef={findInputRef}
            onQueryChange={setQuery}
            onNext={() => cycleMatch(1)}
            onPrev={() => cycleMatch(-1)}
            onClose={closeFind}
          />
        )}
        <div className="viewer-toolbar">
          <span className="viewer-title" title={name}>{name}</span>
          <span className="viewer-pages">
            <input
              ref={pageInputRef}
              className="page-input"
              style={{ "--page-digits": String(doc.numPages).length } as CSSProperties}
              value={pageDraft}
              aria-label="Page number"
              title="Go to page (Cmd+Alt+G)"
              onChange={(e) => setPageDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  commitPageDraft();
                  e.currentTarget.blur();
                } else if (e.key === "Escape") {
                  setPageDraft(String(current));
                  e.currentTarget.blur();
                }
              }}
              onBlur={() => setPageDraft(String(current))}
            />
            {" / "}
            {doc.numPages}
          </span>
          <div className="viewer-zoom">
            <button onClick={() => setScale(zoomOut)} title="Zoom out (Cmd+-)">−</button>
            <span>{Math.round(scale * 100)}%</span>
            <button onClick={() => setScale(zoomIn)} title="Zoom in (Cmd+=)">+</button>
            <button onClick={() => setScale(fitScale(baseSize))} title="Fit slide (Cmd+0)">Fit</button>
          </div>
        </div>
        <div className="stage" ref={stageRef}>
          <PdfPage
            key={`stage-${current}`}
            doc={doc}
            pageNumber={current}
            scale={scale}
            baseWidth={baseSize.w}
            baseHeight={baseSize.h}
            textLayer
          />
        </div>
      </div>
      <NotesSidebar pdfId={pdfId} page={current} />
    </div>
  );
}
