import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt, modeColor } from "../lib/api";

export type Agg = { mean: number | null; p50: number | null; p95: number | null; measured: number; n: number };
export type Row = { label: string; key: string; stat?: "mean" | "p50" | "p95" };

type Props = {
  title: string;
  rows: Row[];                                   // one category per metric
  modes: string[];
  data: Record<string, Record<string, Agg | undefined>>; // mode -> metric -> aggregate
  kind?: "num" | "ms" | "usd";
  domain?: [number, number];
};

/** Grouped bars: metrics on x, one fixed-colour series per mode, plus the same numbers as a table. */
export default function ModeChart({ title, rows, modes, data, kind = "num", domain }: Props) {
  const chartRows = rows.map((r) => {
    const out: Record<string, any> = { label: r.label };
    for (const m of modes) out[m] = data[m]?.[r.key]?.[r.stat ?? "mean"] ?? null;
    return out;
  });
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 text-sm font-semibold">{title}</figcaption>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartRows} barGap={2} barCategoryGap="22%" margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="label" tick={{ fill: "var(--ink-2)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--grid)" }} />
            <YAxis domain={domain} tick={{ fill: "var(--ink-2)", fontSize: 11 }} tickLine={false} axisLine={false} width={48}
                   tickFormatter={(v) => (kind === "ms" ? `${Math.round(v)}` : kind === "usd" ? v.toPrecision(2) : String(v))} />
            <Tooltip cursor={{ fill: "var(--grid)", opacity: 0.4 }}
                     content={({ active, payload, label }) => active && payload?.length ? (
                       <div className="rounded-md border border-stone-200 bg-white px-2.5 py-1.5 text-xs shadow-sm dark:border-stone-700 dark:bg-stone-900">
                         <div className="mb-1 font-medium">{label}</div>
                         {payload.map((p) => (
                           <div key={String(p.dataKey)} className="flex items-center gap-1.5">
                             <span className="h-2 w-2 rounded-sm" style={{ background: modeColor(String(p.dataKey)) }} />
                             <b className="tabular-nums">{fmt(p.value as number, kind)}</b> <span className="text-stone-500">{String(p.dataKey)}</span>
                           </div>
                         ))}
                       </div>) : null} />
            <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
            {modes.map((m) => (
              <Bar key={m} dataKey={m} fill={modeColor(m)} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-2 w-full text-xs tabular-nums">
        <thead className="text-stone-500">
          <tr><th className="text-left font-medium">metric</th>{modes.map((m) => <th key={m} className="text-right font-medium">{m}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="text-stone-600 dark:text-stone-400">{r.label}</td>
              {modes.map((m) => {
                const a = data[m]?.[r.key];
                return <td key={m} className="text-right">{fmt(a?.[r.stat ?? "mean"], kind)}
                  {a && a.measured < a.n && <span className="text-stone-400"> ({a.measured}/{a.n})</span>}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
