import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Badge, Card, ErrorNote, inputCls, Stat } from "../components/ui";
import { api } from "../lib/api";
import type { Doc } from "./Documents";

type Node = {
  id: string; heading: string; level: number; page: number | null; page_end: number | null; path: string[];
  token_count: number; chunk_count: number; heading_source: string; children: Node[];
};
type Section = {
  id: string; heading: string; path: string[]; content: string; page_start: number | null; page_end: number | null;
  token_count: number; heading_source: string;
  chunks: { id: string; ordinal: number; text: string; page: number | null; token_count: number }[];
};

function TreeNode({ n, sel, onSelect }: { n: Node; sel: string | null; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(n.level < 2);
  return (
    <li>
      <div className={`flex items-center gap-1 rounded px-1 py-0.5 text-sm ${sel === n.id ? "bg-stone-200 dark:bg-stone-800" : "hover:bg-stone-100 dark:hover:bg-stone-800/60"}`}>
        <button className="w-4 text-xs text-stone-500" aria-label={open ? "Collapse" : "Expand"}
                onClick={() => setOpen(!open)} disabled={!n.children.length}>
          {n.children.length ? (open ? "▾" : "▸") : ""}
        </button>
        <button className="min-w-0 flex-1 truncate text-left" onClick={() => onSelect(n.id)} title={n.heading}>
          {n.level === 0 ? <em>{n.heading} (intro)</em> : n.heading}
        </button>
        <span className="shrink-0 text-xs tabular-nums text-stone-500">{n.page ? `p.${n.page}` : ""}</span>
      </div>
      {open && n.children.length > 0 && (
        <ul className="ml-4 border-l border-stone-200 pl-1 dark:border-stone-800">
          {n.children.map((c) => <TreeNode key={c.id} n={c} sel={sel} onSelect={onSelect} />)}
        </ul>
      )}
    </li>
  );
}

export default function Structure() {
  const { docId } = useParams();
  const nav = useNavigate();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [tree, setTree] = useState<{ title: string; parse_method: string; parse_confidence: number; sections: Node[] } | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [section, setSection] = useState<Section | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => { api<Doc[]>("/documents").then(setDocs).catch(setError); }, []);
  useEffect(() => {
    if (!docId) return;
    setTree(null); setSection(null); setSel(null);
    api(`/documents/${docId}/structure`).then(setTree).catch(setError);
  }, [docId]);
  useEffect(() => {
    if (sel) api<Section>(`/sections/${sel}`).then(setSection).catch(setError);
  }, [sel]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Structure explorer</h1>
        <select className={`${inputCls} max-w-xs`} value={docId ?? ""} onChange={(e) => nav(`/structure/${e.target.value}`)}>
          <option value="" disabled>Choose a document</option>
          {docs.filter((d) => d.status === "ready").map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
        </select>
      </div>
      <ErrorNote error={error} />
      {tree && (
        <div className="grid gap-4 lg:grid-cols-[minmax(260px,380px)_1fr]">
          <Card title="Headings" actions={<span className="text-xs text-stone-500">{tree.parse_method} · confidence {tree.parse_confidence}</span>}>
            <ul className="max-h-[70vh] overflow-auto">
              {tree.sections.map((n) => <TreeNode key={n.id} n={n} sel={sel} onSelect={setSel} />)}
            </ul>
          </Card>
          <Card title={section ? (section.path.join(" › ") || `${tree.title} (introduction)`) : "Select a section"}>
            {section && (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-6">
                  <Stat label="Section id" value={<code className="text-xs">{section.id}</code>} />
                  <Stat label="Pages" value={section.page_start ? `${section.page_start}–${section.page_end}` : "–"} />
                  <Stat label="Own tokens" value={section.token_count} />
                  <Stat label="Heading from" value={<Badge>{section.heading_source}</Badge>} />
                </div>
                <div>
                  <h3 className="mb-1 text-xs font-medium text-stone-500">Chunks ({section.chunks.length})</h3>
                  {section.chunks.length === 0 && <p className="text-sm text-stone-500">This section has no text of its own; its content is in its subsections.</p>}
                  <ol className="space-y-2">
                    {section.chunks.map((c) => (
                      <li key={c.id} className="rounded-md border border-stone-200 p-3 dark:border-stone-800">
                        <div className="mb-1 text-xs text-stone-500">#{c.ordinal} · {c.token_count} tokens{c.page ? ` · p.${c.page}` : ""} · <code>{c.id}</code></div>
                        <p className="whitespace-pre-wrap text-sm">{c.text}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
