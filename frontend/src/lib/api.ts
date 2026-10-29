import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
);

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000") + "/api";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (data.session) headers.Authorization = `Bearer ${data.session.access_token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const r = await fetch(BASE + path, { ...init, headers, body });
  if (r.status === 204) return undefined as T;
  const payload = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = payload.error ?? {};
    throw new ApiError(r.status, e.code ?? "http_error", e.message ?? r.statusText, e.details);
  }
  return payload as T;
}

export const MODES = ["vector", "structure", "hybrid"] as const;
export type Mode = (typeof MODES)[number];
export const modeColor = (m: string) => `var(--mode-${m})`;

export function fmt(v: number | null | undefined, kind: "num" | "ms" | "usd" | "pct" = "num"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (kind === "ms") return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
  if (kind === "usd") return v === 0 ? "$0" : v < 0.01 ? `$${v.toPrecision(2)}` : `$${v.toFixed(4)}`;
  if (kind === "pct") return `${(v * 100).toFixed(1)}%`;
  return Number.isInteger(v) ? String(v) : v.toFixed(3);
}
