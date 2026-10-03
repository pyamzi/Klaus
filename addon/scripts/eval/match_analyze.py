"""K-302 match-precision harness, step 2: compare variants on proxy labels.

Positives are cards whose Text names the lecture's topic by keyword; hard
negatives are same-subject cards that don't. Reports AUC, false positives
at the recall the old raw 0.75 threshold had, and the best-lecture rule.
Proxy labels only: swap TASKS for a hand-labelled set when one exists.
"""
from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_embed import HERE, load_notes, note_text  # noqa: E402

cards = json.load(open(os.path.join(HERE, "cards.json")))
nids, cloze = cards["nids"], np.array(cards["cloze"])
pages_meta = json.load(open(os.path.join(HERE, "pages.json")))
PDFS = sorted(pages_meta)
notes = load_notes()
text = [note_text(notes.get(n, (False, [""]))[1][:1], cloze_resolve=True) for n in nids]

TASKS = {
    "B-12_and_Folate_Deficiency_ELO": (
        r"\bB-?12\b|cobalamin|folate|folic|methylmalon|homocystein|pernicious|intrinsic factor|megaloblast|hypersegment|subacute combined",
        r"iron deficien|ferritin|sickle|thalass|hemophilia|von Willebrand|G6PD|spherocyt|leukemia|lymphoma|myeloma|\bDIC\b|\bTTP\b|\bITP\b|polycythemia|hemochromat|lead poison|sideroblast",
    ),
    "RCTs_and_Measures_of_Asociation": (
        r"randomi[sz]|\bRCT|relative risk|odds ratio|number needed|\bNNT\b|intention[- ]to[- ]treat|blinding|attributable risk",
        r"sensitivity|specificity|predictive value|prevalence|incidence|likelihood ratio|confidence interval|p[- ]value|type (I|II|1|2) error|\bpower\b",
    ),
}


def lab(pattern):
    r = re.compile(pattern, re.I)
    return np.array([bool(r.search(t)) for t in text])


def scores(C, P_by_pdf, mode="max"):
    out = {}
    for d in PDFS:
        S = C @ P_by_pdf[d].T
        if mode == "max":
            out[d] = S.max(1)
        else:  # top-2 mean
            k = min(2, S.shape[1])
            out[d] = np.sort(S, 1)[:, -k:].mean(1)
    return out


def center(C, P):
    mu_c = C.mean(0)
    mu_p = np.concatenate([P[d] for d in PDFS]).mean(0)
    n = lambda X: X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    return n(C - mu_c), {d: n(P[d] - mu_p) for d in PDFS}


def auc(pos, neg):
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort() + 1
    rp = ranks[: len(pos)].sum()
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


cfgs = {}
for cv in ("A", "B", "C", "D"):
    pth = os.path.join(HERE, f"cards_{cv}.npy")
    if not os.path.exists(pth):
        continue
    C = np.load(pth)
    pv = "A" if cv == "A" else ("P" if cv in "BC" else "N")
    P = {d: np.load(os.path.join(HERE, f"pages_{d}_{pv}.npy")) for d in PDFS}
    cfgs[cv] = (C, P)
    cfgs[cv + "+center"] = center(C, P)

base_scores = scores(*cfgs["A"])
print(f"notes {len(nids)}  cloze {cloze.sum()}")
for lecture, (pp, nn) in TASKS.items():
    pos, neg = lab(pp), lab(nn) & ~lab(pp)
    old_recall = (base_scores[lecture][pos] >= 0.75).mean()
    print(f"\n=== {lecture}: positives {pos.sum()}  hard negatives {neg.sum()}  old recall@0.75 {old_recall:.2f}")
    print(f"{'variant':18} {'AUC':>6} {'thr@=recall':>11} {'FP':>6} {'FP+δ.03':>8} {'recall+δ':>8} {'all matched':>11}")
    for name, (C, P) in cfgs.items():
        for mode in ("max", "top2"):
            s = scores(C, P, mode)
            x = s[lecture]
            thr = np.quantile(x[pos], 1 - old_recall)  # same recall as old@0.75
            best = np.max(np.stack([s[d] for d in PDFS]), 0)
            keep = x >= thr
            keep_d = keep & (x >= best - 0.03)
            print(f"{name+'/'+mode:18} {auc(x[pos], x[neg]):6.3f} {thr:11.3f} {int((keep & neg).sum()):6d}"
                  f" {int((keep_d & neg).sum()):8d} {(keep_d & pos).sum() / pos.sum():8.2f} {int(keep.sum()):11d}")

# lectures-per-card histogram among heme lectures at each variant's equal-recall threshold (B12 anchor)
HEME = [d for d in PDFS if d not in ("Bootcamp.com_Biostatistics", "Measures_of_Disease_Frequency_ELO", "RCTs_and_Measures_of_Asociation")]
print("\n=== heme lectures-per-card histogram (thr from B12 equal-recall; counts of cards matching 1,2,3,4,5,6 heme lectures)")
pos = lab(TASKS["B-12_and_Folate_Deficiency_ELO"][0])
old_recall = (base_scores["B-12_and_Folate_Deficiency_ELO"][pos] >= 0.75).mean()
for name, (C, P) in cfgs.items():
    s = scores(C, P)
    thr = np.quantile(s["B-12_and_Folate_Deficiency_ELO"][pos], 1 - old_recall)
    best = np.max(np.stack([s[d] for d in PDFS]), 0)
    for lbl, delta in (("", None), (" +δ", 0.03)):
        m = np.stack([(s[d] >= thr) & ((s[d] >= best - delta) if delta else True) for d in HEME]).sum(0)
        hist = [int((m == k).sum()) for k in range(1, len(HEME) + 1)]
        print(f"{name+lbl:14} thr {thr:.3f}  {hist}")
