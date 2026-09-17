// Client for the local klaus-core service, configured by the extension
// host via window.__KLAUS__ (see extension.ts / index.tsx).

const cfg = window.__KLAUS__ ?? ({} as Partial<Window["__KLAUS__"]>);
const BASE = cfg.coreUrl ?? "http://127.0.0.1:7863";
const TOKEN = cfg.coreToken ?? "dev";

export interface PdfMeta {
  id: string;
  name: string;
  size: number;
  mtime: number;
}

async function request(path: string): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "X-Klaus-Token": TOKEN },
  });
  if (!res.ok) {
    throw new Error(`klaus-core ${path} failed: ${res.status}`);
  }
  return res;
}

export async function fetchLibrary(): Promise<PdfMeta[]> {
  const res = await request("/library");
  const data = await res.json();
  return data.pdfs as PdfMeta[];
}

export async function fetchPdfBytes(id: string): Promise<ArrayBuffer> {
  const res = await request(`/pdf/${id}`);
  return res.arrayBuffer();
}

export interface NotesDoc {
  version: number;
  pages: Record<string, { md: string }>;
}

export async function fetchNotes(id: string): Promise<NotesDoc> {
  const res = await request(`/notes/${id}`);
  return res.json();
}

export async function saveNotes(id: string, doc: NotesDoc): Promise<void> {
  const res = await fetch(`${BASE}/notes/${id}`, {
    method: "PUT",
    headers: { "X-Klaus-Token": TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(doc),
  });
  if (!res.ok) {
    throw new Error(`klaus-core PUT /notes/${id} failed: ${res.status}`);
  }
}
