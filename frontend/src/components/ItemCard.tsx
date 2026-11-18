import { Link } from "react-router-dom";
import clsx from "clsx";
import { AlertTriangle, Check, Film, Globe, ImageIcon, Loader2, Play, ShieldCheck, Square, Trash2, X } from "lucide-react";
import type { Item } from "../lib/api";
import { displayTitle, fmtDate, pretty } from "../lib/ui";
import { ProgressBar, StatusBadge } from "./ui";

export default function ItemCard({ item, onAction, busy }: {
  item: Item;
  onAction: (id: number, action: "approve" | "reject" | "stop" | "delete") => void;
  busy?: boolean;
}) {
  const generating = item.status === "generating" || item.status === "queued";
  const video = item.kind === "video";

  return (
    <div className="group flex flex-col overflow-hidden rounded-2xl bg-white ring-1 ring-stone-200/80 transition hover:-translate-y-0.5 hover:shadow-lg hover:shadow-stone-900/5">
      <Link to={`/items/${item.id}`} className="relative block bg-stone-100">
        <div className={clsx("relative w-full overflow-hidden", video ? "aspect-video" : "aspect-[4/5]")}>
          {item.thumb && !generating ? (
            <img src={item.thumb} alt="" loading="lazy" className="size-full object-cover transition duration-500 group-hover:scale-[1.03]" />
          ) : (
            <div className={clsx("grid size-full place-items-center bg-gradient-to-br from-stone-100 to-stone-200", generating && "shimmer")}>
              {generating ? <Loader2 className="size-7 animate-spin text-stone-400" /> : video ? <Film className="size-8 text-stone-300" /> : <ImageIcon className="size-8 text-stone-300" />}
            </div>
          )}
          {video && item.thumb && !generating && (
            <div className="absolute inset-0 grid place-items-center bg-black/0 transition group-hover:bg-black/20">
              <span className="grid size-12 place-items-center rounded-full bg-white/90 shadow-lg backdrop-blur transition group-hover:scale-110">
                <Play className="ml-0.5 size-5 fill-ink-900 text-ink-900" />
              </span>
            </div>
          )}
          <div className="absolute left-3 top-3 flex gap-1.5">
            <StatusBadge status={item.status} className="bg-white/95 shadow-sm backdrop-blur" />
          </div>
          <div className="absolute bottom-3 left-3 flex gap-1.5">
            {item.quality && item.quality.passed !== null && !generating && (
              <span title={item.quality.passed ? "AI quality check passed" : `AI quality check: ${item.quality.issues} thing(s) to look at`}
                className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold shadow-sm",
                  item.quality.passed ? "bg-emerald-50/95 text-emerald-700" : "bg-amber-50/95 text-amber-700")}>
                {item.quality.passed ? <ShieldCheck className="size-3" /> : <AlertTriangle className="size-3" />}
                {item.quality.score ? `${item.quality.score}/10` : item.quality.passed ? "OK" : "Check"}
              </span>
            )}
          </div>
          <span className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-ink-900/80 px-2 py-0.5 text-[11px] font-semibold text-white backdrop-blur">
            {video ? <Film className="size-3" /> : <ImageIcon className="size-3" />} {video ? "Video" : "Post"}
          </span>
        </div>
      </Link>

      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <span className="font-medium text-stone-700">{fmtDate(item.date)}</span>
          {item.source_url ? (
            <span className="inline-flex min-w-0 items-center gap-1 truncate"><Globe className="size-3 shrink-0" />{new URL(item.source_url).hostname.replace("www.", "")}</span>
          ) : item.product ? <span className="truncate">· {item.product}</span> : null}
        </div>
        <Link to={`/items/${item.id}`} className="line-clamp-2 font-semibold leading-snug text-stone-900 hover:text-brand-700">
          {displayTitle(item)}
        </Link>

        {generating ? (
          <div className="mt-auto space-y-1.5 pt-2">
            <ProgressBar value={item.progress} />
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1 truncate text-xs text-stone-500">{item.stage || "Starting…"}</div>
              <button disabled={busy} onClick={() => onAction(item.id, "stop")} title="Stop generating" aria-label="Stop generating"
                className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-stone-500 ring-1 ring-stone-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-50">
                <Square className="size-3" /> Stop
              </button>
            </div>
          </div>
        ) : (
          <>
            {(item.format || item.theme) && (
              <div className="truncate text-xs text-stone-400">{[item.format, item.theme].filter(Boolean).map(pretty).join(" · ")}</div>
            )}
            {["rejected", "failed"].includes(item.status) && (
              <div className="mt-auto flex justify-end pt-2">
                <button disabled={busy} onClick={() => onAction(item.id, "delete")} title="Delete" aria-label="Delete"
                  className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-stone-500 ring-1 ring-stone-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-50">
                  <Trash2 className="size-3.5" /> Delete
                </button>
              </div>
            )}
            {item.status === "pending_approval" && (
              <div className="mt-auto flex gap-2 pt-2">
                <button disabled={busy} onClick={() => onAction(item.id, "approve")}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">
                  <Check className="size-3.5" /> Approve
                </button>
                <button disabled={busy} onClick={() => onAction(item.id, "reject")} title="Reject" aria-label="Reject"
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-stone-500 ring-1 ring-stone-200 hover:bg-stone-50 hover:text-red-600 disabled:opacity-50">
                  <X className="size-3.5" />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
