import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";

interface PdfPageProps {
  doc: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  baseWidth: number;
  baseHeight: number;
  textLayer?: boolean;
}

function isCancelled(e: unknown): boolean {
  return e instanceof Error && e.name === "RenderingCancelledException";
}

export default function PdfPage({ doc, pageNumber, scale, baseWidth, baseHeight, textLayer = true }: PdfPageProps) {
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
        if (textLayer) {
          textDiv.style.setProperty("--scale-factor", String(viewport.scale));
          textDiv.style.width = `${viewport.width}px`;
          textDiv.style.height = `${viewport.height}px`;
          await new pdfjs.TextLayer({
            textContentSource: page.streamTextContent(),
            container: textDiv,
            viewport,
          }).render();
        }
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
  }, [doc, pageNumber, scale, visible, textLayer]);

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
