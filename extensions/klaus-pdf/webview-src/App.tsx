import { useEffect, useState } from "react";
import PdfViewer from "./components/PdfViewer";
import { fetchLibrary, type PdfMeta } from "./lib/core";
import "./App.css";

function prettyName(name: string): string {
  return name.replace(/\.pdf$/i, "").replace(/_/g, " ");
}

function prettySize(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function App() {
  const [library, setLibrary] = useState<PdfMeta[] | null>(null);
  const [selected, setSelected] = useState<PdfMeta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLibrary()
      .then(setLibrary)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-header">Klaus</div>
        <div className="sidebar-section">Library</div>
        {error && (
          <div className="sidebar-error">
            klaus-core unreachable — is it running on port 7863?
            <div className="sidebar-error-detail">{error}</div>
          </div>
        )}
        {library?.length === 0 && (
          <div className="sidebar-empty">No PDFs in the library yet.</div>
        )}
        <ul className="pdf-list">
          {library?.map((pdf) => (
            <li key={pdf.id}>
              <button
                className={selected?.id === pdf.id ? "pdf-item selected" : "pdf-item"}
                onClick={() => setSelected(pdf)}
              >
                <span className="pdf-item-name">{prettyName(pdf.name)}</span>
                <span className="pdf-item-size">{prettySize(pdf.size)}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main className="content">
        {selected ? (
          <PdfViewer key={selected.id} pdfId={selected.id} name={selected.name} />
        ) : (
          <div className="viewer-message">Select a PDF from the library.</div>
        )}
      </main>
    </div>
  );
}
