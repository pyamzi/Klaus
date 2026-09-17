import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import { assetUrl, fetchNotes, saveNotes, uploadAsset, type NotesDoc } from "./core";

const SAVE_DEBOUNCE_MS = 800;

interface NotesSidebarProps {
  pdfId: string;
  page: number;
}

type SaveState = "saved" | "saving" | "error";

export default function NotesSidebar({ pdfId, page }: NotesSidebarProps) {
  const [doc, setDoc] = useState<NotesDoc | null>(null);
  const [preview, setPreview] = useState(false);
  const [status, setStatus] = useState<SaveState>("saved");
  const [loadError, setLoadError] = useState<string | null>(null);
  const docRef = useRef<NotesDoc | null>(null);
  const revRef = useRef(0); // bumps on every edit
  const savingRef = useRef(false); // a PUT is in flight
  const timerRef = useRef<number | undefined>(undefined);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchNotes(pdfId)
      .then((d) => {
        if (cancelled) return;
        docRef.current = d;
        setDoc(d);
      })
      .catch((e) => !cancelled && setLoadError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [pdfId]);

  // Saves are serialized: at most one PUT in flight, and a snapshot that is
  // already stale by the time it lands neither shows "Saved" nor stops the
  // newer state from being flushed right after.
  const flush = async () => {
    timerRef.current = undefined;
    if (savingRef.current) return; // the finisher below re-runs flush
    const d = docRef.current;
    if (!d) return;
    savingRef.current = true;
    const rev = revRef.current;
    try {
      await saveNotes(pdfId, d);
      if (revRef.current === rev) setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      savingRef.current = false;
      if (revRef.current !== rev) void flush();
    }
  };

  // Flush a pending edit when the panel goes away.
  useEffect(() => {
    return () => {
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
        void flush();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const md = doc?.pages[String(page)]?.md ?? "";

  const updatePage = (key: string, text: string) => {
    if (!docRef.current) return;
    const next: NotesDoc = {
      ...docRef.current,
      pages: { ...docRef.current.pages, [key]: { md: text } },
    };
    docRef.current = next;
    revRef.current += 1;
    setDoc(next);
    setStatus("saving");
    if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => void flush(), SAVE_DEBOUNCE_MS);
  };

  const insertImage = async (file: Blob) => {
    if (!file.type.startsWith("image/")) return;
    // Capture the target slide and cursor before awaiting: the user may
    // switch slides or keep typing while the upload is in flight.
    const targetPage = String(page);
    const el = textRef.current;
    const at = el ? el.selectionStart : null;
    setStatus("saving");
    try {
      const name = await uploadAsset(pdfId, file);
      const ref = `![](${assetUrl(pdfId, name)})`;
      const latest = docRef.current?.pages[targetPage]?.md ?? "";
      const pos = at !== null && at <= latest.length ? at : latest.length;
      updatePage(targetPage, latest.slice(0, pos) + ref + latest.slice(pos));
    } catch {
      setStatus("error");
    }
  };

  if (loadError) {
    return (
      <aside className="notes-sidebar">
        <div className="notes-header">Slide {page}</div>
        <div className="notes-error">Notes unavailable: {loadError}</div>
      </aside>
    );
  }

  return (
    <aside className="notes-sidebar">
      <div className="notes-header">
        <span>Slide {page}</span>
        <span className={`notes-status notes-status-${status}`}>
          {status === "saving" ? "Saving…" : status === "error" ? "Save failed" : "Saved"}
        </span>
        <button className="notes-toggle" onClick={() => setPreview((p) => !p)}>
          {preview ? "Edit" : "Preview"}
        </button>
      </div>
      {preview ? (
        <div
          className="notes-preview"
          // Scripts injected via note HTML cannot run: the webview CSP only
          // allows nonce'd scripts. This is the user's own local content.
          dangerouslySetInnerHTML={{ __html: marked.parse(md, { async: false }) as string }}
        />
      ) : (
        <textarea
          ref={textRef}
          className="notes-input"
          placeholder="Notes for this slide… (Markdown)"
          value={md}
          disabled={doc === null}
          onChange={(e) => updatePage(String(page), e.target.value)}
          onPaste={(e) => {
            const file = Array.from(e.clipboardData.items)
              .find((i) => i.type.startsWith("image/"))?.getAsFile();
            if (file) {
              e.preventDefault();
              void insertImage(file);
            }
          }}
          onDrop={(e) => {
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith("image/")) {
              e.preventDefault();
              void insertImage(file);
            }
          }}
        />
      )}
    </aside>
  );
}
