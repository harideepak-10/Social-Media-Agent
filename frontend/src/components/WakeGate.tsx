import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Branded loading screen that covers the free server's wake-up.
 *
 * The dashboard is a Render Static Site (never sleeps), the agent a free Web Service that sleeps after 15 minutes
 * idle and needs ~30-60 s to start. On open we ping the agent; if it answers fast the app shows straight away
 * (no flash), otherwise this screen stays until it does – people never see Render's own "waking up" page.
 */
const MESSAGES = [
  "Waking up your marketing agent…",
  "Loading your content queue…",
  "Getting posts and videos ready…",
  "Checking today's schedule…",
  "Almost there…",
];
const SHOW_AFTER_MS = 700;   // answers faster than this -> no loading screen at all
const GIVE_UP_S = 150;

async function agentAwake(): Promise<boolean> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 12000);
  try {
    const r = await fetch(`/api/ping?t=${Date.now()}`, { cache: "no-store", signal: ctl.signal });
    // Render's waking page (or a proxy error page) is HTML – only our own JSON answer means "ready"
    return r.ok && (r.headers.get("content-type") || "").includes("application/json");
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

export default function WakeGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [show, setShow] = useState(false);
  const [secs, setSecs] = useState(0);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    setFailed(false);
    const started = Date.now();
    const showTimer = setTimeout(() => alive.current && setShow(true), SHOW_AFTER_MS);
    const tick = setInterval(() => alive.current && setSecs(Math.round((Date.now() - started) / 1000)), 1000);
    (async () => {
      while (alive.current) {
        if (await agentAwake()) {
          if (alive.current) setReady(true);
          break;
        }
        if ((Date.now() - started) / 1000 > GIVE_UP_S) {
          if (alive.current) setFailed(true);
          break;
        }
        await new Promise((r) => setTimeout(r, 2500));
      }
    })();
    return () => { alive.current = false; clearTimeout(showTimer); clearInterval(tick); };
  }, [attempt]);

  useEffect(() => {
    if (ready) document.getElementById("boot-splash")?.remove();
  }, [ready]);

  if (ready) return <>{children}</>;
  if (!show && !failed) return <BootScreen quiet />;
  return <BootScreen secs={secs} failed={failed} onRetry={() => { setSecs(0); setAttempt((a) => a + 1); }} />;
}

export function BootScreen({ secs = 0, failed = false, quiet = false, onRetry }: { secs?: number; failed?: boolean; quiet?: boolean; onRetry?: () => void }) {
  const msg = MESSAGES[Math.min(MESSAGES.length - 1, Math.floor(secs / 9))];
  // eases towards 95 % over ~60 s; jumps to 100 % when the app takes over
  const pct = Math.min(95, Math.round(100 * (1 - Math.exp(-secs / 22))));
  return (
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center overflow-hidden bg-[#0E0D0C] px-6 text-center text-white">
      <div className="pointer-events-none absolute -left-40 -top-40 size-[34rem] rounded-full bg-[#C8372D]/25 blur-[120px]" />
      <div className="pointer-events-none absolute -bottom-48 -right-40 size-[30rem] rounded-full bg-amber-500/10 blur-[120px]" />
      <div className="relative">
        <div className="absolute inset-0 animate-ping rounded-2xl bg-[#C8372D]/30" style={{ animationDuration: "2.2s" }} />
        <div className="relative grid size-16 place-items-center rounded-2xl bg-[#C8372D] shadow-2xl shadow-[#C8372D]/40">
          <svg viewBox="0 0 32 32" className="size-8 animate-[spin_6s_linear_infinite]"><path d="M16 4l10 12-10 12L6 16z" fill="none" stroke="white" strokeWidth="2.6" strokeLinejoin="round" /></svg>
        </div>
      </div>
      <h1 className="relative mt-7 text-2xl font-extrabold tracking-tight">Krypsos <span className="text-white/60">Marketing Agent</span></h1>
      {quiet ? (
        <p className="relative mt-2 text-sm text-white/50">Opening…</p>
      ) : failed ? (
        <div className="relative mt-4 max-w-sm">
          <p className="text-sm text-white/70">The agent is taking longer than usual to start. It may be updating – please try again in a minute.</p>
          <button onClick={onRetry} className="mt-5 rounded-full bg-white px-6 py-2.5 text-sm font-bold text-[#0E0D0C] hover:bg-white/90">Try again</button>
        </div>
      ) : (
        <>
          <p key={msg} className="relative mt-2 animate-[fadein_.5s_ease] text-sm text-white/70">{msg}</p>
          <div className="relative mt-7 h-1.5 w-64 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-gradient-to-r from-[#C8372D] to-amber-400 transition-[width] duration-1000 ease-out" style={{ width: `${pct}%` }} />
          </div>
          <p className="relative mt-3 text-xs tabular-nums text-white/35">
            {secs < 5 ? "Starting up" : `${secs}s · the agent sleeps when nobody uses it and needs about a minute to wake`}
          </p>
        </>
      )}
    </div>
  );
}
