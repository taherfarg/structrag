import { useState } from "react";
import { Badge, Button, Card, ErrorNote, inputCls, ModeTag, Stat } from "../components/ui";
import { api, fmt, MODES, type Mode } from "../lib/api";

type Evidence = {
  rank: number; chunk_id: string; section_id: string; filename: string; heading_path: string[]; page: number | null;
  text: string; token_count: number; score: number | null; provenance: Record<string, any>;
};
type Verdict = { claim_index: number; cited_support: string; context_support: string; rationale: string };
type ModeResult = {
  mode: Mode;
  error: { code: string; message: string; trace?: any } | null;
  retrieval: { evidence: Evidence[]; ranked_sections: string[]; latency_ms: number; trace: any } | null;
  answer: {
    answer: string; insufficient_evidence: boolean; claims: { text: string; evidence_ids: string[] }[];
    citations: { evidence_id: string; filename: string; heading_path: string[]; page: number | null }[];
    invalid_citations: string[]; uncited_claims: number; verification: Verdict[] | null; verification_error: string | null;
  } | null;
  retrieval_latency_ms: number | null; total_latency_ms: number;
  usage: { calls: number; input_tokens: number; output_tokens: number; cost_usd: number | null };
};

const supportTone = (s: string) => (s === "supported" ? "good" : s === "partial" ? "warn" : "bad") as "good" | "warn" | "bad";

function Answer({ r, onCite }: { r: ModeResult; onCite: (rank: number) => void }) {
  const a = r.answer!;
  // Inline [E3] markers become buttons that highlight the evidence they point at.
  const parts = a.answer.split(/(\[E\d+\])/g);
  return (
    <div className="space-y-2">
      {a.insufficient_evidence && <Badge tone="warn">insufficient evidence</Badge>}
      <p className="text-sm leading-relaxed">
        {parts.map((p, i) => /^\[E\d+\]$/.test(p)
          ? <button key={i} onClick={() => onCite(Number(p.slice(2, -1)))} className="mx-0.5 rounded bg-stone-200 px-1 text-xs font-medium hover:bg-stone-300 dark:bg-stone-700 dark:hover:bg-stone-600">{p.slice(1, -1)}</button>
          : <span key={i}>{p}</span>)}
      </p>
      {a.citations.length > 0 && (
        <ul className="space-y-0.5 text-xs text-stone-600 dark:text-stone-400">
          {a.citations.map((c) => (
            <li key={c.evidence_id}><b>{c.evidence_id}</b> {c.filename} › {c.heading_path.join(" › ") || "(introduction)"}{c.page ? `, p.${c.page}` : ""}</li>
          ))}
        </ul>
      )}
      {(a.invalid_citations.length > 0 || a.uncited_claims > 0) && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          {a.invalid_citations.length > 0 && `Invalid citations dropped: ${a.invalid_citations.join(", ")}. `}
          {a.uncited_claims > 0 && `${a.uncited_claims} claim(s) without a citation.`}
        </p>
      )}
      {a.verification && (
        <details className="text-xs">
          <summary className="cursor-pointer text-stone-500">Claim verification ({a.verification.length})</summary>
          <ol className="mt-1 space-y-1">
            {a.verification.map((v) => (
              <li key={v.claim_index}>
                <div>{a.claims[v.claim_index]?.text}</div>
                <div className="flex flex-wrap gap-1"><Badge tone={supportTone(v.cited_support)}>cited: {v.cited_support}</Badge>
                  <Badge tone={supportTone(v.context_support)}>context: {v.context_support}</Badge></div>
                <div className="text-stone-500">{v.rationale}</div>
              </li>
            ))}
          </ol>
        </details>
      )}
      {a.verification_error && <p className="text-xs text-amber-700 dark:text-amber-300">Verification failed: {a.verification_error}</p>}
    </div>
  );
}

function Routing({ trace }: { trace: any }) {
  const routing = trace?.routing ?? trace;
  if (!routing?.rounds && !trace?.fallback && !trace?.structure_error) return null;
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-stone-500">Routing trace</summary>
      <div className="mt-1 space-y-1">
        {trace?.fallback && <Badge tone="warn">fell back to vector: {trace.fallback_reason}</Badge>}
        {trace?.structure_error && <Badge tone="warn">structure failed: {trace.structure_error}</Badge>}
        {routing?.document_selection && <div>Documents chosen {routing.document_selection.selected.length}/{routing.document_selection.candidates}</div>}
        {routing?.rounds?.map((r: any) => (
          <div key={r.round} className="rounded border border-stone-200 p-1.5 dark:border-stone-800">
            <div>Round {r.round}: {r.selected.length} selected, {r.expand.length} expanded, {r.shown} shown
              {r.invalid.length > 0 && <span className="text-red-700 dark:text-red-300"> · invalid ids: {r.invalid.join(", ")}</span>}</div>
            <div className="text-stone-500">confidence {r.confidence} (model-reported) — {r.reason}</div>
          </div>
        ))}
      </div>
    </details>
  );
}

function EvidenceList({ items, highlight }: { items: Evidence[]; highlight: number | null }) {
  return (
    <ol className="space-y-2">
      {items.map((e) => {
        const p = e.provenance;
        const sources: string[] = p.sources ?? [p.source];
        return (
          <li key={e.chunk_id} id={`ev-${e.chunk_id}`}
              className={`rounded-md border p-2 text-xs ${highlight === e.rank ? "border-stone-900 dark:border-stone-100" : "border-stone-200 dark:border-stone-800"}`}>
            <div className="mb-1 flex flex-wrap items-center gap-1">
              <b>E{e.rank}</b>
              {sources.map((s) => <Badge key={s}>{s}</Badge>)}
              {p.vector_rank && <span className="text-stone-500">vec #{p.vector_rank}</span>}
              {p.structure_rank && <span className="text-stone-500">struct #{p.structure_rank}</span>}
              {e.score !== null && <span className="tabular-nums text-stone-500">score {e.score.toFixed(4)}</span>}
              {p.rerank_score !== undefined && <span className="text-stone-500">rerank {p.rerank_score}</span>}
            </div>
            <div className="mb-1 font-medium">{e.filename} › {e.heading_path.join(" › ") || "(introduction)"}{e.page ? ` · p.${e.page}` : ""}</div>
            <p className="line-clamp-4 whitespace-pre-wrap text-stone-700 dark:text-stone-300" title={e.text}>{e.text}</p>
          </li>
        );
      })}
    </ol>
  );
}

function Column({ r }: { r: ModeResult }) {
  const [hl, setHl] = useState<number | null>(null);
  return (
    <Card title={<ModeTag mode={r.mode} />} className="min-w-0">
      <div className="mb-3 grid grid-cols-3 gap-3">
        <Stat label="Retrieval" value={fmt(r.retrieval_latency_ms, "ms")} />
        <Stat label="End to end" value={fmt(r.total_latency_ms, "ms")} />
        <Stat label="Cost" value={fmt(r.usage.cost_usd, "usd")} />
        <Stat label="Tokens in / out" value={`${r.usage.input_tokens} / ${r.usage.output_tokens}`} />
        <Stat label="LLM calls" value={r.usage.calls} />
        <Stat label="Evidence" value={r.retrieval ? `${r.retrieval.evidence.length} chunks · ${r.retrieval.ranked_sections.length} sections` : "–"} />
      </div>
      {r.error && <ErrorNote error={`${r.error.code}: ${r.error.message}`} />}
      {r.error?.trace && <Routing trace={r.error.trace} />}
      {r.answer && <div className="mb-3 border-b border-stone-100 pb-3 dark:border-stone-800"><Answer r={r} onCite={setHl} /></div>}
      {r.retrieval && <div className="mb-3"><Routing trace={r.retrieval.trace} /></div>}
      {r.retrieval && <EvidenceList items={r.retrieval.evidence} highlight={hl} />}
    </Card>
  );
}

export default function Playground() {
  const [query, setQuery] = useState("");
  const [modes, setModes] = useState<Mode[]>([...MODES]);
  const [verify, setVerify] = useState(false);
  const [results, setResults] = useState<Record<string, ModeResult> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true); setError(null);
    try {
      setResults(await api("/ask", { method: "POST", json: { query, modes, config: { verify_citations: verify } } }));
    } catch (e) { setError(e); }
    setBusy(false);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">RAG playground</h1>
      <Card>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (query.trim()) run(); }}>
          <textarea className={`${inputCls} min-h-20`} placeholder="Ask a question about your documents"
                    value={query} onChange={(e) => setQuery(e.target.value)} />
          <div className="flex flex-wrap items-center gap-4 text-sm">
            {MODES.map((m) => (
              <label key={m} className="flex items-center gap-1.5">
                <input type="checkbox" checked={modes.includes(m)}
                       onChange={(e) => setModes(e.target.checked ? MODES.filter((x) => x === m || modes.includes(x)) : modes.filter((x) => x !== m))} />
                <ModeTag mode={m} />
              </label>
            ))}
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />verify citations</label>
            <Button type="submit" disabled={busy || !modes.length || !query.trim()}>{busy ? "Running…" : "Compare"}</Button>
          </div>
          <p className="text-xs text-stone-500">Modes run concurrently here, so latencies include contention. Benchmarks run one query at a time.</p>
        </form>
      </Card>
      <ErrorNote error={error} />
      {results && (
        <div className="grid gap-4 xl:grid-cols-3">
          {MODES.filter((m) => results[m]).map((m) => <Column key={m} r={results[m]} />)}
        </div>
      )}
    </div>
  );
}
