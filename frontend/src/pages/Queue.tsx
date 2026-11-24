import { useMemo, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CalendarClock, CalendarDays, Check, CheckSquare, Film, ImageIcon, Inbox, RotateCcw, Search, Sparkles, Trash2, Wand2, X } from "lucide-react";
import { api, type Status } from "../lib/api";
import { fmtDate, workerText } from "../lib/ui";
import ItemCard, { type CardAction } from "../components/ItemCard";
import { PausedBanner } from "../components/Agent";
import { InstallBanner } from "../components/Install";
import { Button, Confirm, EmptyState, Modal, useToast } from "../components/ui";
import { PendingOccasionsBanner } from "../components/Occasions";

const TABS: { id: string; label: string; statuses: Status[] | null; bin?: boolean }[] = [
  { id: "all", label: "All", statuses: null },
  { id: "review", label: "Needs review", statuses: ["pending_approval", "outline"] },
  { id: "generating", label: "Generating", statuses: ["generating", "queued"] },
  { id: "approved", label: "Approved", statuses: ["approved", "publishing"] },
  { id: "published", label: "Published", statuses: ["published", "dry_run", "partial"] },
  { id: "archived", label: "Rejected / failed", statuses: ["rejected", "failed"] },
  { id: "bin", label: "Bin", statuses: null, bin: true },
];
const ALL_STATUSES: Status[] = ["generating", "queued", "outline", "pending_approval", "approved", "publishing", "published", "dry_run", "partial", "failed", "rejected"];

export default function Queue() {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState("all");
  const [kind, setKind] = useState<"" | "video" | "post">("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [genOpen, setGenOpen] = useState(false);

  useEffect(() => { const t = setTimeout(() => setSearch(q), 300); return () => clearTimeout(t); }, [q]);

  const current = TABS.find((t) => t.id === tab)!;
  const statuses = current.statuses;
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  useEffect(() => { setSelected(new Set()); }, [tab, kind, search]);
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["items"] }); qc.invalidateQueries({ queryKey: ["meta"] }); qc.invalidateQueries({ queryKey: ["calendar"] }); };
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const { data, isLoading } = useQuery({
    queryKey: ["items", tab, kind, search],
    queryFn: () => api.items({ status: statuses?.join(","), kind, q: search, limit: 120, bin: current.bin }),
    refetchInterval: (query) => (query.state.data?.items.some((i) => ["generating", "queued", "publishing"].includes(i.status)) ? 3000 : 20000),
  });

  const action = useMutation({
    mutationFn: async ({ id, a }: { id: number; a: CardAction }) => {
      if (a === "delete") { await api.deleteItem(id); return null; }
      if (a === "purge") { await api.deleteForever(id); return null; }
      if (a === "restore") return api.restore(id);
      return api.action(id, a);
    },
    onSuccess: (item, { id, a }) => {
      if (a === "delete") {
        toast("ok", "Moved to the bin", { label: "Undo", onClick: () => api.restore(id).then(refresh) });
      } else {
        toast("ok", a === "approve" && item ? `Approved – goes out ${fmtDate(item.date)} at ${item.publish_time || meta?.times.publish || "posting time"}`
          : a === "stop" ? "Stopped" : a === "restore" ? "Restored" : a === "purge" ? "Deleted for good" : "Rejected");
      }
      refresh();
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const bulk = useMutation({
    mutationFn: ({ a }: { a: "approve" | "reject" | "delete" | "restore" | "purge" }) => api.bulk([...selected], a),
    onSuccess: (r, { a }) => {
      const verb = { approve: "Approved", reject: "Rejected", delete: "Moved to the bin", restore: "Restored", purge: "Deleted for good" }[a];
      const ids = r.done;
      toast(r.skipped.length ? "error" : "ok",
        `${verb}: ${ids.length}${r.skipped.length ? ` · skipped ${r.skipped.length} (${[...new Set(r.skipped.map((x) => x.reason))].join(", ")})` : ""}`,
        a === "delete" && ids.length ? { label: "Undo", onClick: () => api.bulk(ids, "restore").then(refresh) } : undefined);
      setSelected(new Set()); setSelecting(false); refresh();
    },
    onError: (e: Error) => toast("error", e.message),
  });
  const [confirmBin, setConfirmBin] = useState(false);
  const emptyBin = useMutation({
    mutationFn: api.emptyBin,
    onSuccess: ({ deleted }) => { toast("ok", `Deleted ${deleted} item${deleted === 1 ? "" : "s"} for good`); refresh(); },
    onError: (e: Error) => toast("error", e.message),
  });

  const [confirmClear, setConfirmClear] = useState(false);
  const clear = useMutation({
    mutationFn: api.deleteRejected,
    onSuccess: ({ deleted }) => {
      toast("ok", `Moved ${deleted} item${deleted === 1 ? "" : "s"} to the bin – kept for 7 days`);
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const generate = useMutation({
    mutationFn: ({ k, notes }: { k?: "video" | "post"; notes?: string }) => api.generate(k, notes ?? ""),
    onSuccess: () => {
      toast("ok", "Started – it will appear here in a few seconds");
      setTimeout(() => qc.invalidateQueries({ queryKey: ["items"] }), 1500);
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const count = (t: (typeof TABS)[number]) =>
    t.bin ? meta?.counts.bin ?? 0 : (t.statuses ?? ALL_STATUSES).reduce((n, s) => n + (meta?.counts[s] ?? 0), 0);

  const items = data?.items ?? [];
  const today = useMemo(() => meta?.week[0], [meta]);

  return (
    <div className="mx-auto max-w-7xl px-5 py-8 md:px-10">
      {/* header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Content queue</h1>
          <p className="mt-1 text-sm text-stone-500">Review what the agent made. Nothing goes out until you approve it.</p>
        </div>
        <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
          <Button icon={<Wand2 className="size-4" />} loading={generate.isPending} onClick={() => setGenOpen(true)}>
            Generate now
          </Button>
          <Link to="/create" className="contents sm:block"><Button variant="primary" icon={<Sparkles className="size-4" />} className="w-full"><span className="sm:hidden">From URL</span><span className="hidden sm:inline">Create from URL</span></Button></Link>
        </div>
      </div>
      <GenerateModal open={genOpen} today={today} busy={generate.isPending} onClose={() => setGenOpen(false)}
        onGenerate={(k, notes) => generate.mutate({ k, notes }, { onSuccess: () => setGenOpen(false) })} />

      {/* week strip */}
      {meta && (
        <div className="-mx-5 mt-6 flex snap-x gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] md:mx-0 md:grid md:grid-cols-7 md:overflow-visible md:px-0">
          {meta.week.map((d, i) => (
            <div key={d.date} className={clsx("min-w-[6.5rem] shrink-0 snap-start rounded-xl px-3 py-2.5 ring-1 md:min-w-0", i === 0 ? "bg-ink-900 text-white ring-ink-900" : "bg-white ring-stone-200/80")}>
              <div className={clsx("text-[11px] font-semibold uppercase tracking-wide", i === 0 ? "text-white/60" : "text-stone-400")}>
                {i === 0 ? "Today" : fmtDate(d.date, { weekday: "short" })} · {fmtDate(d.date, { day: "numeric" })}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-sm font-semibold">
                {d.kind === "video" ? <Film className="size-3.5" /> : d.kind === "post" ? <ImageIcon className="size-3.5" /> : null}
                {d.kind === "none" ? <span className={i === 0 ? "text-white/50" : "text-stone-400"}>Off</span> : d.kind === "video" ? "Video" : "Post"}
              </div>
              {(d.occasions ?? []).filter((o) => o.status !== "skipped").slice(0, 1).map((o) => (
                <div key={o.name} title={`${o.name} – ${o.status === "approved" ? "greeting will be posted" : "waiting for your decision"}`}
                  className={clsx("mt-0.5 truncate text-[11px]", o.status === "approved" ? (i === 0 ? "text-emerald-300" : "text-emerald-700") : (i === 0 ? "text-amber-300" : "text-amber-600"))}>
                  {o.status === "approved" ? "✅" : "⏳"} {o.name}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {meta?.video_worker?.mode === "pc" && !meta.video_worker.online && (meta.counts.queued ?? 0) > 0 && (
        <div className="mt-6 flex items-start gap-3 rounded-2xl bg-indigo-50 px-5 py-4 text-sm text-indigo-900 ring-1 ring-indigo-200">
          <Film className="mt-0.5 size-4 shrink-0" />
          <div>
            <div className="font-semibold">{meta.counts.queued} video{(meta.counts.queued ?? 0) > 1 ? "s are" : " is"} waiting for your PC</div>
            <div className="mt-0.5 text-indigo-800/80">{workerText(meta.video_worker)}. Double-click <b>run_video_worker.bat</b> in the project folder and keep the window open – the video appears here when it's done.</div>
          </div>
        </div>
      )}
      <PausedBanner />
      <InstallBanner />
      {(meta?.counts.missed ?? 0) > 0 && tab !== "approved" && (
        <button onClick={() => setTab("approved")}
          className="mt-6 flex w-full items-start gap-3 rounded-2xl bg-red-50 px-5 py-4 text-left text-sm text-red-900 ring-1 ring-red-200 hover:bg-red-100/60">
          <CalendarClock className="mt-0.5 size-4 shrink-0" />
          <span><b>{meta!.counts.missed} approved {meta!.counts.missed === 1 ? "post" : "posts"} missed {meta!.counts.missed === 1 ? "its" : "their"} day</b> – they won't go out by themselves.
            Open {meta!.counts.missed === 1 ? "it" : "them"} and pick a new date. <span className="font-semibold underline">Show approved</span></span>
        </button>
      )}
      <PendingOccasionsBanner />

      {/* filters */}
      <div className="mt-8 flex flex-wrap items-center gap-3">
        <div className="-mx-5 flex w-[calc(100%+2.5rem)] gap-1 overflow-x-auto px-5 [scrollbar-width:none] md:mx-0 md:w-auto md:flex-wrap md:overflow-visible md:rounded-xl md:bg-white md:p-1 md:px-1 md:ring-1 md:ring-stone-200/80">
          {TABS.map((t) => {
            const n = count(t);
            return (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={clsx("flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition",
                  tab === t.id ? "bg-ink-900 text-white" : "bg-white text-stone-600 ring-1 ring-stone-200/80 hover:bg-stone-100 md:bg-transparent md:ring-0")}>
                {t.label}
                {n > 0 && <span className={clsx("rounded-full px-1.5 text-[11px] font-bold",
                  tab === t.id ? "bg-white/20" : t.id === "review" ? "bg-brand-600 text-white" : "bg-stone-100 text-stone-500")}>{n}</span>}
              </button>
            );
          })}
        </div>
        <div className="flex gap-1 rounded-xl bg-white p-1 ring-1 ring-stone-200/80">
          {(["", "video", "post"] as const).map((k) => (
            <button key={k} onClick={() => setKind(k)}
              className={clsx("rounded-lg px-3 py-1.5 text-sm font-medium", kind === k ? "bg-stone-100 text-stone-900" : "text-stone-500 hover:text-stone-800")}>
              {k === "" ? "All types" : k === "video" ? "Videos" : "Posts"}
            </button>
          ))}
        </div>
        <Button variant={selecting ? "dark" : "outline"} className="px-3 py-1.5 text-sm" icon={<CheckSquare className="size-4" />}
          onClick={() => { setSelecting((v) => !v); setSelected(new Set()); }}>{selecting ? "Done" : "Select"}</Button>
        <label className="ml-auto flex w-full items-center gap-2 rounded-xl bg-white px-3 py-2 ring-1 ring-stone-200/80 focus-within:ring-ink-900 sm:w-72">
          <Search className="size-4 text-stone-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search topic, product, website…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-stone-400" />
        </label>
      </div>

      {/* grid */}
      <div className="mt-6">
        {tab === "bin" && items.length > 0 && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-xl bg-white px-4 py-3 text-sm ring-1 ring-stone-200/80">
            <span className="text-stone-600">Deleted items stay here for 7 days, then they're removed for good. Restore anything you still need.</span>
            <Button variant="danger" className="shrink-0 px-3 py-1.5 text-xs" icon={<Trash2 className="size-3.5" />} loading={emptyBin.isPending}
              onClick={() => setConfirmBin(true)}>Empty bin</Button>
          </div>
        )}
        <Confirm open={confirmBin} title="Empty the bin?" body="Everything in the bin and its files are deleted for good. This can't be undone."
          confirmLabel="Empty bin" variant="danger" onConfirm={() => emptyBin.mutate()} onClose={() => setConfirmBin(false)} />
        {tab === "archived" && items.length > 0 && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-xl bg-white px-4 py-3 text-sm ring-1 ring-stone-200/80">
            <span className="text-stone-600">Rejected, stopped and failed items – nothing here is ever posted.</span>
            <Button variant="danger" className="px-3 py-1.5 text-xs" icon={<Trash2 className="size-3.5" />} loading={clear.isPending}
              onClick={() => setConfirmClear(true)}>Delete all</Button>
          </div>
        )}
        <Confirm open={confirmClear} title="Delete all rejected and failed items?"
          body={`All ${count(TABS.find((t) => t.id === "archived")!)} rejected, stopped and failed items and their files are removed for good.`}
          confirmLabel="Delete all" variant="danger" onConfirm={() => clear.mutate()} onClose={() => setConfirmClear(false)} />
        {isLoading ? (
          <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => <div key={i} className="shimmer h-80 rounded-2xl bg-stone-200/60" />)}
          </div>
        ) : items.length === 0 ? (
          <EmptyState icon={<Inbox className="size-6" />}
            title={tab === "review" ? "Nothing waiting for review" : tab === "bin" ? "The bin is empty" : "No content here yet"}
            text={tab === "all" && !search ? "The agent prepares tomorrow's content every evening. Or create something right now." : "Try another filter or search."}
            action={tab === "all" && !search ? <Button variant="primary" icon={<Wand2 className="size-4" />} onClick={() => setGenOpen(true)}>Generate content</Button> : undefined} />
        ) : (
          <div className="grid grid-cols-2 items-start gap-3 sm:gap-5 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((item) => (
              <ItemCard key={item.id} item={item} busy={action.isPending}
                onAction={(id, a) => action.mutate({ id, a })}
                selecting={selecting} selected={selected.has(item.id)} onSelect={toggle} />
            ))}
          </div>
        )}
        {data && data.total > items.length && (
          <p className="mt-6 text-center text-sm text-stone-400">Showing {items.length} of {data.total}</p>
        )}
      </div>

      {selecting && (
        <div className="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-20 mt-6 flex flex-wrap items-center gap-2 rounded-2xl bg-ink-900 px-4 py-3 text-sm text-white shadow-2xl md:bottom-4">
          <span className="font-semibold">{selected.size} selected</span>
          <button onClick={() => setSelected(selected.size === items.length ? new Set() : new Set(items.map((i) => i.id)))}
            className="text-xs font-semibold text-white/60 underline hover:text-white">{selected.size === items.length && items.length ? "Clear" : "Select all"}</button>
          <span className="flex-1" />
          {tab === "bin" ? (
            <>
              <Button variant="outline" className="px-3 py-1.5 text-xs" icon={<RotateCcw className="size-3.5" />} disabled={!selected.size}
                loading={bulk.isPending && bulk.variables?.a === "restore"} onClick={() => bulk.mutate({ a: "restore" })}>Restore</Button>
              <Button variant="danger" className="px-3 py-1.5 text-xs" icon={<Trash2 className="size-3.5" />} disabled={!selected.size}
                loading={bulk.isPending && bulk.variables?.a === "purge"} onClick={() => bulk.mutate({ a: "purge" })}>Delete for good</Button>
            </>
          ) : (
            <>
              <Button variant="success" className="px-3 py-1.5 text-xs" icon={<Check className="size-3.5" />} disabled={!selected.size}
                loading={bulk.isPending && bulk.variables?.a === "approve"} onClick={() => bulk.mutate({ a: "approve" })}>Approve</Button>
              <Button variant="outline" className="px-3 py-1.5 text-xs" icon={<X className="size-3.5" />} disabled={!selected.size}
                loading={bulk.isPending && bulk.variables?.a === "reject"} onClick={() => bulk.mutate({ a: "reject" })}>Reject</Button>
              <Button variant="outline" className="px-3 py-1.5 text-xs" icon={<Trash2 className="size-3.5" />} disabled={!selected.size}
                loading={bulk.isPending && bulk.variables?.a === "delete"} onClick={() => bulk.mutate({ a: "delete" })}>Delete</Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const IDEAS = [
  "Feature the Restaurant POS for busy restaurant owners",
  "A tip that saves small businesses time",
  "Announce our free demo – book this week",
  "Fun, light-hearted post for Friday",
  "Myth vs fact about AI agents",
];

function GenerateModal({ open, today, busy, onClose, onGenerate }: {
  open: boolean; today?: { kind: string }; busy: boolean;
  onClose: () => void; onGenerate: (kind: "video" | "post" | undefined, notes: string) => void;
}) {
  const [kind, setKind] = useState<"scheduled" | "post" | "video">("post");
  const [notes, setNotes] = useState("");
  useEffect(() => { if (open) setKind(today && today.kind !== "none" ? "scheduled" : "post"); }, [open, today]);
  const choices = [
    ...(today && today.kind !== "none" ? [{ id: "scheduled" as const, icon: <CalendarDays className="size-5" />, title: "Today's plan",
      sub: today.kind === "video" ? "Video · as scheduled" : "Post · as scheduled" }] : []),
    { id: "post" as const, icon: <ImageIcon className="size-5" />, title: "A post", sub: "Image + captions · ~1 min" },
    { id: "video" as const, icon: <Film className="size-5" />, title: "A video", sub: "16:9 + 9:16 · ~5 min" },
  ];
  return (
    <Modal open={open} onClose={onClose} title="Generate now"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={<Wand2 className="size-4" />} loading={busy}
          onClick={() => onGenerate(kind === "scheduled" ? undefined : kind, notes.trim())}>Generate</Button>
      </>}>
      <div className="text-sm font-semibold">What should it make?</div>
      <div className={clsx("mt-2 grid gap-2", choices.length === 3 ? "grid-cols-3" : "grid-cols-2")}>
        {choices.map((c) => (
          <button key={c.id} onClick={() => setKind(c.id)}
            className={clsx("flex flex-col items-start gap-1 rounded-xl p-3 text-left ring-1 transition",
              kind === c.id ? "bg-brand-50 ring-2 ring-brand-500" : "bg-white ring-stone-200 hover:bg-stone-50")}>
            <span className={kind === c.id ? "text-brand-700" : "text-stone-500"}>{c.icon}</span>
            <span className="text-sm font-semibold leading-tight">{c.title}</span>
            <span className="text-[11px] leading-tight text-stone-500">{c.sub}</span>
          </button>
        ))}
      </div>
      <label className="mt-5 block text-sm font-semibold" htmlFor="gen-notes">
        Your prompt <span className="font-normal text-stone-400">(optional)</span>
      </label>
      <textarea id="gen-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={1000}
        placeholder="e.g. A post about our Clinic software for salon owners, friendly tone, mention the free demo"
        className="mt-2 w-full resize-none rounded-xl bg-stone-50 px-3.5 py-3 text-sm outline-none ring-1 ring-stone-200 placeholder:text-stone-400 focus:bg-white focus:ring-2 focus:ring-ink-900" />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {IDEAS.map((t) => (
          <button key={t} onClick={() => setNotes(t)} className="rounded-full bg-stone-100 px-2.5 py-1 text-xs text-stone-600 hover:bg-stone-200">{t}</button>
        ))}
      </div>
      <p className="mt-3 text-xs text-stone-500">
        Leave it empty and the agent picks the topic itself (festival, trend or product). Name a product and it features that one.
      </p>
    </Modal>
  );
}
