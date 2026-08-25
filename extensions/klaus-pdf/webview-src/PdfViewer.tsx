import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { fetchPdfBytes } from "../lib/core";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const PAGE_GAP = 16;
const VIEW_PADDING = 24;

interface PageProps {
  doc: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  baseWidth: number;
  baseHeight: number;
}

function isCancelled(e: unknown): boolean {
  return e instanceof Error && e.name === "RenderingCancelledException";
}

function Page({ doc, pageNumber, scale, baseWidth, baseHeight }: PageProps) {
  const holderRef = useRef<HTMLDivElement>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const holder = holderRef.current;
    if (!holder) return;
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((e) => e.isIntersecting)),
      { rootMargin: "800px 0px" },
    );
    observer.observe(holder);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let renderTask: ReturnType<
      Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]
    > | null = null;

    (async () => {
      try {
        const page = await doc.getPage(pageNumber);
        if (cancelled) return;
        const host = canvasHostRef.current;
        const textDiv = textRef.current;
        if (!host || !textDiv) return;

        // Render into a fresh canvas and swap it in when done: no
        // canvas-reuse conflicts (StrictMode, rapid zoom) and no flicker.
        const viewport = page.getViewport({ scale });
        const dpr = window.devicePixelRatio || 1;
        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        renderTask = page.render({
          canvas,
          viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
        });
        await renderTask.promise;
        if (cancelled) return;
        host.replaceChildren(canvas);

        textDiv.replaceChildren();
        textDiv.style.setProperty("--scale-factor", String(viewport.scale));
        textDiv.style.width = `${viewport.width}px`;
        textDiv.style.height = `${viewport.height}px`;
        await new pdfjs.TextLayer({
          textContentSource: page.streamTextContent(),
          container: textDiv,
          viewport,
        }).render();
      } catch (e) {
        if (!cancelled && !isCancelled(e)) {
          console.error(`[klaus] page ${pageNumber} render failed:`, e);
        }
      }
    })();

    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [doc, pageNumber, scale, visible]);

  return (
    <div
      ref={holderRef}
      className="pdf-page"
      style={{ width: baseWidth * scale, height: baseHeight * scale }}
      data-page={pageNumber}
    >
      <div ref={canvasHostRef} className="pdf-page-canvas" />
      <div ref={textRef} className="textLayer" />
    </div>
  );
}

interface PdfViewerProps {
  pdfId: string;
  name: string;
}

export default function PdfViewer({ pdfId, name }: PdfViewerProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [baseSize, setBaseSize] = useState<{ w: number; h: number } | null>(null);
  const [scale, setScale] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const fitWidthScale = (w: number) => {
    const container = scrollRef.current;
    if (!container) return 1;
    return Math.max(0.25, (container.clientWidth - VIEW_PADDING * 2) / w);
  };

  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    setDoc(null);
    setBaseSize(null);
    setError(null);
    setCurrentPage(1);

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
        setScale(fitWidthScale(viewport.width));
        setDoc(loaded);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      task?.destroy();
    };
  }, [pdfId]);

  const onScroll = () => {
    const container = scrollRef.current;
    if (!container || !baseSize || !doc) return;
    const pageStride = baseSize.h * scale + PAGE_GAP;
    const middle = container.scrollTop + container.clientHeight / 2;
    const page = Math.floor(middle / pageStride) + 1;
    setCurrentPage(Math.min(Math.max(page, 1), doc.numPages));
  };

  const zoom = (factor: number) =>
    setScale((s) => Math.min(6, Math.max(0.25, s * factor)));

  if (error) {
    return <div className="viewer-message">Could not open {name}: {error}</div>;
  }
  if (!doc || !baseSize) {
    return <div className="viewer-message">Opening {name}…</div>;
  }

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <span className="viewer-title" title={name}>{name}</span>
        <span className="viewer-pages">
          {currentPage} / {doc.numPages}
        </span>
        <div className="viewer-zoom">
          <button onClick={() => zoom(1 / 1.2)} title="Zoom out">−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button onClick={() => zoom(1.2)} title="Zoom in">+</button>
          <button
            onClick={() => setScale(fitWidthScale(baseSize.w))}
            title="Fit width"
          >
            Fit
          </button>
        </div>
      </div>
      <div className="viewer-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="viewer-pages-column" style={{ gap: PAGE_GAP }}>
          {Array.from({ length: doc.numPages }, (_, i) => (
            <Page
              key={`${pdfId}-${i + 1}`}
              doc={doc}
              pageNumber={i + 1}
              scale={scale}
              baseWidth={baseSize.w}
              baseHeight={baseSize.h}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
