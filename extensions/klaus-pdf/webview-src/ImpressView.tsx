import { useCallback, useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import NotesSidebar from "./NotesSidebar";
import PdfPage from "./PdfPage";
import { fetchPdfBytes } from "./core";

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

  const fitScale = useCallback((size: { w: number; h: number }) => {
    const stage = stageRef.current;
    if (!stage) return 1;
    return Math.max(
      0.1,
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
        const size = { w: viewport.width, h: viewport.height };
        setBaseSize(size);
        setScale(fitScale(size));
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

  // Refit when the panel resizes.
  useEffect(() => {
    if (!baseSize) return;
    const onResize = () => setScale(fitScale(baseSize));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [baseSize, fitScale]);

  // Keep a ref of `current` so the keydown handler need not re-bind per slide.
  const currentRef = useRef(current);
  currentRef.current = current;

  // Keyboard slide navigation, unless typing in the notes sidebar.
  useEffect(() => {
    if (!doc) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable) return;
      const last = doc.numPages;
      const go = (n: number) => {
        setCurrent(Math.min(Math.max(n, 1), last));
        e.preventDefault();
      };
      if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "PageDown") go(currentRef.current + 1);
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp" || e.key === "PageUp") go(currentRef.current - 1);
      else if (e.key === "Home") go(1);
      else if (e.key === "End") go(last);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc]);

  const zoom = (factor: number) =>
    setScale((s) => Math.min(6, Math.max(0.1, s * factor)));

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
          <span className="viewer-pages">{current} / {doc.numPages}</span>
          <div className="viewer-zoom">
            <button onClick={() => zoom(1 / 1.2)} title="Zoom out">−</button>
            <span>{Math.round(scale * 100)}%</span>
            <button onClick={() => zoom(1.2)} title="Zoom in">+</button>
            <button onClick={() => setScale(fitScale(baseSize))} title="Fit slide">Fit</button>
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
