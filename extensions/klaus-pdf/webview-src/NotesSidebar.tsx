import { useRef, useState } from "react";
import { marked } from "marked";
import { assetUrl, uploadAsset } from "./core";
import type { NotesStore } from "./notesStore";

interface NotesSidebarProps {
  pdfId: string;
  page: number;
  store: NotesStore;
}

export default function NotesSidebar({ pdfId, page, store }: NotesSidebarProps) {
  const { doc, loadError, status } = store;
  const [preview, setPreview] = useState(false);
  const [uploadFailed, setUploadFailed] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const md = doc?.pages[String(page)]?.md ?? "";

  const insertImage = async (file: Blob) => {
    if (!file.type.startsWith("image/")) return;
    // Capture the target slide and cursor before awaiting: the user may
    // switch slides or keep typing while the upload is in flight.
    const targetPage = String(page);
    const el = textRef.current;
    const at = el ? el.selectionStart : null;
    setUploadFailed(false);
    try {
      const name = await uploadAsset(pdfId, file);
      const ref = `![](${assetUrl(pdfId, name)})`;
      const latest = store.getDoc()?.pages[targetPage]?.md ?? "";
      const pos = at !== null && at <= latest.length ? at : latest.length;
      store.updatePage(targetPage, latest.slice(0, pos) + ref + latest.slice(pos));
    } catch {
      setUploadFailed(true);
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

  const failed = status === "error" || uploadFailed;
  return (
    <aside className="notes-sidebar">
      <div className="notes-header">
        <span>Slide {page}</span>
        <span className={`notes-status notes-status-${failed ? "error" : status}`}>
          {status === "saving" ? "Saving…" : failed ? "Save failed" : "Saved"}
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
          onChange={(e) => store.updatePage(String(page), e.target.value)}
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
