import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { PauseCircle, PlayCircle } from "lucide-react";
import { api, type AgentState } from "../lib/api";
import { fmtDate } from "../lib/ui";
import { Button, Modal, inputCls, useToast } from "./ui";

/** Pause / resume all automatic work (preparing at the evening time and posting at the posting time). */
export function useAgent() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const set = useMutation({
    mutationFn: ({ paused, until }: { paused: boolean; until?: string }) => api.setAgent(paused, until ?? ""),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["meta"] });
      toast("ok", a.paused ? `Agent paused${a.paused_until ? ` until ${fmtDate(a.paused_until)}` : ""} – nothing goes out automatically` : "Agent resumed");
    },
    onError: (e: Error) => toast("error", e.message),
  });
  return { agent: meta?.agent, set };
}

export function pausedLabel(a?: AgentState) {
  if (!a?.paused) return "Running";
  return a.paused_until ? `Paused until ${fmtDate(a.paused_until, { day: "numeric", month: "short" })}` : "Paused";
}

/** Sidebar (dark) switch. */
export function AgentSwitch() {
  const { agent, set } = useAgent();
  const [open, setOpen] = useState(false);
  const paused = !!agent?.paused;
  return (
    <>
      <button onClick={() => (paused ? set.mutate({ paused: false }) : setOpen(true))} disabled={!agent || set.isPending}
        className={clsx("mt-6 flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-xs ring-1 transition",
          paused ? "bg-amber-400/10 text-amber-200 ring-amber-300/30 hover:bg-amber-400/20" : "bg-emerald-400/5 text-white/70 ring-white/10 hover:bg-white/5")}>
        {paused ? <PlayCircle className="size-4 shrink-0 text-amber-300" /> : <PauseCircle className="size-4 shrink-0 text-emerald-300" />}
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-white/90">Agent: {pausedLabel(agent)}</span>
          <span className="block text-white/50">{paused ? "Tap to resume" : "Tap to pause (holidays, busy weeks)"}</span>
        </span>
      </button>
      <PauseModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}

export function PauseModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { set } = useAgent();
  const [mode, setMode] = useState<"open" | "date">("open");
  const today = new Date().toISOString().slice(0, 10);
  const [until, setUntil] = useState(today);
  return (
    <Modal open={open} onClose={onClose} title="Pause the agent"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={<PauseCircle className="size-4" />} loading={set.isPending}
          onClick={() => set.mutate({ paused: true, until: mode === "date" ? until : "" }, { onSuccess: onClose })}>Pause</Button>
      </>}>
      <p className="text-sm text-stone-600">
        While paused, the agent doesn't prepare content in the evening and doesn't post anything automatically.
        <b> Generate now</b> and <b>Publish now</b> still work, and you can still review and approve.
      </p>
      <div className="mt-4 space-y-2">
        {([["open", "Until I resume it"], ["date", "Until a date (resumes by itself)"]] as const).map(([id, label]) => (
          <label key={id} className={clsx("flex cursor-pointer items-center gap-3 rounded-xl px-4 py-3 ring-1",
            mode === id ? "bg-brand-50 ring-2 ring-brand-500" : "ring-stone-200 hover:bg-stone-50")}>
            <input type="radio" name="pause-mode" checked={mode === id} onChange={() => setMode(id)} className="accent-brand-600" />
            <span className="text-sm font-semibold">{label}</span>
          </label>
        ))}
        {mode === "date" && (
          <div className="pl-1 pt-1">
            <label className="text-xs font-semibold text-stone-500" htmlFor="pause-until">Last paused day</label>
            <input id="pause-until" type="date" min={today} value={until} onChange={(e) => setUntil(e.target.value)} className={clsx(inputCls, "mt-1")} />
            <p className="mt-1 text-xs text-stone-500">It starts working again the day after.</p>
          </div>
        )}
      </div>
    </Modal>
  );
}

/** Queue banner while paused. */
export function PausedBanner() {
  const { agent, set } = useAgent();
  if (!agent?.paused) return null;
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3 rounded-2xl bg-amber-50 px-5 py-4 text-sm text-amber-900 ring-1 ring-amber-200">
      <PauseCircle className="size-5 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">The agent is paused{agent.paused_until ? ` until ${fmtDate(agent.paused_until, { weekday: "long", day: "numeric", month: "long" })}` : ""}</div>
        <div className="text-amber-800/80">Nothing is prepared or posted automatically. Generate now and Publish now still work.</div>
      </div>
      <Button variant="dark" className="px-3 py-1.5 text-xs" icon={<PlayCircle className="size-3.5" />} loading={set.isPending}
        onClick={() => set.mutate({ paused: false })}>Resume</Button>
    </div>
  );
}

/** Phone top bar button. */
export function AgentIconButton() {
  const { agent, set } = useAgent();
  const [open, setOpen] = useState(false);
  const paused = !!agent?.paused;
  return (
    <>
      <button onClick={() => (paused ? set.mutate({ paused: false }) : setOpen(true))} aria-label={paused ? "Resume agent" : "Pause agent"}
        className={clsx("grid size-9 place-items-center rounded-lg hover:bg-white/10", paused ? "text-amber-300" : "text-white/60 hover:text-white")}>
        {paused ? <PlayCircle className="size-5" /> : <PauseCircle className="size-5" />}
      </button>
      <PauseModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
