import { useEffect, useState } from "react";
import { Button, Card, ErrorNote, inputCls } from "../components/ui";
import { api } from "../lib/api";

type Field = { key: string; label: string; help?: string; options?: string[] };
const GROUPS: { title: string; fields: Field[] }[] = [
  { title: "Retrieval", fields: [
    { key: "top_k", label: "Vector top-K" },
    { key: "similarity", label: "Similarity", options: ["cosine", "inner_product", "l2"], help: "Only cosine uses the HNSW index." },
    { key: "context_token_budget", label: "Context token budget", help: "Same budget for every mode." },
  ] },
  { title: "Structure routing", fields: [
    { key: "routing_depth", label: "Routing rounds" },
    { key: "toc_initial_depth", label: "Initial ToC depth" },
    { key: "toc_token_budget", label: "ToC token budget" },
    { key: "doc_select_max", label: "Documents before pre-selection" },
    { key: "max_selected_sections", label: "Max selected sections" },
    { key: "include_parent_intro", label: "Include parent intro" },
    { key: "structure_order", label: "Chunk order inside a section", options: ["document", "relevance"],
      help: "relevance sorts each selected section's chunks by query similarity (one extra embedding call)." },
    { key: "structure_fallback", label: "On routing failure", options: ["none", "vector"], help: "Fallback results are labelled fallback_vector." },
  ] },
  { title: "Hybrid fusion", fields: [
    { key: "vector_candidates", label: "Vector candidates" },
    { key: "rrf_k", label: "RRF k" },
    { key: "weight_structure", label: "Structure weight" },
    { key: "weight_vector", label: "Vector weight" },
    { key: "rerank", label: "Reranking", options: ["none", "cross_encoder"], help: "Cross-encoder runs locally (needs the rerank extra)." },
    { key: "rerank_candidates", label: "Rerank candidates" },
  ] },
  { title: "Models and answers", fields: [
    { key: "router_model", label: "Router model" },
    { key: "answer_model", label: "Answer model" },
    { key: "judge_model", label: "Judge / verifier model" },
    { key: "answer_max_tokens", label: "Answer max tokens" },
    { key: "verify_citations", label: "Verify citations by default" },
  ] },
];

export default function Settings() {
  const [s, setS] = useState<any>(null);
  const [cfg, setCfg] = useState<Record<string, any>>({});
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => { api("/settings").then((r) => { setS(r); setCfg(r.config); }).catch(setError); }, []);
  if (!s) return <ErrorNote error={error} />;

  async function save() {
    setError(null); setSaved(false);
    const body = Object.fromEntries(Object.entries(cfg).map(([k, v]) => [k, v === "" ? null : v]));
    try { const r = await api("/settings", { method: "PUT", json: body }); setCfg(r.config); setSaved(true); }
    catch (e) { setError(e); }
  }

  const input = (f: Field) => {
    const v = cfg[f.key];
    const def = s.defaults[f.key];
    if (typeof def === "boolean") return <input type="checkbox" checked={!!v} onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.checked })} />;
    if (f.options) return <select className={inputCls} value={v} onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.value })}>{f.options.map((o) => <option key={o}>{o}</option>)}</select>;
    if (typeof def === "number") return <input className={inputCls} type="number" step="any" value={v} onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.value === "" ? "" : Number(e.target.value) })} />;
    const model = s.models[f.key.replace("_model", "")];
    return <input className={inputCls} placeholder={model ? `default: ${model}` : ""} value={v ?? ""} onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.value })} />;
  };

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold">Settings</h1>
      <Card title="Index (fixed at indexing time)">
        <dl className="grid grid-cols-3 gap-3 text-sm">
          <div><dt className="text-xs text-stone-500">Embedding model</dt><dd>{s.index.embedding_model}</dd></div>
          <div><dt className="text-xs text-stone-500">Dimensions</dt><dd>{s.index.embedding_dim}</dd></div>
          <div><dt className="text-xs text-stone-500">Chunk max tokens</dt><dd>{s.index.chunk_max_tokens}</dd></div>
        </dl>
        <p className="mt-2 text-xs text-stone-500">Changing these needs an environment change, a migration for the vector size, and a re-index.</p>
      </Card>
      {GROUPS.map((g) => (
        <Card key={g.title} title={g.title}>
          <div className="grid gap-3 sm:grid-cols-2">
            {g.fields.map((f) => (
              <label key={f.key} className="block text-sm">
                <span className="mb-1 block text-xs text-stone-600 dark:text-stone-400">{f.label}</span>
                {input(f)}
                {f.help && <span className="mt-0.5 block text-xs text-stone-500">{f.help}</span>}
              </label>
            ))}
          </div>
        </Card>
      ))}
      <ErrorNote error={error} />
      <div className="flex items-center gap-3">
        <Button onClick={save}>Save settings</Button>
        <Button variant="ghost" onClick={() => setCfg(s.defaults)}>Reset to defaults</Button>
        {saved && <span className="text-sm text-stone-500">Saved.</span>}
      </div>
    </div>
  );
}
