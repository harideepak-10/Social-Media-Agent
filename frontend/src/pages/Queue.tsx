import { useMemo, useRef, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CalendarDays, ChevronDown, Film, ImageIcon, Inbox, Search, Sparkles, Trash2, Wand2 } from "lucide-react";
import { api, type Status } from "../lib/api";
import { fmtDate, workerText } from "../lib/ui";
import ItemCard from "../components/ItemCard";
import { Button, Confirm, EmptyState, useToast } from "../components/ui";
import { PendingOccasionsBanner } from "../components/Occasions";

const TABS: { id: string; label: string; statuses: Status[] | null }[] = [
  { id: "all", label: "All", statuses: null },
  { id: "review", label: "Needs review", statuses: ["pending_approval"] },
  { id: "generating", label: "Generating", statuses: ["generating", "queued"] },
  { id: "approved", label: "Approved", statuses: ["approved"] },
  { id: "published", label: "Published", statuses: ["published", "dry_run", "partial"] },
  { id: "archived", label: "Rejected / failed", statuses: ["rejected", "failed"] },
];

export default function Queue() {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState("all");
  const [kind, setKind] = useState<"" | "video" | "post">("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => { const t = setTimeout(() => setSearch(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => {
    const close = (e: MouseEvent) => menuRef.current && !menuRef.current.contains(e.target as Node) && setMenu(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const statuses = TABS.find((t) => t.id === tab)?.statuses;
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const { data, isLoading } = useQuery({
    queryKey: ["items", tab, kind, search],
    queryFn: () => api.items({ status: statuses?.join(","), kind, q: search, limit: 120 }),
    refetchInterval: (query) => (query.state.data?.items.some((i) => ["generating", "queued"].includes(i.status)) ? 3000 : 20000),
  });

  const action = useMutation({
    mutationFn: async ({ id, a }: { id: number; a: "approve" | "reject" | "stop" | "delete" }) =>
      a === "delete" ? (await api.deleteItem(id), null) : api.action(id, a),
    onSuccess: (item, { a }) => {
      toast("ok", a === "delete" ? "Deleted" : a === "approve" && item ? `Approved – goes out ${fmtDate(item.date)} at ${meta?.times.publish ?? "publish time"}` : a === "stop" ? "Stopped" : "Rejected");
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const [confirmClear, setConfirmClear] = useState(false);
  const clear = useMutation({
    mutationFn: api.deleteRejected,
    onSuccess: ({ deleted }) => {
      toast("ok", `Deleted ${deleted} item${deleted === 1 ? "" : "s"}`);
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const generate = useMutation({
    mutationFn: (k?: "video" | "post") => api.generate(k),
    onSuccess: () => {
      toast("ok", "Started – it will appear here in a few seconds");
      setTimeout(() => qc.invalidateQueries({ queryKey: ["items"] }), 1500);
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const count = (t: (typeof TABS)[number]) =>
    t.statuses ? t.statuses.reduce((n, s) => n + (meta?.counts[s] ?? 0), 0) : Object.values(meta?.counts ?? {}).reduce((a, b) => a + (b ?? 0), 0);

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
        <div className="flex gap-2">
          <div className="relative" ref={menuRef}>
            <Button icon={<Wand2 className="size-4" />} loading={generate.isPending} onClick={() => setMenu((m) => !m)}>
              Generate now <ChevronDown className="size-4 opacity-60" />
            </Button>
            {menu && (
              <div className="absolute right-0 z-20 mt-2 w-64 overflow-hidden rounded-xl bg-white p-1 shadow-xl ring-1 ring-stone-200">
                {today && today.kind !== "none" && (
                  <MenuItem icon={<CalendarDays className="size-4" />} title="Today's scheduled content"
                    sub={`${today.kind === "video" ? "Video" : "Post"} · picks topic & product`}
                    onClick={() => { setMenu(false); generate.mutate(undefined); }} />
                )}
                <MenuItem icon={<ImageIcon className="size-4" />} title="A post" sub="Festival, trend or product – ~1 min"
                  onClick={() => { setMenu(false); generate.mutate("post"); }} />
                <MenuItem icon={<Film className="size-4" />} title="A video" sub="Product promo, 16:9 + 9:16 – ~5 min"
                  onClick={() => { setMenu(false); generate.mutate("video"); }} />
              </div>
            )}
          </div>
          <Link to="/create"><Button variant="primary" icon={<Sparkles className="size-4" />}>Create from URL</Button></Link>
        </div>
      </div>

      {/* week strip */}
      {meta && (
        <div className="mt-6 grid grid-cols-7 gap-2">
          {meta.week.map((d, i) => (
            <div key={d.date} className={clsx("rounded-xl px-3 py-2.5 ring-1", i === 0 ? "bg-ink-900 text-white ring-ink-900" : "bg-white ring-stone-200/80")}>
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
      <PendingOccasionsBanner />

      {/* filters */}
      <div className="mt-8 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 rounded-xl bg-white p-1 ring-1 ring-stone-200/80">
          {TABS.map((t) => {
            const n = count(t);
            return (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={clsx("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition",
                  tab === t.id ? "bg-ink-900 text-white" : "text-stone-600 hover:bg-stone-100")}>
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
        <label className="ml-auto flex w-full items-center gap-2 rounded-xl bg-white px-3 py-2 ring-1 ring-stone-200/80 focus-within:ring-ink-900 sm:w-72">
          <Search className="size-4 text-stone-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search topic, product, website…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-stone-400" />
        </label>
      </div>

      {/* grid */}
      <div className="mt-6">
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
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => <div key={i} className="shimmer h-80 rounded-2xl bg-stone-200/60" />)}
          </div>
        ) : items.length === 0 ? (
          <EmptyState icon={<Inbox className="size-6" />}
            title={tab === "review" ? "Nothing waiting for review" : "No content here yet"}
            text={tab === "all" && !search ? "The agent prepares tomorrow's content every evening. Or create something right now." : "Try another filter or search."}
            action={tab === "all" && !search ? <Button variant="primary" icon={<Wand2 className="size-4" />} onClick={() => generate.mutate(undefined)}>Generate today's content</Button> : undefined} />
        ) : (
          <div className="grid grid-cols-1 items-start gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((item) => (
              <ItemCard key={item.id} item={item} busy={action.isPending}
                onAction={(id, a) => action.mutate({ id, a })} />
            ))}
          </div>
        )}
        {data && data.total > items.length && (
          <p className="mt-6 text-center text-sm text-stone-400">Showing {items.length} of {data.total}</p>
        )}
      </div>
    </div>
  );
}

function MenuItem({ icon, title, sub, onClick }: { icon: React.ReactNode; title: string; sub: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-stone-50">
      <span className="mt-0.5 text-stone-500">{icon}</span>
      <span><span className="block text-sm font-semibold">{title}</span><span className="block text-xs text-stone-500">{sub}</span></span>
    </button>
  );
}
