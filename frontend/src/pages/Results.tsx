import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BarChart3, Eye, Heart, Lightbulb, Loader2, MessageCircle, MousePointerClick, Play, RefreshCw, Share2 } from "lucide-react";
import { api, type InsightGroup, type Insights } from "../lib/api";
import { PLATFORMS, ago, pretty } from "../lib/ui";
import { Button, Card, EmptyState, useToast } from "../components/ui";

const PERIODS = [7, 30, 90] as const;
const TILES: [keyof Insights["totals"], string, typeof Heart][] = [
  ["engagement", "Engagement", BarChart3], ["likes", "Likes", Heart], ["comments", "Comments", MessageCircle],
  ["shares", "Shares", Share2], ["reach", "Reach", Eye], ["views", "Views", Play], ["clicks", "Clicks", MousePointerClick],
];

export default function Results() {
  const qc = useQueryClient();
  const toast = useToast();
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const { data, isLoading } = useQuery({ queryKey: ["insights", days], queryFn: () => api.insights(days) });
  const refresh = useMutation({
    mutationFn: () => api.refreshInsights(days),
    onSuccess: (r) => {
      qc.setQueryData(["insights", days], r.report);
      toast("ok", r.summary ? `Updated ${r.refreshed} post(s) and wrote a new summary` : `Updated ${r.refreshed} post(s) – a summary needs at least 3 measured posts`);
    },
    onError: (e: Error) => toast("error", e.message),
  });

  return (
    <div className="mx-auto max-w-6xl px-5 py-8 md:px-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Results</h1>
          <p className="mt-1 text-sm text-stone-500">How your posts did on LinkedIn, Facebook and Instagram – and what the agent learns from it.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-xl bg-white p-1 ring-1 ring-stone-200/80" role="tablist" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p} role="tab" aria-selected={days === p} onClick={() => setDays(p)}
                className={clsx("rounded-lg px-3 py-1.5 text-sm font-medium", days === p ? "bg-ink-900 text-white" : "text-stone-600 hover:bg-stone-100")}>
                {p} days
              </button>
            ))}
          </div>
          <Button icon={<RefreshCw className="size-4" />} loading={refresh.isPending} onClick={() => refresh.mutate()}>Refresh</Button>
        </div>
      </div>

      {isLoading || !data ? (
        <div className="mt-10 flex items-center gap-2 text-sm text-stone-500"><Loader2 className="size-4 animate-spin" /> Loading…</div>
      ) : data.published === 0 ? (
        <div className="mt-8">
          <EmptyState icon={<BarChart3 className="size-6" />} title="Nothing posted in this period"
            text="Results appear here once approved content has been posted to a connected account. Test-mode posts have no numbers."
            action={<Link to="/settings?tab=connections"><Button variant="primary">Connect accounts</Button></Link>} />
        </div>
      ) : (
        <>
          <SummaryCard data={data} />

          <section aria-label="Totals" className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {TILES.map(([k, label, Icon]) => (
              <div key={k} className={clsx("rounded-2xl bg-white p-4 ring-1 ring-stone-200/80", k === "engagement" && "col-span-2 sm:col-span-1")}>
                <div className="flex items-center gap-1.5 text-xs font-semibold text-stone-500"><Icon className="size-3.5" />{label}</div>
                <div className="mt-1 text-2xl font-extrabold tabular-nums">{(data.totals[k] ?? 0).toLocaleString()}</div>
              </div>
            ))}
          </section>
          <p className="mt-2 text-xs text-stone-500">
            {data.measured} of {data.published} posted item{data.published === 1 ? "" : "s"} have numbers. Engagement = likes + comments + shares. Numbers refresh every 6 hours.
          </p>

          {Object.keys(data.per_platform).length > 0 && (
            <Card className="mt-6 p-4 sm:p-6">
              <h2 className="font-bold">By platform</h2>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[28rem] text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-stone-500">
                      <th className="py-2 pr-3 font-semibold">Platform</th>
                      {["likes", "comments", "shares", "reach", "views", "clicks"].map((k) => <th key={k} className="py-2 pr-3 text-right font-semibold">{pretty(k)}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.per_platform).map(([p, m]) => (
                      <tr key={p} className="border-t border-stone-100">
                        <td className="py-2 pr-3 font-semibold">
                          <span className="mr-2 inline-block size-2 rounded-full align-middle" style={{ background: PLATFORMS.find((x) => x.id === p)?.color }} />
                          {PLATFORMS.find((x) => x.id === p)?.label ?? p}
                        </td>
                        {(["likes", "comments", "shares", "reach", "views", "clicks"] as const).map((k) => (
                          <td key={k} className="py-2 pr-3 text-right tabular-nums text-stone-700">{(m[k] ?? 0).toLocaleString()}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Ranking title="Formats" groups={data.by_format} />
            <Ranking title="Products" groups={data.by_product} />
            <Ranking title="Day of the week" groups={data.by_weekday} />
            <Ranking title="Topic source" groups={data.by_source} />
          </div>

          {data.top.length > 0 && (
            <Card className="mt-6 p-4 sm:p-6">
              <h2 className="font-bold">Best posts</h2>
              <ol className="mt-3 divide-y divide-stone-100">
                {data.top.map((p, i) => (
                  <li key={p.id}>
                    <Link to={`/items/${p.id}`} className="flex items-center gap-3 py-2.5 hover:bg-stone-50">
                      <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-ink-900 text-xs font-bold text-white">{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{p.topic || "Untitled"}</span>
                        <span className="block truncate text-xs text-stone-500">{[p.kind === "video" ? "Video" : "Post", pretty(p.format), p.product, p.weekday].filter(Boolean).join(" · ")}</span>
                      </span>
                      <span className="shrink-0 text-right text-xs text-stone-500">
                        <b className="block text-sm tabular-nums text-stone-900">{(p.engagement ?? 0).toLocaleString()}</b>engagement
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function SummaryCard({ data }: { data: Insights }) {
  const s = data.summary;
  return (
    <Card className="mt-6 p-4 sm:p-6">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-600"><Lightbulb className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="font-bold">What worked best</h2>
          {s ? (
            <>
              <p className="mt-1 text-sm leading-relaxed text-stone-700">{s.text}</p>
              {s.tips && (
                <>
                  <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-stone-500">The agent now leans towards</div>
                  <ul className="mt-1 space-y-1 text-sm text-stone-700">
                    {s.tips.split("\n").map((t) => t.replace(/^[-•*\d.\s]+/, "").trim()).filter(Boolean).map((t) => <li key={t} className="flex gap-2"><span className="text-brand-600">→</span>{t}</li>)}
                  </ul>
                </>
              )}
              <p className="mt-2 text-[11px] text-stone-400">Written by the AI {ago(s.created_at)} from the last {s.days} days. Updated every Monday.</p>
            </>
          ) : (
            <p className="mt-1 text-sm text-stone-500">
              Once at least 3 posts have numbers, the AI writes a short summary here every Monday (or press Refresh) – and new content leans towards what works.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

/** Horizontal bars: average engagement per group, one hue, value labelled at the bar end. */
function Ranking({ title, groups }: { title: string; groups: InsightGroup[] }) {
  const max = Math.max(1, ...groups.map((g) => g.avg_engagement));
  return (
    <Card className="p-4 sm:p-6">
      <h2 className="font-bold">{title}</h2>
      <p className="text-xs text-stone-500">Average engagement per post</p>
      {groups.length === 0 ? <p className="mt-3 text-sm text-stone-400">Not enough data yet.</p> : (
        <ul className="mt-3 space-y-2.5">
          {groups.slice(0, 8).map((g) => (
            <li key={g.name} className="group" title={`${pretty(g.name)}: ${g.avg_engagement} average engagement · ${g.avg_reach} average reach · ${g.posts} post${g.posts === 1 ? "" : "s"}`}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="truncate font-medium text-stone-800">{pretty(g.name)}</span>
                <span className="shrink-0 tabular-nums text-stone-600">{g.avg_engagement.toLocaleString()} <span className="text-xs text-stone-400">· {g.posts} post{g.posts === 1 ? "" : "s"}</span></span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-stone-100">
                <div className="h-2 rounded-full bg-brand-600 transition-[width] group-hover:bg-brand-700" style={{ width: `${Math.max(2, (g.avg_engagement / max) * 100)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
