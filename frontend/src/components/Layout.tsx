import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { CalendarDays, ExternalLink, LayoutGrid, LogOut, Settings2, Sparkles } from "lucide-react";
import { api, auth } from "../lib/api";

export default function Layout() {
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: api.meta, refetchInterval: 15000 });
  const review = meta?.counts.pending_approval ?? 0;
  const running = (meta?.counts.generating ?? 0) + (meta?.counts.queued ?? 0);
  const pc = meta?.video_worker;
  const live = meta ? Object.values(meta.platforms).some(Boolean) : false;

  const link = ({ isActive }: { isActive: boolean }) =>
    clsx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
      isActive ? "bg-white/10 text-white" : "text-white/60 hover:bg-white/5 hover:text-white");

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col bg-ink-900 px-4 py-6 md:flex">
        <div className="flex items-center gap-3 px-2">
          <div className="grid size-9 place-items-center rounded-lg bg-brand-600 text-white">
            <svg viewBox="0 0 32 32" className="size-5"><path d="M16 3l11 13-11 13L5 16z" fill="none" stroke="currentColor" strokeWidth="3" /></svg>
          </div>
          <div className="leading-tight">
            <div className="font-bold text-white">{meta?.company.name ?? "Krypsos"}</div>
            <div className="text-xs text-white/50">Marketing Agent</div>
          </div>
        </div>

        <nav className="mt-8 flex flex-col gap-1">
          <NavLink to="/" end className={link}>
            <LayoutGrid className="size-4" /> Content queue
            {review > 0 && <span className="ml-auto rounded-full bg-brand-600 px-2 text-xs font-bold text-white">{review}</span>}
          </NavLink>
          <NavLink to="/create" className={link}>
            <Sparkles className="size-4" /> Create from URL
          </NavLink>
          <NavLink to="/schedule" className={link}>
            <CalendarDays className="size-4" /> Schedule & calendar
          </NavLink>
          <NavLink to="/settings" className={link}>
            <Settings2 className="size-4" /> Settings
          </NavLink>
        </nav>

        {running > 0 && (
          <div className="mt-6 rounded-lg bg-indigo-500/10 px-3 py-2.5 text-xs text-indigo-200">
            <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-indigo-400" />
            {running} item{running > 1 ? "s" : ""} generating…
          </div>
        )}
        {pc?.mode === "pc" && (
          <div className="mt-3 flex items-center gap-2 px-3 text-xs text-white/60" title="Videos are made by run_video_worker.bat on your PC">
            <span className={clsx("size-1.5 rounded-full", pc.online ? "bg-emerald-400" : "bg-white/30")} />
            Video PC: {pc.online ? (pc.state === "working" ? "making a video" : "online") : "offline"}
          </div>
        )}

        <div className="mt-auto space-y-3 px-2 text-xs text-white/50">
          <div className="rounded-lg bg-white/5 p-3">
            <div className="font-semibold text-white/80">{live ? "Publishing live" : "Test mode"}</div>
            <div className="mt-1">
              {live ? "Approved content is posted for real." : <>Approved content is marked as published but not posted. <NavLink to="/settings?tab=connections" className="font-semibold text-white/80 underline">Connect accounts</NavLink> to go live.</>}
            </div>
          </div>
          {meta && <div>Prepares at {meta.times.generate} · posts at {meta.times.publish}</div>}
          <a href="/classic/" className="flex items-center gap-1.5 hover:text-white"><ExternalLink className="size-3" /> Classic dashboard</a>
          <button onClick={() => { auth.clear(); window.dispatchEvent(new Event("dma:logout")); }}
            className="flex items-center gap-1.5 hover:text-white"><LogOut className="size-3" /> Log out</button>
        </div>
      </aside>

      {/* mobile top bar */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-4 bg-ink-900 px-4 py-3 md:hidden">
          <span className="font-bold text-white">{meta?.company.name ?? "Krypsos"}</span>
          <NavLink to="/" end className={({ isActive }) => clsx("text-sm", isActive ? "text-white" : "text-white/60")}>Queue</NavLink>
          <NavLink to="/create" className={({ isActive }) => clsx("text-sm", isActive ? "text-white" : "text-white/60")}>Create</NavLink>
          <NavLink to="/schedule" className={({ isActive }) => clsx("text-sm", isActive ? "text-white" : "text-white/60")}>Schedule</NavLink>
          <NavLink to="/settings" className={({ isActive }) => clsx("text-sm", isActive ? "text-white" : "text-white/60")}>Settings</NavLink>
        </div>
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
