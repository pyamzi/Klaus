import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import NotesSidebar from "./NotesSidebar";
import PdfPage from "./PdfPage";
import { fetchPdfBytes } from "./core";
import {
  clampZoom,
  isTypingTarget,
  matchShortcut,
  parsePage,
  zoomIn,
  zoomOut,
  type TargetLike,
} from "./shortcuts";
import { toast } from "./toast";

const THUMB_WIDTH = 140;
const STAGE_PADDING = 32;

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

  // Shortcut table per docs/reference/klausmate-viewer-parity.md. Keystrokes
  // aimed at the notes textarea or the page field are left alone.
  useEffect(() => {
    if (!doc || !baseSize) return;
    const last = doc.numPages;
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target as TargetLike | null)) return;
      const action = matchShortcut(e);
      if (!action) return;
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
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc, baseSize, fitScale, selectSlideText]);

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
