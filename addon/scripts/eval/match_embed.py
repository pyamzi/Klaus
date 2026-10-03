"""K-302 match-precision harness, step 1: embed card/page variants with the
local Ollama and cache them as .npy in $KLAUS_EVAL_DIR (default: a temp dir).

Read-only toward Klaus: never writes to user_files or the live collection
(it copies collection.anki2 + WAL first). Variants: A = the vectors Klaus
has on disk; B = task prefix; C = prefix + Text-only cloze; D = Text-only.
Then run match_analyze.py. Needs numpy.

    KLAUS_EVAL_DIR=/tmp/k302 python3 scripts/eval/match_embed.py [B C D]
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request

import numpy as np

HERE = os.environ.get("KLAUS_EVAL_DIR") or os.path.join(tempfile.gettempdir(), "klaus-match-eval")
os.makedirs(HERE, exist_ok=True)
UF = os.environ.get("KLAUS_USER_FILES") or os.path.join(os.path.dirname(__file__), "..", "..", "klaus_note", "user_files")
COL = os.path.expanduser(os.environ.get("KLAUS_COLLECTION") or "~/Library/Application Support/Anki2/Pouya/collection.anki2")
OLLAMA = "http://127.0.0.1:11434/api/embed"


def strip_html(s: str) -> str:  # mirrors klaus_note._strip_html
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</?(div|p|span|li|ul|ol|h[1-6])\b[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"'))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


_WS = re.compile(r"\s+")
CLOZE = re.compile(r"\{\{c\d+::((?:(?!\{\{|\}\}|::).)*)(?:::(?:(?!\{\{|\}\}).)*)?\}\}", re.S)


def resolve_cloze(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, CLOZE.sub(r"\1", s)
    return s


def note_text(fields, cloze_resolve=False, text_only=False, cap=4000):
    if text_only:
        fields = fields[:1]
    parts = []
    for f in fields:
        t = strip_html(f or "").strip()
        if cloze_resolve:
            t = resolve_cloze(t)
        if t:
            parts.append(t)
    text = _WS.sub(" ", " \n ".join(parts)).strip()
    return text[:cap]


def h8(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def embed(texts, prefix=""):
    out = []
    t0 = time.time()
    for i in range(0, len(texts), 64):
        batch = [prefix + t for t in texts[i:i + 64]]
        req = urllib.request.Request(OLLAMA, data=json.dumps(
            {"model": "nomic-embed-text", "input": batch, "truncate": True}).encode(),
            headers={"Content-Type": "application/json"})
        out.extend(json.load(urllib.request.urlopen(req, timeout=600))["embeddings"])
        if i % 6400 == 0:
            print(f"  {i}/{len(texts)} {time.time()-t0:.0f}s", flush=True)
    v = np.asarray(out, dtype=np.float32)
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    return v


def load_notes():
    tmp = os.path.join(HERE, "col_copy")
    os.makedirs(tmp, exist_ok=True)
    for suffix in ("", "-wal"):
        if os.path.exists(COL + suffix):
            shutil.copy2(COL + suffix, os.path.join(tmp, "collection.anki2" + suffix))
    db = sqlite3.connect(os.path.join(tmp, "collection.anki2"))
    cloze_mids = {int(i) for i, cfg in db.execute("select id, config from notetypes")
                  if bytes(cfg or b"")[:2] == b"\x08\x01"}
    rows = db.execute("select id, mid, flds from notes").fetchall()
    return {int(n): (int(m) in cloze_mids, f.split("\x1f")) for n, m, f in rows}


def load_old_cards():
    d = os.path.join(UF, "card_index")
    m = json.load(open(os.path.join(d, "manifest.json")))
    v = np.fromfile(os.path.join(d, "vectors.f32"), dtype=np.float32).reshape(len(m["nids"]), m["dims"])
    return [int(n) for n in m["nids"]], m["hashes"], v


def load_pages():
    out = {}
    for d in sorted(os.listdir(os.path.join(UF, "pdf_index"))):
        mp = os.path.join(UF, "pdf_index", d, "manifest.json")
        if not os.path.exists(mp):
            continue
        m = json.load(open(mp))
        vec = np.fromfile(os.path.join(UF, "pdf_index", d, "vectors.f32"), dtype=np.float32)
        vec = vec.reshape(-1, m["dims"])[: m["embedded_rows"]]
        want = {int(p): h for p, h in m["pages"]}
        # pick the record dir whose texts match the manifest hashes best
        best = None
        for rd in glob.glob(os.path.join(UF, "pages", d, "*")):
            texts, hits = {}, 0
            for p in want:
                f = os.path.join(rd, f"{p-1:04d}.json")
                if not os.path.exists(f):
                    continue
                r = json.load(open(f))
                slide = str(r.get("slide_text") or "").strip()
                said = "\n".join(str(s.get("text") or "").strip() for s in r.get("segments") or [] if str(s.get("text") or "").strip())
                t = f"{slide}\n\n{said}" if slide and said else (slide or said)
                texts[p] = t
                hits += h8(t) == want[p]
            if best is None or hits > best[0]:
                best = (hits, texts)
        pages = sorted(want)
        out[d] = {"pages": pages, "texts": [best[1].get(p, "") for p in pages], "old": vec, "hits": best[0]}
    return out


if __name__ == "__main__":
    notes = load_notes()
    nids, hashes, old_v = load_old_cards()
    fields = [notes.get(n, (False, [""]))[1] for n in nids]
    is_cloze = np.array([notes.get(n, (False, []))[0] for n in nids])
    base = [note_text(f) for f in fields]
    match = sum(h8(t) == h for t, h in zip(base, hashes))
    print(f"notes {len(nids)} cloze {is_cloze.sum()} base-text hash match {match}/{len(nids)}")
    pages = load_pages()
    for d, p in pages.items():
        print(f"  pdf {d}: {len(p['pages'])} pages, text hash match {p['hits']}")
    json.dump({"nids": nids, "cloze": is_cloze.tolist()}, open(os.path.join(HERE, "cards.json"), "w"))
    np.save(os.path.join(HERE, "cards_A.npy"), old_v)
    variants = {
        "B": ([note_text(f) for f in fields], "search_document: "),
        "C": ([note_text(f, True, c) for f, c in zip(fields, is_cloze)], "search_document: "),
        "D": ([note_text(f, True, c) for f, c in zip(fields, is_cloze)], ""),
    }
    for name in sys.argv[1:] or ["B", "C", "D"]:
        texts, prefix = variants[name]
        if name != "A":
            print(f"embedding cards {name}", flush=True)
            np.save(os.path.join(HERE, f"cards_{name}.npy"), embed([t or " " for t in texts], prefix))
    for d, p in pages.items():
        np.save(os.path.join(HERE, f"pages_{d}_A.npy"), p["old"])
        np.save(os.path.join(HERE, f"pages_{d}_P.npy"), embed([t or " " for t in p["texts"]], "search_document: "))
        np.save(os.path.join(HERE, f"pages_{d}_N.npy"), embed([t or " " for t in p["texts"]], ""))
    json.dump({d: {"pages": p["pages"], "texts": p["texts"]} for d, p in pages.items()},
              open(os.path.join(HERE, "pages.json"), "w"))
    print("done")
