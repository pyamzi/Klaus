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
