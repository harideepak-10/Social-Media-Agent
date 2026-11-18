import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, ChevronDown, Download, ExternalLink, Eye, Hash, Loader2, RefreshCw, Send, ShieldCheck, Square, Trash2, X, XCircle } from "lucide-react";
import { api, type ItemDetail as TItem, type Platform } from "../lib/api";
import { ORIGIN, PLATFORMS, displayTitle, downloadHref, finalCaption, fmtDate, pretty, sourceLabel, workerText } from "../lib/ui";
import { Button, Card, Chip, Confirm, ProgressBar, StatusBadge, useToast } from "../components/ui";

type Action = "approve" | "reject" | "regenerate" | "publish" | "stop" | "check";

export default function ItemDetail() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const { data: item, isLoading, error } = useQuery({
    queryKey: ["item", id],
    queryFn: () => api.item(id),
    refetchInterval: (q) => (["generating", "queued"].includes(q.state.data?.status ?? "") ? 2500 : false),
  });

  // ── editable state ──
  const [captions, setCaptions] = useState<TItem["captions"]>({});
  const [tags, setTags] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [tab, setTab] = useState<Platform>("instagram");
  const [showFinal, setShowFinal] = useState(false);
  const [confirm, setConfirm] = useState<Action | "delete" | null>(null);

  useEffect(() => {
    if (!item) return;
    setCaptions(item.captions ?? {});
    setTags(item.hashtags.split(/\s+/).filter(Boolean));
    setPlatforms(item.platforms);
    if (item.platforms.length && !item.platforms.includes(tab)) setTab(item.platforms[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id, item?.status, item?.hashtags, item?.captions && JSON.stringify(item.captions), item?.platforms.join()]);

  const dirty = useMemo(() => !!item && (
    JSON.stringify(captions) !== JSON.stringify(item.captions ?? {}) ||
    tags.join(" ") !== item.hashtags.split(/\s+/).filter(Boolean).join(" ") ||
    platforms.join() !== item.platforms.join()
  ), [item, captions, tags, platforms]);

  const refresh = (data?: TItem) => {
    if (data) qc.setQueryData(["item", id], data);
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["meta"] });
  };

  const save = useMutation({
    mutationFn: () => api.update(id, { captions, hashtags: tags.join(" "), platforms }),
    onSuccess: (d) => { refresh(d); toast("ok", "Changes saved"); },
    onError: (e: Error) => toast("error", e.message),
  });

  const del = useMutation({
    mutationFn: () => api.deleteItem(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
      toast("ok", "Deleted");
      nav("/");
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const act = useMutation({
    mutationFn: async (a: Action) => {
      if (dirty && (a === "approve" || a === "publish")) await api.update(id, { captions, hashtags: tags.join(" "), platforms });
      return api.action(id, a);
    },
    onSuccess: (d, a) => {
      refresh(d);
      const msg: Record<Action, string> = {
        approve: `Approved – goes out ${fmtDate(d.date)} at ${meta?.times.publish ?? "publish time"}`,
        reject: "Rejected",
        regenerate: d.source_url ? "Regenerating from the same link…" : "Making a fresh version – it will appear in the queue",
        publish: "Publishing now…",
        stop: "Stopped – nothing will be saved for this one",
        check: d.quality_report && "passed" in d.quality_report && d.quality_report.passed ? "Quality check passed" : "Quality check done – see the results",
      };
      toast("ok", msg[a]);
      if (a === "regenerate" && !d.source_url) nav("/");
      if (a === "publish") setTimeout(() => qc.invalidateQueries({ queryKey: ["item", id] }), 4000);
    },
    onError: (e: Error) => toast("error", e.message),
  });

  if (isLoading) return <div className="grid h-full place-items-center"><Loader2 className="size-6 animate-spin text-stone-400" /></div>;
  if (error || !item) return (
    <div className="mx-auto max-w-xl px-6 py-20 text-center">
      <p className="text-stone-500">{(error as Error)?.message ?? "Not found"}</p>
      <Link to="/" className="mt-4 inline-block text-sm font-semibold text-brand-700">← Back to queue</Link>
    </div>
  );

  const generating = item.status === "generating" || item.status === "queued";
  const queued = item.status === "queued";
  const pc = meta?.video_worker;
  const editable = !generating && !["published", "dry_run"].includes(item.status);
  const warning = item.error && item.status !== "failed" ? item.error : "";

  return (
    <div className="mx-auto max-w-7xl px-5 py-8 md:px-10">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-medium text-stone-500 hover:text-stone-900">
        <ArrowLeft className="size-4" /> Content queue
      </Link>

      {/* title */}
      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 basis-[22rem]">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={item.status} />
            <Chip>{item.kind === "video" ? "Video" : "Post"}</Chip>
            {item.product && <Chip>{item.product}</Chip>}
            {item.format && <Chip>{pretty(item.format)}</Chip>}
            {item.theme && <Chip>{pretty(item.theme)}</Chip>}
          </div>
          <h1 className="mt-3 text-2xl font-extrabold leading-tight tracking-tight md:text-3xl">{displayTitle(item)}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-stone-500">
            <span>For {fmtDate(item.date, { weekday: "long", day: "numeric", month: "long" })}</span>
            <span>Source: {sourceLabel(item.source)}</span>
            {ORIGIN[item.origin] && <span>Made by: {ORIGIN[item.origin]}</span>}
            {item.source_url && (
              <a href={item.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline">
                {item.source_url.replace(/^https?:\/\//, "")} <ExternalLink className="size-3" />
              </a>
            )}
          </div>
          {item.angle && <p className="mt-3 max-w-3xl whitespace-pre-line text-sm text-stone-600">{item.angle}</p>}
          {item.notes && <p className="mt-1 text-sm text-stone-500">Your focus: <em>{item.notes}</em></p>}
        </div>

        {!generating && (
          <div className="flex flex-wrap gap-2">
            {["pending_approval", "rejected", "failed", "partial"].includes(item.status) && item.media && (
              <Button variant="success" icon={<Check className="size-4" />} loading={act.isPending && act.variables === "approve"}
                onClick={() => act.mutate("approve")}>Approve</Button>
            )}
            {["pending_approval", "approved"].includes(item.status) && (
              <Button variant="danger" icon={<X className="size-4" />} onClick={() => act.mutate("reject")}
                loading={act.isPending && act.variables === "reject"}>Reject</Button>
            )}
            <Button icon={<RefreshCw className="size-4" />} onClick={() => setConfirm("regenerate")}
              loading={act.isPending && act.variables === "regenerate"}>Regenerate</Button>
            {editable && item.media && (
              <Button variant="dark" icon={<Send className="size-4" />} onClick={() => setConfirm("publish")}
                loading={act.isPending && act.variables === "publish"}>Publish now</Button>
            )}
            {["rejected", "failed"].includes(item.status) && (
              <Button variant="danger" icon={<Trash2 className="size-4" />} loading={del.isPending}
                onClick={() => setConfirm("delete")}>Delete</Button>
            )}
          </div>
        )}
      </div>

      {/* banners */}
      {item.status === "approved" && (
        <Banner tone="ok" icon={<CheckCircle2 className="size-4" />}>
          Approved. It will be {meta && Object.values(meta.platforms).some(Boolean) ? "posted" : "marked as published (test mode)"} on {fmtDate(item.date)} at {meta?.times.publish}.
        </Banner>
      )}
      {item.status === "failed" && (
        <Banner tone="error" icon={<XCircle className="size-4" />}>
          <div className="font-semibold">Generation failed</div>
          <div className="mt-1 whitespace-pre-wrap font-mono text-xs">{item.error}</div>
        </Banner>
      )}
      {warning && <Banner tone="warn" icon={<AlertTriangle className="size-4" />}>{warning}</Banner>}

      {generating ? (
        <Card className="mt-8 p-8 md:p-12">
          <div className="mx-auto max-w-xl text-center">
            <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-brand-50"><Loader2 className="size-7 animate-spin text-brand-600" /></div>
            <h2 className="mt-5 text-xl font-bold">{queued ? "Waiting for your PC to make this video" : `The agent is creating your ${item.kind}`}</h2>
            <p className="mt-1 text-sm text-stone-500">
              {queued
                ? "Videos are made on your PC because this server is too small for them. Start run_video_worker.bat on your PC – it picks this up within a minute."
                : item.kind === "video" ? "Videos take about 4–8 minutes (16:9 and 9:16 versions)." : "Posts take about a minute."} You can leave this page – it keeps working.
            </p>
            {pc?.mode === "pc" && item.kind === "video" && (
              <div className={clsx("mx-auto mt-4 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1",
                pc.online ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200")}>
                <span className={clsx("size-1.5 rounded-full", pc.online ? "bg-emerald-500" : "bg-amber-500")} />
                {workerText(pc)}
              </div>
            )}
            <ProgressBar value={item.progress} className="mt-8 h-2" />
            <div className="mt-3 flex justify-between text-sm">
              <span className="font-medium text-stone-700">{item.stage || "Starting…"}</span>
              <span className="tabular-nums text-stone-400">{item.progress}%</span>
            </div>
            <Button variant="danger" className="mt-8" icon={<Square className="size-4" />}
              loading={act.isPending && act.variables === "stop"} onClick={() => setConfirm("stop")}>Stop generating</Button>
          </div>
        </Card>
      ) : (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          {/* preview */}
          <div className="space-y-6">
            <Preview item={item} />
            <QualityCard item={item} checking={act.isPending && act.variables === "check"} onCheck={() => act.mutate("check")} />
            <Details item={item} />
          </div>

          {/* captions */}
          <div className="space-y-6">
            <Card className="p-5">
              <div className="flex items-center justify-between">
                <h2 className="font-bold">Post to</h2>
                <span className="text-xs text-stone-400">{meta && !Object.values(meta.platforms).some(Boolean) ? "Test mode – nothing is posted" : ""}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {PLATFORMS.map((p) => {
                  const on = platforms.includes(p.id);
                  return (
                    <button key={p.id} disabled={!editable}
                      onClick={() => setPlatforms((cur) => on ? cur.filter((x) => x !== p.id) : [...cur, p.id])}
                      className={clsx("flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ring-1 transition disabled:opacity-60",
                        on ? "bg-ink-900 text-white ring-ink-900" : "bg-white text-stone-500 ring-stone-200 hover:text-stone-800")}>
                      <span className="size-2 rounded-full" style={{ background: on ? p.color : "#d6d3d1" }} />
                      {p.label}
                      {meta && <span className={clsx("text-[10px] font-medium", on ? "text-white/50" : "text-stone-400")}>{meta.platforms[p.id] ? "live" : "test"}</span>}
                    </button>
                  );
                })}
              </div>
              {item.kind === "video" && item.media_vertical && (
                <p className="mt-3 text-xs text-stone-500">Instagram & Facebook get the 9:16 Reel, LinkedIn gets the 16:9 video.</p>
              )}
            </Card>

            <Card className="overflow-hidden">
              <div className="flex border-b border-stone-200">
                {PLATFORMS.map((p) => (
                  <button key={p.id} onClick={() => setTab(p.id)}
                    className={clsx("relative flex-1 px-4 py-3 text-sm font-semibold transition",
                      tab === p.id ? "text-stone-900" : "text-stone-400 hover:text-stone-700")}>
                    {p.label}
                    {tab === p.id && <span className="absolute inset-x-4 bottom-0 h-0.5 rounded-full" style={{ background: p.color }} />}
                  </button>
                ))}
              </div>
              <div className="p-5">
                {(() => {
                  const p = PLATFORMS.find((x) => x.id === tab)!;
                  const text = captions[tab] ?? "";
                  const final = finalCaption(text, tags.join(" "), tab);
                  const over = final.length > p.limit;
                  return (
                    <>
                      {showFinal ? (
                        <div className="min-h-56 whitespace-pre-wrap rounded-xl bg-stone-50 p-4 text-sm leading-relaxed ring-1 ring-stone-200">{final || <span className="text-stone-400">Empty</span>}</div>
                      ) : (
                        <textarea value={text} disabled={!editable}
                          onChange={(e) => setCaptions((c) => ({ ...c, [tab]: e.target.value }))}
                          placeholder={`Caption for ${p.label}`}
                          className="min-h-56 w-full resize-y rounded-xl bg-stone-50 p-4 text-sm leading-relaxed outline-none ring-1 ring-stone-200 focus:bg-white focus:ring-2 focus:ring-ink-900 disabled:opacity-70" />
                      )}
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <button onClick={() => setShowFinal((s) => !s)} className="inline-flex items-center gap-1 font-medium text-stone-500 hover:text-stone-900">
                          <Eye className="size-3.5" /> {showFinal ? "Edit caption" : "Preview with hashtags"}
                        </button>
                        <span className={clsx("tabular-nums", over ? "font-semibold text-red-600" : "text-stone-400")}>
                          {final.length.toLocaleString()}{p.limit < 10000 && ` / ${p.limit.toLocaleString()}`}
                        </span>
                      </div>
                    </>
                  );
                })()}
              </div>
            </Card>

            <Card className="p-5">
              <h2 className="flex items-center gap-2 font-bold"><Hash className="size-4 text-stone-400" /> Hashtags</h2>
              <TagInput tags={tags} onChange={setTags} disabled={!editable} />
              <p className="mt-2 text-xs text-stone-400">Added to each caption if missing. LinkedIn uses the first 5.</p>
            </Card>

            {editable && (
              <div className={clsx(dirty && "sticky bottom-4", "flex items-center justify-between gap-3 rounded-2xl px-5 py-3 shadow-lg ring-1 transition",
                dirty ? "bg-ink-900 text-white ring-ink-900" : "bg-white text-stone-400 ring-stone-200")}>
                <span className="text-sm">{dirty ? "You have unsaved changes" : "All changes saved"}</span>
                <div className="flex gap-2">
                  {dirty && <Button variant="ghost" className="text-white/70 hover:bg-white/10 hover:text-white"
                    onClick={() => { setCaptions(item.captions ?? {}); setTags(item.hashtags.split(/\s+/).filter(Boolean)); setPlatforms(item.platforms); }}>Discard</Button>}
                  <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
                </div>
              </div>
            )}

            <Results item={item} />
          </div>
        </div>
      )}

      <Confirm open={confirm === "publish"} title="Publish now?"
        body={<>This sends it to {platforms.map((p) => PLATFORMS.find((x) => x.id === p)?.label).join(", ")} right away{meta && !Object.values(meta.platforms).some(Boolean) ? " (test mode – nothing is actually posted)" : ""}.</>}
        confirmLabel="Publish now" variant="dark" onConfirm={() => act.mutate("publish")} onClose={() => setConfirm(null)} />
      <Confirm open={confirm === "regenerate"} title="Make a new version?"
        body={item.source_url ? "The agent rebuilds this from the same link. The current version is replaced." : "This one is rejected and the agent creates a fresh one for the same day, with a different design."}
        confirmLabel="Regenerate" onConfirm={() => act.mutate("regenerate")} onClose={() => setConfirm(null)} />
      <Confirm open={confirm === "delete"} title="Delete this item?"
        body="The item and its poster/video files are removed for good (also from cloud storage). This can't be undone."
        confirmLabel="Delete" variant="danger" onConfirm={() => del.mutate()} onClose={() => setConfirm(null)} />
      <Confirm open={confirm === "stop"} title="Stop generating?"
        body="The agent stops at its next step and throws away what it made so far. You can click Regenerate later to try again."
        confirmLabel="Stop" variant="danger" onConfirm={() => act.mutate("stop")} onClose={() => setConfirm(null)} />
    </div>
  );
}

// ── pieces ─────────────────────────────────────────────────────────────────
function Banner({ tone, icon, children }: { tone: "ok" | "warn" | "error"; icon: React.ReactNode; children: React.ReactNode }) {
  const cls = { ok: "bg-emerald-50 text-emerald-800 ring-emerald-200", warn: "bg-amber-50 text-amber-800 ring-amber-200", error: "bg-red-50 text-red-800 ring-red-200" }[tone];
  return <div className={clsx("mt-6 flex gap-3 rounded-xl px-4 py-3 text-sm ring-1", cls)}><span className="mt-0.5">{icon}</span><div className="min-w-0 flex-1">{children}</div></div>;
}

function Preview({ item }: { item: TItem }) {
  const [view, setView] = useState<"wide" | "tall">("wide");
  if (!item.media) return <Card className="grid aspect-video place-items-center text-sm text-stone-400">No media</Card>;
  if (item.kind === "post") {
    return (
      <Card className="overflow-hidden">
        <div className="bg-stone-100 p-4 md:p-6">
          <img src={item.media} alt={item.topic} className="mx-auto max-h-[78vh] rounded-lg shadow-xl shadow-stone-900/10" />
        </div>
        <div className="flex items-center justify-between px-5 py-3 text-sm">
          <SavedAs label="1080 × 1350" file={item.files?.[0]} />
          <a href={downloadHref(item.media)} download className="inline-flex items-center gap-1.5 font-semibold text-stone-700 hover:text-brand-700"><Download className="size-4" /> Download</a>
        </div>
      </Card>
    );
  }
  const src = view === "tall" && item.media_vertical ? item.media_vertical : item.media;
  return (
    <Card className="overflow-hidden">
      {item.media_vertical && (
        <div className="flex gap-1 border-b border-stone-200 p-2">
          {([["wide", "16:9 · LinkedIn"], ["tall", "9:16 · Reels"]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setView(k)}
              className={clsx("rounded-lg px-3 py-1.5 text-sm font-semibold", view === k ? "bg-ink-900 text-white" : "text-stone-500 hover:bg-stone-100")}>{label}</button>
          ))}
        </div>
      )}
      <div className="bg-ink-900">
        <video key={src} src={src} poster={item.thumb} controls playsInline
          className={clsx("mx-auto block", view === "tall" ? "max-h-[78vh]" : "w-full")} />
      </div>
      <div className="flex items-center justify-between px-5 py-3 text-sm">
        <SavedAs label={view === "tall" ? "1080 × 1920" : "1920 × 1080"}
          file={item.files?.find((f) => (view === "tall" ? f.includes("9x16") || f.includes("vertical") : !f.includes("9x16"))) ?? item.files?.[0]} />
        <a href={downloadHref(src)} download className="inline-flex items-center gap-1.5 font-semibold text-stone-700 hover:text-brand-700"><Download className="size-4" /> Download</a>
      </div>
    </Card>
  );
}

function SavedAs({ label, file }: { label: string; file?: string }) {
  return (
    <span className="min-w-0 text-stone-500">
      {label}
      {file && <> · <span className="font-mono text-xs text-stone-600" title="Saved in your project folder">{file}</span></>}
    </span>
  );
}

type Scene = { eyebrow?: string; headline?: string; accent?: string; bullets?: { text?: string }[]; badges?: { value?: string; label?: string }[]; voice?: string };

function QualityCard({ item, checking, onCheck }: { item: TItem; checking: boolean; onCheck: () => void }) {
  const q = item.quality_report && "checks" in item.quality_report ? item.quality_report : null;
  const tone = !q ? "stone" : q.passed ? "emerald" : q.passed === false ? "amber" : "stone";
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className={clsx("size-5", tone === "emerald" ? "text-emerald-600" : tone === "amber" ? "text-amber-600" : "text-stone-400")} />
          <h2 className="font-bold">AI quality check</h2>
          {q && (
            <span className={clsx("rounded-full px-2 py-0.5 text-xs font-bold ring-1",
              tone === "emerald" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : tone === "amber" ? "bg-amber-50 text-amber-700 ring-amber-200" : "bg-stone-50 text-stone-600 ring-stone-200")}>
              {q.passed ? "Passed" : q.passed === false ? "Needs a look" : "Not checked"}{q.score ? ` · ${q.score}/10` : ""}
            </span>
          )}
        </div>
        {item.media && (
          <Button variant="outline" className="px-3 py-1.5 text-xs" icon={<RefreshCw className="size-3.5" />} loading={checking} onClick={onCheck}>
            {q ? "Check again" : "Check quality"}
          </Button>
        )}
      </div>
      {!q ? (
        <p className="mt-3 text-sm text-stone-500">{checking ? "The AI is looking at it…" : "Not checked yet. New posts and videos are checked automatically."}</p>
      ) : (
        <>
          {q.summary && <p className="mt-3 text-sm text-stone-700">{q.summary}</p>}
          {q.problems.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {q.problems.map((p, i) => (
                <li key={i} className="flex gap-2 text-sm text-amber-800"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{p}</li>
              ))}
            </ul>
          )}
          <div className="mt-4 grid gap-1.5 sm:grid-cols-2">
            {q.checks.map((c) => (
              <div key={c.name} className="flex items-center gap-2 text-xs">
                {c.status === "ok" ? <CheckCircle2 className="size-3.5 shrink-0 text-emerald-600" /> :
                  c.status === "warn" ? <AlertTriangle className="size-3.5 shrink-0 text-amber-500" /> : <XCircle className="size-3.5 shrink-0 text-red-600" />}
                <span className="font-semibold text-stone-700">{c.name}</span>
                <span className="truncate text-stone-400">{c.detail}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function Details({ item }: { item: TItem }) {
  const [open, setOpen] = useState(false);
  const s = item.script;
  if (!s || typeof s === "string") return null;
  const scenes = (s.scenes as Scene[] | undefined) ?? [];
  const intro = s.intro as Scene | undefined;
  const outro = s.outro as Scene | undefined;
  return (
    <Card>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span className="font-bold">{item.kind === "video" ? "Storyboard" : "Design details"}</span>
        <ChevronDown className={clsx("size-4 text-stone-400 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-stone-100 px-5 py-4 text-sm">
          {item.kind === "video" ? (
            <ol className="space-y-3">
              {intro && <SceneRow n="Intro" s={intro} />}
              {scenes.map((sc, i) => <SceneRow key={i} n={`Scene ${i + 1}`} s={sc} />)}
              {s.grid ? <SceneRow n="Summary" s={s.grid as Scene} /> : null}
              {outro && <SceneRow n="Outro" s={outro} />}
            </ol>
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
              {Object.entries(s).filter(([, v]) => typeof v === "string" && v).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-stone-400">{pretty(k)}</dt><dd className="font-medium">{String(v)}</dd></div>
              ))}
            </dl>
          )}
        </div>
      )}
    </Card>
  );
}

function SceneRow({ n, s }: { n: string; s: Scene }) {
  return (
    <li className="rounded-xl bg-stone-50 p-3.5 ring-1 ring-stone-200/70">
      <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-stone-400">
        {n}{s.eyebrow && <span className="text-brand-600">· {s.eyebrow}</span>}
      </div>
      <div className="mt-1 font-semibold">{s.headline} <span className="text-brand-700">{s.accent}</span></div>
      {!!s.bullets?.length && <ul className="mt-1.5 list-inside list-disc text-stone-600">{s.bullets.map((b, i) => <li key={i}>{b.text}</li>)}</ul>}
      {!!s.badges?.length && <div className="mt-2 flex flex-wrap gap-1.5">{s.badges.map((b, i) => <Chip key={i} className="bg-amber-50 text-amber-800">{b.value} · {b.label}</Chip>)}</div>}
      {s.voice && <p className="mt-2 border-l-2 border-stone-300 pl-3 text-stone-500 italic">“{s.voice}”</p>}
    </li>
  );
}

function Results({ item }: { item: TItem }) {
  const entries = Object.entries(item.results ?? {});
  if (!entries.length) return null;
  return (
    <Card className="p-5">
      <h2 className="font-bold">Publish results</h2>
      <ul className="mt-3 space-y-2">
        {entries.map(([p, r]) => (
          <li key={p} className="text-sm">
            <div className="flex items-center gap-2">
              {r!.ok ? <CheckCircle2 className="size-4 text-emerald-600" /> : <XCircle className="size-4 text-red-600" />}
              <span className="font-semibold">{PLATFORMS.find((x) => x.id === p)?.label ?? p}</span>
              {r!.dry_run && <Chip>test mode – not posted</Chip>}
              {r!.id && <span className="text-xs text-stone-400">id {r!.id}</span>}
            </div>
            {r!.error && <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-red-50 p-2 text-xs text-red-700">{r!.error}</pre>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function TagInput({ tags, onChange, disabled }: { tags: string[]; onChange: (t: string[]) => void; disabled?: boolean }) {
  const [v, setV] = useState("");
  const add = (raw: string) => {
    const t = raw.trim().replace(/^#*/, "").replace(/[^\p{L}\p{N}_]/gu, "");
    if (t && !tags.some((x) => x.toLowerCase() === `#${t}`.toLowerCase())) onChange([...tags, `#${t}`]);
    setV("");
  };
  return (
    <div className={clsx("mt-3 flex flex-wrap gap-1.5 rounded-xl bg-stone-50 p-2 ring-1 ring-stone-200 focus-within:ring-2 focus-within:ring-ink-900", disabled && "opacity-70")}>
      {tags.map((t, i) => (
        <span key={t} className={clsx("inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold",
          i < 5 ? "bg-white text-stone-800 ring-1 ring-stone-200" : "bg-stone-100 text-stone-500")}>
          {t}
          {!disabled && <button onClick={() => onChange(tags.filter((x) => x !== t))} className="text-stone-400 hover:text-red-600"><X className="size-3" /></button>}
        </span>
      ))}
      {!disabled && (
        <input value={v} onChange={(e) => setV(e.target.value)} placeholder="Add hashtag…"
          onKeyDown={(e) => {
            if (["Enter", " ", ","].includes(e.key)) { e.preventDefault(); add(v); }
            if (e.key === "Backspace" && !v && tags.length) onChange(tags.slice(0, -1));
          }}
          onBlur={() => v && add(v)}
          className="min-w-28 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-stone-400" />
      )}
    </div>
  );
}
