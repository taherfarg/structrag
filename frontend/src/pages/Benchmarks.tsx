import { Fragment, useCallback, useEffect, useState } from "react";
import ModeChart, { type Agg } from "../components/ModeChart";
import { Badge, Button, Card, ErrorNote, inputCls, ModeTag } from "../components/ui";
import { api, fmt, MODES, type Mode } from "../lib/api";

type Dataset = { id: string; name: string; version: string; queries: number; corpus: string[] };
type Summary = {
  modes: Record<string, Record<string, Agg> & { total_cost_usd?: any }>; by_tag: Record<string, Record<string, Record<string, Agg>>>;
  judge_cost_usd: number | null; errors?: Record<string, number>; complete?: boolean;
};
type Run = {
  id: string; label: string | null; modes: string[]; status: string; error: string | null; config_hash: string;
  summary: Summary | null; created_at: string; finished_at: string | null; dataset_name: string; dataset_version: string; results: number;
};
type Result = {
  mode: string; qid: string; question: string; expected_answer: string | null; answerable: boolean; tags: string[];
  metrics: Record<string, number | null>; answer: any; retrieved: { ranked_sections: string[]; gold: string[]; evidence: any[] };
  error: any;
};

const RETRIEVAL = [
  { label: "Hit@1", key: "hit@1" }, { label: "Hit@3", key: "hit@3" }, { label: "Recall@5", key: "recall@5" },
  { label: "Precision@3", key: "precision@3" }, { label: "MRR", key: "mrr" }, { label: "nDCG@5", key: "ndcg@5" },
];
const ANSWER = [
  { label: "Correctness", key: "correctness" }, { label: "Faithfulness", key: "faithfulness" },
  { label: "Citation support", key: "citation_support" }, { label: "Abstention acc.", key: "abstention_correct" },
  { label: "Unsupported claims", key: "unsupported_claim_rate" },
];
const LATENCY = [
  { label: "Retrieval p50", key: "retrieval_latency_ms", stat: "p50" as const }, { label: "Retrieval p95", key: "retrieval_latency_ms", stat: "p95" as const },
  { label: "End-to-end p50", key: "total_latency_ms", stat: "p50" as const }, { label: "End-to-end p95", key: "total_latency_ms", stat: "p95" as const },
];

function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<(Run & { manifest: any; config: any; results: Result[] }) | null>(null);
  const [tag, setTag] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { api(`/benchmarks/${id}`).then(setRun); }, [id]);
  if (!run) return null;
  if (!run.summary) return <Card title="Run"><p className="text-sm">Status: {run.status} {run.error && <span className="text-red-700">{run.error}</span>}</p></Card>;
  const modes = MODES.filter((m) => run.modes.includes(m));
  const tags = ["all", ...new Set(Object.values(run.summary.by_tag).flatMap((t) => Object.keys(t)))];
  const data = tag === "all" ? run.summary.modes : Object.fromEntries(modes.map((m) => [m, run.summary!.by_tag[m]?.[tag] ?? {}]));
  const queries = [...new Map(run.results.map((r) => [r.qid, r])).values()]
    .filter((q) => tag === "all" || q.tags.includes(tag) || (tag === "unanswerable" && !q.answerable));
  const byQ = (qid: string, m: string) => run.results.find((r) => r.qid === qid && r.mode === m);

  return (
    <div className="space-y-4">
      <Card title={`${run.label ?? "Run"} · ${run.dataset_name}@${run.dataset_version}`}
            actions={<span className="text-xs text-stone-500">config {run.config_hash} · {run.manifest.dataset.queries} queries{run.manifest.fake_llm && " · FAKE LLM"}</span>}>
        {run.summary.complete === false && (
          <p role="alert" className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Incomplete run: failed queries per mode {JSON.stringify(run.summary.errors)}. Quality metrics cover only the
            queries that ran, so compare modes with care.
          </p>
        )}
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-stone-500">Question type</span>
          {tags.map((t) => (
            <button key={t} onClick={() => setTag(t)}
                    className={`rounded-full px-2.5 py-0.5 text-xs ${tag === t ? "bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900" : "bg-stone-100 dark:bg-stone-800"}`}>{t}</button>
          ))}
        </div>
        <div className="grid gap-6 lg:grid-cols-2">
          <ModeChart title="Retrieval quality (section level)" rows={RETRIEVAL} modes={modes} data={data} domain={[0, 1]} />
          <ModeChart title="Answer quality (LLM-judged)" rows={ANSWER} modes={modes} data={data} domain={[0, 1]} />
          <ModeChart title="Latency (ms)" rows={LATENCY} modes={modes} data={data} kind="ms" />
          <ModeChart title="Cost per query (USD, excludes judge)" rows={[{ label: "Mean", key: "cost_usd" }, { label: "p95", key: "cost_usd", stat: "p95" }]} modes={modes} data={data} kind="usd" />
        </div>
        <p className="mt-3 text-xs text-stone-500">
          Metrics with fewer measured values than questions show (measured/n): unanswerable questions have no retrieval
          metrics, and abstentions have no faithfulness. Judge cost for the run: {fmt(run.summary.judge_cost_usd, "usd")}.
          Models: router {run.config.router_model}, answer {run.config.answer_model}, judge {run.config.judge_model}.
        </p>
      </Card>
      <Card title={`Per-question results (${queries.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-stone-500">
              <tr><th className="py-1 pr-2 font-medium">Question</th>
                {modes.map((m) => <th key={m} className="pr-2 font-medium"><ModeTag mode={m} /><div className="font-normal">hit@3 · correct</div></th>)}</tr>
            </thead>
            <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
              {queries.map((q) => (
                <Fragment key={q.qid}>
                  <tr className="cursor-pointer align-top hover:bg-stone-50 dark:hover:bg-stone-800/40" onClick={() => setOpen(open === q.qid ? null : q.qid)}>
                    <td className="py-1.5 pr-2"><b>{q.qid}</b> {q.question} <span className="text-stone-500">{q.tags.join(", ")}{!q.answerable && " unanswerable"}</span></td>
                    {modes.map((m) => {
                      const r = byQ(q.qid, m);
                      return <td key={m} className="pr-2 tabular-nums">{r?.error ? <Badge tone="bad">{r.error.code}</Badge> : `${fmt(r?.metrics["hit@3"])} · ${fmt(r?.metrics.correctness)}`}</td>;
                    })}
                  </tr>
                  {open === q.qid && (
                    <tr><td colSpan={modes.length + 1} className="pb-3">
                      {q.expected_answer && <p className="mb-2"><span className="text-stone-500">Expected:</span> {q.expected_answer}</p>}
                      <div className="grid gap-3 lg:grid-cols-3">
                        {modes.map((m) => {
                          const r = byQ(q.qid, m);
                          const gold = new Set(r?.retrieved.gold ?? []);
                          return (
                            <div key={m} className="rounded border border-stone-200 p-2 dark:border-stone-800">
                              <ModeTag mode={m} />
                              <p className="my-1">{r?.answer?.answer ?? r?.error?.message}</p>
                              <ol className="list-decimal pl-4 text-stone-600 dark:text-stone-400">
                                {r?.retrieved.evidence.map((e: any) => (
                                  <li key={e.chunk_id} className={gold.has(e.section_id) ? "font-semibold text-stone-900 dark:text-stone-100" : ""}>
                                    {e.heading_path.join(" › ") || "(intro)"}
                                  </li>
                                ))}
                              </ol>
                            </div>
                          );
                        })}
                      </div>
                      <p className="mt-1 text-stone-500">Bold evidence comes from a gold section.</p>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function LiveAnalytics() {
  const [a, setA] = useState<any>(null);
  useEffect(() => { api("/analytics?days=30").then(setA).catch(() => setA(null)); }, []);
  if (!a) return null;
  return (
    <Card title="Live traffic, last 30 days (playground and API)">
      <div className="grid gap-6 lg:grid-cols-2">
        <table className="w-full text-xs tabular-nums">
          <thead className="text-stone-500"><tr><th className="text-left font-medium">mode</th><th className="text-right font-medium">queries</th>
            <th className="text-right font-medium">retrieval p50/p95</th><th className="text-right font-medium">total p50/p95</th><th className="text-right font-medium">avg cost</th></tr></thead>
          <tbody>{a.modes.map((m: any) => (
            <tr key={m.mode}><td><ModeTag mode={m.mode} /></td><td className="text-right">{m.queries}</td>
              <td className="text-right">{fmt(m.retrieval_p50_ms, "ms")} / {fmt(m.retrieval_p95_ms, "ms")}</td>
              <td className="text-right">{fmt(m.total_p50_ms, "ms")} / {fmt(m.total_p95_ms, "ms")}</td>
              <td className="text-right">{fmt(m.avg_cost_usd, "usd")}</td></tr>))}</tbody>
        </table>
        <table className="w-full text-xs tabular-nums">
          <thead className="text-stone-500"><tr><th className="text-left font-medium">purpose</th><th className="text-left font-medium">model</th>
            <th className="text-right font-medium">calls</th><th className="text-right font-medium">tokens in/out</th><th className="text-right font-medium">cost</th></tr></thead>
          <tbody>{a.spend.map((s: any) => (
            <tr key={s.purpose + s.model}><td>{s.purpose}</td><td className="truncate">{s.model}</td><td className="text-right">{s.calls}</td>
              <td className="text-right">{s.input_tokens}/{s.output_tokens}</td>
              <td className="text-right">{fmt(s.cost_usd, "usd")}{s.cost_unknown > 0 && ` (+${s.cost_unknown} unpriced)`}</td></tr>))}</tbody>
        </table>
        <table className="w-full text-xs tabular-nums lg:col-span-2">
          <thead className="text-stone-500"><tr><th className="text-left font-medium">index footprint</th><th className="text-right font-medium">sections</th>
            <th className="text-right font-medium">chunks</th><th className="text-right font-medium">stored</th><th className="text-right font-medium">parse / embed / store</th></tr></thead>
          <tbody>{a.index.map((d: any) => (
            <tr key={d.id}><td>{d.filename}</td><td className="text-right">{d.sections}</td><td className="text-right">{d.chunks}</td>
              <td className="text-right">{(d.stored_bytes / 1024).toFixed(0)} KB</td>
              <td className="text-right">{fmt(d.timings?.parse_ms, "ms")} / {fmt(d.timings?.embed_ms, "ms")} / {fmt(d.timings?.store_ms, "ms")}</td></tr>))}</tbody>
        </table>
      </div>
    </Card>
  );
}

export default function Benchmarks() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [form, setForm] = useState({ dataset_id: "", label: "", judge: true, modes: [...MODES] as Mode[] });
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      const [d, r] = await Promise.all([api<Dataset[]>("/eval/datasets"), api<Run[]>("/benchmarks")]);
      setDatasets(d); setRuns(r);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const active = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [active, load]);

  async function uploadDataset(f: File | undefined) {
    if (!f) return;
    try { await api("/eval/datasets", { method: "POST", json: JSON.parse(await f.text()) }); await load(); }
    catch (e) { setError(e); }
  }
  async function start() {
    setError(null);
    try {
      const r = await api("/benchmarks", { method: "POST", json: { ...form, label: form.label || null } });
      setSel(r.id); await load();
    } catch (e) { setError(e); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Benchmarks</h1>
      <ErrorNote error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Datasets" actions={
          <label className="cursor-pointer text-xs text-stone-600 underline dark:text-stone-300">Upload JSON
            <input type="file" accept=".json" className="sr-only" onChange={(e) => uploadDataset(e.target.files?.[0])} /></label>}>
          <ul className="space-y-1 text-sm">
            {datasets.map((d) => <li key={d.id}><b>{d.name}</b>@{d.version} · {d.queries} questions · corpus {d.corpus.length} files</li>)}
            {!datasets.length && <li className="text-stone-500">No datasets yet. See eval/dataset.json for the format.</li>}
          </ul>
        </Card>
        <Card title="Start a run">
          <div className="space-y-2 text-sm">
            <select className={inputCls} value={form.dataset_id} onChange={(e) => setForm({ ...form, dataset_id: e.target.value })}>
              <option value="">Choose a dataset</option>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}@{d.version}</option>)}
            </select>
            <input className={inputCls} placeholder="Label (optional)" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
            <div className="flex flex-wrap items-center gap-3">
              {MODES.map((m) => (
                <label key={m} className="flex items-center gap-1.5">
                  <input type="checkbox" checked={form.modes.includes(m)} onChange={(e) =>
                    setForm({ ...form, modes: e.target.checked ? MODES.filter((x) => x === m || form.modes.includes(x)) : form.modes.filter((x) => x !== m) })} />
                  <ModeTag mode={m} /></label>
              ))}
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.judge} onChange={(e) => setForm({ ...form, judge: e.target.checked })} />LLM judge</label>
            </div>
            <p className="text-xs text-stone-500">Uses your saved settings. Real model calls; cost scales with questions × modes.</p>
            <Button disabled={!form.dataset_id || !form.modes.length} onClick={start}>Run benchmark</Button>
          </div>
        </Card>
      </div>
      <Card title="Runs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-stone-500"><tr><th className="py-1 font-medium">Run</th><th className="font-medium">Dataset</th><th className="font-medium">Status</th>
              <th className="font-medium">Modes</th><th className="font-medium">Config</th><th className="text-right font-medium">Results</th><th className="font-medium">Started</th></tr></thead>
            <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
              {runs.map((r) => (
                <tr key={r.id} onClick={() => setSel(r.id)} className={`cursor-pointer ${sel === r.id ? "bg-stone-100 dark:bg-stone-800" : "hover:bg-stone-50 dark:hover:bg-stone-800/40"}`}>
                  <td className="py-1.5">{r.label ?? r.id.slice(0, 8)}</td><td>{r.dataset_name}@{r.dataset_version}</td>
                  <td><Badge tone={r.status === "done" ? "good" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Badge>
                    {r.error && <span className="ml-1 text-red-700 dark:text-red-300" title={r.error}>{r.error.slice(0, 60)}</span>}</td>
                  <td>{r.modes.join(", ")}</td><td><code>{r.config_hash}</code></td><td className="text-right tabular-nums">{r.results}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {sel && runs.find((r) => r.id === sel)?.status === "done" && <RunDetail key={sel} id={sel} />}
      <LiveAnalytics />
    </div>
  );
}
