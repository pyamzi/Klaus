// Client for the local klaus-core service.

const BASE = import.meta.env.VITE_KLAUS_CORE_URL ?? "http://127.0.0.1:7863";
const TOKEN = import.meta.env.VITE_KLAUS_CORE_TOKEN ?? "dev";

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
