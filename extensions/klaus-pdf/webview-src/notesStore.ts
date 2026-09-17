import { useCallback, useEffect, useRef, useState } from "react";
import { fetchNotes, saveNotes, type NotesDoc } from "./core";
import type { Highlight } from "./highlights";

const SAVE_DEBOUNCE_MS = 800;

export type SaveState = "saved" | "saving" | "error";

export interface NotesStore {
  doc: NotesDoc | null;
  loadError: string | null;
  status: SaveState;
  /** The latest doc, unaffected by render timing — for async callers. */
  getDoc: () => NotesDoc | null;
  updatePage: (key: string, text: string) => void;
  addHighlight: (key: string, highlight: Highlight) => void;
}

/**
 * The one owner of a PDF's notes document. Everything that edits the doc —
 * the notes sidebar, the highlight shortcut — goes through this hook's
 * commit path, so there is exactly one writer and one save pipeline.
 *
 * Saves are serialized: at most one PUT in flight, and a snapshot that is
 * already stale by the time it lands neither shows "Saved" nor stops the
 * newer state from being flushed right after.
 */
export function useNotesDoc(pdfId: string): NotesStore {
  const [doc, setDoc] = useState<NotesDoc | null>(null);
  const [status, setStatus] = useState<SaveState>("saved");
  const [loadError, setLoadError] = useState<string | null>(null);
  const docRef = useRef<NotesDoc | null>(null);
  const revRef = useRef(0); // bumps on every edit
  const savingRef = useRef(false); // a PUT is in flight
  const timerRef = useRef<number | undefined>(undefined);

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

  const flush = useCallback(async () => {
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
  }, [pdfId]);

  // Flush a pending edit when the panel goes away.
  useEffect(() => {
    return () => {
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
        void flush();
      }
    };
  }, [flush]);

  const commit = useCallback(
    (next: NotesDoc) => {
      docRef.current = next;
      revRef.current += 1;
      setDoc(next);
      setStatus("saving");
      if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => void flush(), SAVE_DEBOUNCE_MS);
    },
    [flush],
  );

  const updatePage = useCallback(
    (key: string, text: string) => {
      const cur = docRef.current;
      if (!cur) return;
      commit({ ...cur, pages: { ...cur.pages, [key]: { md: text } } });
    },
    [commit],
  );

  const addHighlight = useCallback(
    (key: string, highlight: Highlight) => {
      const cur = docRef.current;
      if (!cur) return;
      const existing = cur.highlights ?? {};
      commit({
        ...cur,
        highlights: { ...existing, [key]: [...(existing[key] ?? []), highlight] },
      });
    },
    [commit],
  );

  const getDoc = useCallback(() => docRef.current, []);

  return { doc, loadError, status, getDoc, updatePage, addHighlight };
}
