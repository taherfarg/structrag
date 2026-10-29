import type { Session } from "@supabase/supabase-js";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { supabase } from "./lib/api";
import Benchmarks from "./pages/Benchmarks";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import Playground from "./pages/Playground";
import Settings from "./pages/Settings";
import Structure from "./pages/Structure";

const NAV = [
  ["/documents", "Documents"],
  ["/structure", "Structure"],
  ["/playground", "Playground"],
  ["/benchmarks", "Benchmarks"],
  ["/settings", "Settings"],
] as const;

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "light");
  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* storage may be blocked */ }
    setTheme(next);
  };
  return (
    <button onClick={flip} className="text-xs text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100">
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}

function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);
  if (session === undefined) return null;
  if (!session) return <Login />;
  return (
    <BrowserRouter>
      <div className="min-h-screen text-stone-900 dark:text-stone-100 md:flex">
        <aside className="border-b border-stone-200 px-4 py-3 dark:border-stone-800 md:w-52 md:shrink-0 md:border-r md:border-b-0 md:py-6">
          <div className="mb-4 text-sm font-bold tracking-tight">StructRAG</div>
          <nav className="flex flex-wrap gap-1 md:flex-col">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} className={({ isActive }) =>
                `rounded-md px-2.5 py-1.5 text-sm ${isActive ? "bg-stone-200 font-medium dark:bg-stone-800" : "text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-900"}`}>
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-6 flex flex-col items-start gap-2 text-xs text-stone-500">
            <span className="max-w-full truncate">{session.user.email}</span>
            <ThemeToggle />
            <button className="hover:text-stone-900 dark:hover:text-stone-100" onClick={() => supabase.auth.signOut()}>Sign out</button>
          </div>
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
          <Routes>
            <Route path="/" element={<Navigate to="/documents" replace />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/structure" element={<Structure />} />
            <Route path="/structure/:docId" element={<Structure />} />
            <Route path="/playground" element={<Playground />} />
            <Route path="/benchmarks" element={<Benchmarks />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
