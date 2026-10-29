import { useState } from "react";
import { Button, Card, ErrorNote, inputCls } from "../components/ui";
import { supabase } from "../lib/api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function go(kind: "in" | "up") {
    setBusy(true); setError(null); setNote(null);
    const res = kind === "in"
      ? await supabase.auth.signInWithPassword({ email, password })
      : await supabase.auth.signUp({ email, password });
    setBusy(false);
    if (res.error) setError(res.error.message);
    else if (kind === "up" && !res.data.session) setNote("Check your email to confirm the account, then sign in.");
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 text-stone-900 dark:text-stone-100">
      <Card title="StructRAG" className="w-full max-w-sm">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go("in"); }}>
          <label className="block text-sm">Email
            <input className={inputCls} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block text-sm">Password
            <input className={inputCls} type="password" autoComplete="current-password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <ErrorNote error={error} />
          {note && <p className="text-sm text-stone-600 dark:text-stone-300">{note}</p>}
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>Sign in</Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => go("up")}>Create account</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
