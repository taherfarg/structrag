"""Section-level retrieval metrics and answer metrics.

`None` means "could not be measured"; `0.0` means "measured, and it was zero".
They are never interchanged, and aggregates report how many values were measured.

Relevance: a retrieved section is relevant if it is a gold section or lies
inside one (gold labelled at "Engine" accepts evidence from "Engine > Warranty").
For MRR and nDCG a section only earns gain the first time it covers a given
gold item, so several subsections of one gold section cannot push nDCG past 1.
"""

import math
import statistics

VERDICT = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0}


def retrieval_metrics(ranked: list[str], gold: list[str], ancestors: dict[str, set[str]],
                      ks: list[int]) -> dict[str, float | None]:
    if not gold:
        return {f"{m}@{k}": None for k in ks for m in ("hit", "recall", "precision", "ndcg")} | {"mrr": None}
    gold_set = set(gold)

    def covers(sid: str) -> set[str]:
        return ({sid} | ancestors.get(sid, set())) & gold_set

    relevant = [bool(covers(s)) for s in ranked]
    gains, covered = [], set()
    for s in ranked:
        new = covers(s) - covered
        gains.append(1.0 if new else 0.0)
        covered |= new

    out: dict[str, float | None] = {}
    for k in ks:
        top_cov = set().union(*(covers(s) for s in ranked[:k])) if ranked[:k] else set()
        out[f"hit@{k}"] = 1.0 if any(relevant[:k]) else 0.0
        out[f"recall@{k}"] = len(top_cov) / len(gold_set)
        out[f"precision@{k}"] = sum(relevant[:k]) / k
        dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
        idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold_set), k)))
        out[f"ndcg@{k}"] = dcg / idcg
    first = next((i for i, g in enumerate(gains) if g), None)
    out["mrr"] = 1.0 / (first + 1) if first is not None else 0.0
    return out


def answer_metrics(answerable: bool, abstained: bool, correctness: float | None,
                   claims: list[dict], verdicts: list[dict] | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {
        "abstention_correct": 1.0 if abstained != answerable else 0.0,
        # An abstention on an answerable question is a wrong answer, measured as 0.
        "correctness": (0.0 if abstained else correctness) if answerable else None,
        "faithfulness": None, "citation_support": None, "unsupported_claim_rate": None,
        "claims": float(len(claims)),
    }
    if not claims or verdicts is None:
        return out  # nothing asserted (or not judged): grounding is not measurable, not zero
    by = {v["claim_index"]: v for v in verdicts}
    judged = [by[i] for i in range(len(claims)) if i in by]
    if judged:
        out["faithfulness"] = statistics.fmean(VERDICT[v["context_support"]] for v in judged)
        cited = [VERDICT[v["cited_support"]] for v in judged if v["cited_support"] != "no_citation"]
        out["citation_support"] = statistics.fmean(cited) if cited else None
        out["unsupported_claim_rate"] = statistics.fmean(
            1.0 if v["cited_support"] == "no_citation" or v["context_support"] == "unsupported" else 0.0
            for v in judged)
    return out


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = (len(s) - 1) * p
    lo, hi = math.floor(idx), math.ceil(idx)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def aggregate(rows: list[dict]) -> dict[str, dict]:
    """rows: per-query metric dicts -> {metric: {mean, p50, p95, measured, n}}."""
    keys = sorted({k for r in rows for k in r})
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = {"mean": statistics.fmean(vals) if vals else None, "p50": percentile(vals, 0.5),
                  "p95": percentile(vals, 0.95), "measured": len(vals), "n": len(rows)}
    return out
