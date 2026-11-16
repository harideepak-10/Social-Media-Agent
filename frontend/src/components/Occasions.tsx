import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, ChevronDown, Loader2, Pause, Play, Plus, Sparkles, Trash2, X } from "lucide-react";
import { api, type Occasion, type OccStatus } from "../lib/api";
import { fmtDate } from "../lib/ui";
import { Button, Card, Field, Modal, inputCls, useToast } from "./ui";

const KIND: Record<Occasion["kind"], { label: string; cls: string; emoji: string }> = {
  festival: { label: "Festival", cls: "bg-amber-50 text-amber-800", emoji: "🎉" },
  special: { label: "Special day", cls: "bg-sky-50 text-sky-800", emoji: "📅" },
  suggestion: { label: "AI suggestion", cls: "bg-violet-50 text-violet-800", emoji: "✨" },
  event: { label: "Your event", cls: "bg-fuchsia-50 text-fuchsia-800", emoji: "📌" },
};
export const OCC_STATUS: Record<OccStatus, { label: string; cls: string; dot: string }> = {
  approved: { label: "Will post", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", dot: "bg-emerald-500" },
  skipped: { label: "Skipped", cls: "bg-stone-100 text-stone-500 ring-stone-200", dot: "bg-stone-400" },
  pending: { label: "Waiting for you", cls: "bg-amber-50 text-amber-800 ring-amber-200", dot: "bg-amber-500" },
  paused: { label: "Paused", cls: "bg-stone-100 text-stone-500 ring-stone-200", dot: "bg-stone-400" },
};
const TABS = [
  { id: "all", label: "All" },
  { id: "pending", label: "Waiting for you" },
  { id: "festival", label: "Festivals" },
  { id: "special", label: "Special days" },
  { id: "suggestion", label: "AI suggestions" },
  { id: "event", label: "My events" },
] as const;

function useInvalidate() {
  const qc = useQueryClient();
  return () => ["occasions", "occasions-pending", "calendar", "meta", "events"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

export function useDecide() {
  const toast = useToast();
  const refresh = useInvalidate();
  return useMutation({
    mutationFn: ({ o, status }: { o: Occasion; status: "approved" | "skipped" }) =>
      o.kind === "suggestion" && status === "approved"
        ? api.suggestionStatus(o.key, "accepted")
        : o.kind === "suggestion" ? api.suggestionStatus(o.key, "dismissed") : api.decide(o.key, status),
    onSuccess: (_, { o, status }) => { refresh(); toast("ok", status === "approved" ? `${o.name}: a greeting post will be made` : `${o.name}: skipped`); },
    onError: (e: Error) => toast("error", e.message),
  });
}

export default function OccasionsCard() {
  const toast = useToast();
  const refresh = useInvalidate();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("all");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["occasions"], queryFn: () => api.occasions(90) });
  const decide = useDecide();
  const suggest = useMutation({
    mutationFn: api.suggestOccasions,
    onSuccess: (r) => { refresh(); toast("ok", r.added ? `${r.added} day${r.added > 1 ? "s" : ""} suggested – accept the ones you like` : "No new days found for your products"); setTab("suggestion"); },
    onError: (e: Error) => toast("error", e.message),
  });

  const items = data?.items ?? [];
  const filtered = items.filter((o) => (tab === "all" ? true : tab === "pending" ? o.status === "pending" : o.kind === tab));
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length, pending: 0 };
    items.forEach((o) => { c[o.kind] = (c[o.kind] ?? 0) + 1; if (o.status === "pending") c.pending++; });
    return c;
  }, [items]);

  return (
    <Card className="mt-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 className="font-bold">Festivals & special days</h2>
          <p className="mt-1 text-xs text-stone-500">
            Next 90 days. A greeting is only made for days marked <b className="text-emerald-700">Will post</b>. Undecided and skipped days get the normal product or trend post instead.
          </p>
        </div>
        <div className="flex gap-2">
          <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add special day</Button>
          <Button variant="dark" icon={<Sparkles className="size-4" />} loading={suggest.isPending} onClick={() => suggest.mutate()}>Suggest days for my products</Button>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-1 rounded-xl bg-stone-50 p-1 ring-1 ring-stone-200/70 sm:inline-flex">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={clsx("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition",
              tab === t.id ? "bg-ink-900 text-white" : "text-stone-600 hover:bg-white")}>
            {t.label}
            {(counts[t.id] ?? 0) > 0 && <span className={clsx("rounded-full px-1.5 text-[11px] font-bold",
              tab === t.id ? "bg-white/20" : t.id === "pending" ? "bg-amber-500 text-white" : "bg-stone-200 text-stone-600")}>{counts[t.id]}</span>}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="mt-6 flex items-center gap-2 text-sm text-stone-500"><Loader2 className="size-4 animate-spin" /> Loading…</div>
      ) : filtered.length === 0 ? (
        <p className="mt-6 rounded-xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm text-stone-400">
          {tab === "pending" ? "Nothing waiting – you're all caught up." : tab === "suggestion" ? "No suggestions yet. Click “Suggest days for my products”." : "Nothing in the next 90 days."}
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-stone-100">
          {filtered.map((o) => (
            <OccasionRow key={`${o.kind}-${o.key}-${o.name}`} o={o} open={open === o.key + o.name}
              onToggle={() => setOpen((x) => (x === o.key + o.name ? null : o.key + o.name))}
              onDecide={(status) => decide.mutate({ o, status })} busy={decide.isPending} />
          ))}
        </ul>
      )}
      <SpecialDayModal open={adding} onClose={() => setAdding(false)} />
    </Card>
  );
}

function OccasionRow({ o, open, onToggle, onDecide, busy }: {
  o: Occasion; open: boolean; onToggle: () => void; onDecide: (s: "approved" | "skipped") => void; busy: boolean;
}) {
  const k = KIND[o.kind];
  const st = OCC_STATUS[o.status];
  const d = new Date(o.date + "T00:00:00");
  const daysAway = Math.round((d.getTime() - new Date(new Date().toDateString()).getTime()) / 86400000);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className={clsx("w-14 shrink-0 rounded-lg py-1.5 text-center", o.status === "approved" ? "bg-emerald-50 text-emerald-800" : "bg-stone-100 text-stone-600")}>
          <div className="text-[10px] font-bold uppercase">{fmtDate(o.date, { month: "short" })}</div>
          <div className="text-lg font-extrabold leading-none">{d.getDate()}</div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={clsx("font-semibold", o.status === "skipped" && "text-stone-400 line-through")}>{k.emoji} {o.name}</span>
            <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase", k.cls)}>{k.label}</span>
          </div>
          <div className="mt-0.5 text-xs text-stone-500">
            {daysAway === 0 ? "Today" : daysAway === 1 ? "Tomorrow" : `In ${daysAway} days`}
            {o.status === "approved" && o.kind !== "event" && <> · posts {o.timing === 0 ? "on the day" : `${o.timing} day${o.timing > 1 ? "s" : ""} early (${fmtDate(o.post_date)})`}</>}
            {o.kind === "event" && o.timing > 0 && <> · announced from {o.timing} day{o.timing > 1 ? "s" : ""} before</>}
            {o.source === "rule" && <> · remembered: <b>{o.rule === "always" ? "always post" : "never post"}</b></>}
            {o.kind === "suggestion" && o.product && <> · fits <b>{o.product}</b></>}
          </div>
          {o.kind === "suggestion" && o.reason && <div className="mt-0.5 text-xs italic text-stone-500">{o.reason}</div>}
          {o.note && o.kind !== "event" && <div className="mt-0.5 text-xs text-stone-500">Note for the AI: {o.note}</div>}
        </div>
        <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1", st.cls)}>
          <span className={clsx("size-1.5 rounded-full", st.dot)} />{st.label}
        </span>
        {o.kind === "event" ? (
          <EventPause o={o} />
        ) : (
          <div className="flex items-center gap-1">
            <button disabled={busy} onClick={() => onDecide("approved")} title="Post a greeting"
              className={clsx("inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold ring-1 transition",
                o.status === "approved" ? "bg-emerald-600 text-white ring-emerald-600" : "bg-white text-stone-600 ring-stone-200 hover:text-emerald-700")}>
              <Check className="size-3.5" /> Post
            </button>
            <button disabled={busy} onClick={() => onDecide("skipped")} title="Don't post"
              className={clsx("inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold ring-1 transition",
                o.status === "skipped" ? "bg-stone-700 text-white ring-stone-700" : "bg-white text-stone-600 ring-stone-200 hover:text-red-600")}>
              <X className="size-3.5" /> Skip
            </button>
            {o.kind !== "suggestion" && (
              <button onClick={onToggle} className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-800" title="Options">
                <ChevronDown className={clsx("size-4 transition", open && "rotate-180")} />
              </button>
            )}
          </div>
        )}
      </div>
      {open && o.kind !== "event" && o.kind !== "suggestion" && <OccasionOptions o={o} />}
    </li>
  );
}

function OccasionOptions({ o }: { o: Occasion }) {
  const toast = useToast();
  const refresh = useInvalidate();
  const [rule, setRule] = useState(o.rule);
  const [timing, setTiming] = useState(o.timing);
  const [note, setNote] = useState(o.note);
  const save = useMutation({
    mutationFn: async () => {
      await api.setRule(o.name, rule, { timing, note });
      if (rule !== "ask") {
        // "always"/"never" decides from now on – drop a one-off choice so it applies to this date too
        if (o.source === "decision") await api.decide(o.key, "clear");
      } else if (o.status === "approved" || o.status === "skipped") {
        await api.decide(o.key, o.status, { timing, note }); // keep this year's choice, with the new options
      }
    },
    onSuccess: () => { refresh(); toast("ok", `Saved – ${o.name} will ${rule === "always" ? "always be posted" : rule === "never" ? "never be posted" : "ask you each year"}`); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <div className="ml-0 mt-3 grid gap-4 rounded-xl bg-stone-50 p-4 ring-1 ring-stone-200/70 sm:ml-[68px] md:grid-cols-[auto_auto_1fr_auto] md:items-end">
      <Field label="Every year">
        <div className="flex gap-1 rounded-lg bg-white p-1 ring-1 ring-stone-200">
          {(["always", "never", "ask"] as const).map((r) => (
            <button key={r} onClick={() => setRule(r)}
              className={clsx("rounded-md px-2.5 py-1 text-xs font-semibold", rule === r ? "bg-ink-900 text-white" : "text-stone-500 hover:text-stone-900")}>
              {r === "always" ? "Always post" : r === "never" ? "Never post" : "Ask me"}
            </button>
          ))}
        </div>
      </Field>
      <Field label="When">
        <select value={timing} onChange={(e) => setTiming(Number(e.target.value))} className={clsx(inputCls, "bg-white py-1.5")}>
          <option value={0}>On the day</option><option value={1}>1 day early</option><option value={2}>2 days early</option>
        </select>
      </Field>
      <Field label="Note for the AI (optional)">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. mention our Pongal offer / keep it simple, no product"
          className={clsx(inputCls, "bg-white py-1.5")} />
      </Field>
      <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
    </div>
  );
}

function EventPause({ o }: { o: Occasion }) {
  const toast = useToast();
  const refresh = useInvalidate();
  const paused = o.status === "paused";
  const m = useMutation({
    mutationFn: () => api.pauseEvent(o.key, !paused),
    onSuccess: () => { refresh(); toast("ok", paused ? `${o.name} will be announced` : `${o.name} paused – it won't be announced`); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <Button variant="outline" loading={m.isPending} onClick={() => m.mutate()}
      icon={paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />} className="px-2.5 py-1.5 text-xs">
      {paused ? "Resume" : "Pause"}
    </Button>
  );
}

function SpecialDayModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const refresh = useInvalidate();
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const { data } = useQuery({ queryKey: ["events"], queryFn: api.events, enabled: open });
  const add = useMutation({
    mutationFn: () => api.addSpecialDay(date.slice(5), name.trim()),
    onSuccess: () => { refresh(); toast("ok", `${name} added – it repeats every year and will be posted`); setName(""); setDate(""); onClose(); },
    onError: (e: Error) => toast("error", e.message),
  });
  const del = useMutation({
    mutationFn: api.removeSpecialDay,
    onSuccess: () => { refresh(); toast("ok", "Removed"); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <Modal open={open} title="Special days" onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Close</Button>
        <Button variant="primary" disabled={!date || name.trim().length < 2} loading={add.isPending} onClick={() => add.mutate()}>Add</Button></>}>
      <p className="text-sm text-stone-500">Days that matter to your business and repeat every year (e.g. your founding day, Engineers' Day). Days you add here are posted automatically.</p>
      <div className="mt-4 grid grid-cols-[auto_1fr] gap-3">
        <Field label="Date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Krypsos Founders' Day" className={inputCls} /></Field>
      </div>
      {!!data?.special_days.length && (
        <div className="mt-5">
          <div className="text-xs font-bold uppercase tracking-wider text-stone-400">In your list</div>
          <ul className="mt-2 max-h-56 divide-y divide-stone-100 overflow-y-auto">
            {data.special_days.map((d) => (
              <li key={d.date} className="flex items-center gap-3 py-1.5 text-sm">
                <span className="w-14 font-mono text-xs text-stone-400">{new Date(`2000-${d.date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>
                <span className="flex-1 truncate">{d.name}</span>
                <button onClick={() => del.mutate(d.date)} className="rounded p-1 text-stone-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-3.5" /></button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}

/** Banner for the queue page: undecided festivals coming up in the next 7 days. */
export function PendingOccasionsBanner() {
  const { data } = useQuery({ queryKey: ["occasions-pending"], queryFn: () => api.pendingOccasions(7), refetchInterval: 60000 });
  const decide = useDecide();
  const items = (data?.items ?? []).filter((o) => o.kind !== "event");
  if (!items.length) return null;
  return (
    <div className="mt-6 rounded-2xl bg-amber-50 p-4 ring-1 ring-amber-200">
      <div className="text-sm font-bold text-amber-900">🎉 Coming up – post a greeting?</div>
      <ul className="mt-2 space-y-1.5">
        {items.slice(0, 4).map((o) => (
          <li key={o.key} className="flex flex-wrap items-center gap-3 text-sm">
            <span className="min-w-0 flex-1"><b>{o.name}</b> <span className="text-amber-800/70">· {fmtDate(o.date)}{o.kind === "suggestion" ? ` · AI suggestion for ${o.product}` : ""}</span></span>
            <button onClick={() => decide.mutate({ o, status: "approved" })} disabled={decide.isPending}
              className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700"><Check className="size-3.5" /> Post</button>
            <button onClick={() => decide.mutate({ o, status: "skipped" })} disabled={decide.isPending}
              className="inline-flex items-center gap-1 rounded-lg bg-white px-2.5 py-1 text-xs font-semibold text-stone-600 ring-1 ring-amber-200 hover:text-red-600"><X className="size-3.5" /> Skip</button>
          </li>
        ))}
      </ul>
      {items.length > 4 && <a href="/schedule" className="mt-2 inline-block text-xs font-semibold text-amber-900 underline">+{items.length - 4} more on the Schedule page</a>}
    </div>
  );
}
