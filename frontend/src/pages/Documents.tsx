import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, ErrorNote } from "../components/ui";
import { api, fmt } from "../lib/api";

export type Doc = {
  id: string; title: string; filename: string; status: string; version: number; parse_method: string | null;
  parse_confidence: number | null; page_count: number | null; error: string | null; size_bytes: number;
  section_count: number; chunk_count: number; timings: Record<string, number>; created_at: string;
  metadata: { parse_warnings?: string[] };
};

const tone = (s: string) => (s === "ready" ? "good" : s === "failed" ? "bad" : "warn") as "good" | "bad" | "warn";

export default function Documents() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api<Doc[]>("/documents").then(setDocs).catch(setError), []);
  useEffect(() => { load(); }, [load]);
  // Poll only while something is still being indexed.
  const busy = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [busy, load]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true); setError(null);
    try {
      for (const f of Array.from(files)) {
        const body = new FormData();
        body.append("file", f);
        await api("/documents", { method: "POST", body });
      }
      await load();
    } catch (e) { setError(e); }
    setUploading(false);
    if (input.current) input.current.value = "";
  }

  async function act(d: Doc, kind: "reindex" | "delete") {
    if (kind === "delete" && !confirm(`Delete ${d.filename}? Its sections, chunks and stored file are removed.`)) return;
    try {
      await api(kind === "delete" ? `/documents/${d.id}` : `/documents/${d.id}/reindex`, {
        method: kind === "delete" ? "DELETE" : "POST",
      });
      await load();
    } catch (e) { setError(e); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Documents</h1>
      <Card title="Upload" actions={<span className="text-xs text-stone-500">PDF, DOCX, Markdown, text · up to 50 MB</span>}>
        <label
          className="flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-stone-300 px-4 py-6 text-sm text-stone-600 hover:bg-stone-50 dark:border-stone-700 dark:text-stone-400 dark:hover:bg-stone-800/50"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}>
          {uploading ? "Uploading…" : "Drop files here or click to choose"}
          <input ref={input} type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt" className="sr-only"
                 onChange={(e) => upload(e.target.files)} />
        </label>
      </Card>
      <ErrorNote error={error} />
      <Card title={`${docs.length} documents`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-stone-500">
              <tr>
                <th className="py-2 pr-3 font-medium">Document</th><th className="pr-3 font-medium">Status</th>
                <th className="pr-3 font-medium">Parsing</th><th className="pr-3 font-medium">Confidence</th>
                <th className="pr-3 text-right font-medium">Sections</th><th className="pr-3 text-right font-medium">Chunks</th>
                <th className="pr-3 text-right font-medium">Index time</th><th />
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
              {docs.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="py-2 pr-3">
                    <Link to={`/structure/${d.id}`} className="font-medium hover:underline">{d.title}</Link>
                    <div className="text-xs text-stone-500">{d.filename} · v{d.version}{d.page_count ? ` · ${d.page_count} pages` : ""}</div>
                    {d.error && <div className="mt-1 max-w-md text-xs text-red-700 dark:text-red-300">{d.error}</div>}
                    {d.metadata.parse_warnings?.map((w) => <div key={w} className="text-xs text-amber-700 dark:text-amber-300">{w}</div>)}
                  </td>
                  <td className="pr-3"><Badge tone={tone(d.status)}>{d.status}</Badge></td>
                  <td className="pr-3 text-xs text-stone-600 dark:text-stone-400">{d.parse_method ?? "–"}</td>
                  <td className="pr-3 tabular-nums">{fmt(d.parse_confidence)}</td>
                  <td className="pr-3 text-right tabular-nums">{d.section_count}</td>
                  <td className="pr-3 text-right tabular-nums">{d.chunk_count}</td>
                  <td className="pr-3 text-right tabular-nums">{fmt(d.timings?.total_ms, "ms")}</td>
                  <td className="space-x-1 whitespace-nowrap text-right">
                    <Button variant="ghost" onClick={() => act(d, "reindex")}>Re-index</Button>
                    <Button variant="danger" onClick={() => act(d, "delete")}>Delete</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
