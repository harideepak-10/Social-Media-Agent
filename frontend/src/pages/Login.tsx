import { useState } from "react";
import { Loader2, LockKeyhole } from "lucide-react";
import { api, auth } from "../lib/api";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { token } = await api.login(username, password);
      auth.set(token);
      onLogin();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-full place-items-center bg-ink-900 px-4">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top_left,rgba(200,55,45,.35),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgba(245,158,11,.15),transparent_55%)]" />
      <form onSubmit={submit} className="relative w-full max-w-sm rounded-2xl bg-white p-8 shadow-2xl">
        <div className="grid size-11 place-items-center rounded-xl bg-brand-600 text-white"><LockKeyhole className="size-5" /></div>
        <h1 className="mt-5 text-xl font-extrabold">Marketing Agent</h1>
        <p className="mt-1 text-sm text-stone-500">Sign in with the dashboard login from your <code className="rounded bg-stone-100 px-1">.env</code></p>
        <label className="mt-6 block text-sm font-semibold">Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
          className="mt-1.5 w-full rounded-lg bg-stone-50 px-3 py-2.5 text-sm outline-none ring-1 ring-stone-200 focus:ring-2 focus:ring-ink-900" />
        <label className="mt-4 block text-sm font-semibold">Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus autoComplete="current-password"
          className="mt-1.5 w-full rounded-lg bg-stone-50 px-3 py-2.5 text-sm outline-none ring-1 ring-stone-200 focus:ring-2 focus:ring-ink-900" />
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        <button disabled={busy || !password}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50">
          {busy && <Loader2 className="size-4 animate-spin" />} Sign in
        </button>
      </form>
    </div>
  );
}
