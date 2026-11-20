import type { Platform, Status } from "./api";

export const STATUS: Record<Status, { label: string; cls: string; dot: string }> = {
  generating: { label: "Generating", cls: "bg-indigo-50 text-indigo-700 ring-indigo-200", dot: "bg-indigo-500 animate-pulse" },
  queued: { label: "Waiting for PC", cls: "bg-indigo-50 text-indigo-700 ring-indigo-200", dot: "bg-indigo-300" },
  pending_approval: { label: "Needs review", cls: "bg-amber-50 text-amber-800 ring-amber-200", dot: "bg-amber-500" },
  approved: { label: "Approved", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", dot: "bg-emerald-500" },
  published: { label: "Published", cls: "bg-emerald-600 text-white ring-emerald-600", dot: "bg-white" },
  dry_run: { label: "Test run", cls: "bg-stone-100 text-stone-700 ring-stone-200", dot: "bg-stone-400" },
  partial: { label: "Partly published", cls: "bg-orange-50 text-orange-700 ring-orange-200", dot: "bg-orange-500" },
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 ring-red-200", dot: "bg-red-500" },
  rejected: { label: "Rejected", cls: "bg-stone-100 text-stone-500 ring-stone-200", dot: "bg-stone-400" },
};

export const PLATFORMS: { id: Platform; label: string; limit: number; color: string; hashtags: number }[] = [
  { id: "instagram", label: "Instagram", limit: 2200, color: "#E1306C", hashtags: 30 },
  { id: "facebook", label: "Facebook", limit: 63206, color: "#1877F2", hashtags: 30 },
  { id: "linkedin", label: "LinkedIn", limit: 3000, color: "#0A66C2", hashtags: 5 },
];

export const pretty = (s: string) =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\b(Ui|Ai|Url|Pos)\b/g, (w) => w.toUpperCase());

export function fmtDate(iso: string, opts: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" }) {
  return new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", opts);
}

export function ago(iso: string | null) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Same rule as pipeline.full_caption: append hashtags that aren't already in the caption. */
export function finalCaption(caption: string, hashtags: string, platform: Platform) {
  let tags = hashtags.split(/\s+/).filter(Boolean);
  if (platform === "linkedin") tags = tags.slice(0, 5);
  const lower = caption.toLowerCase();
  const missing = tags.filter((t) => !lower.includes(t.toLowerCase()));
  return (caption.trimEnd() + (missing.length ? "\n\n" + missing.join(" ") : "")).trim();
}

const SOURCES: Record<string, string> = {
  url: "Website link", website: "Product", festival: "Festival", event: "Event", trend: "Trend", request: "Your prompt",
};
export const sourceLabel = (s: string) => SOURCES[s] ?? (s ? pretty(s) : "—");

/** Readable title – while a link item is still generating its topic is just the URL. */
export function displayTitle(item: { topic: string; kind: string; source_url: string; status: string }) {
  if (item.source_url && (!item.topic || item.topic.endsWith(" …"))) {
    const host = item.source_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
    return `New ${item.kind} for ${host}`;
  }
  return item.topic || (item.status === "generating" ? `New ${item.kind} – picking a topic…`
    : item.status === "queued" ? `New ${item.kind} – waiting for your PC` : "Untitled");
}

/** Link that really downloads: cross-site `download` attributes are ignored by browsers, so for files in
 *  Supabase Storage we ask Supabase to send it as an attachment instead. */
export function downloadHref(src: string): string {
  if (!src) return src;
  const name = decodeURIComponent(src.split("?")[0].split("/").pop() || "download");
  if (src.includes("/storage/v1/object/public/")) return `${src}${src.includes("?") ? "&" : "?"}download=${encodeURIComponent(name)}`;
  return src;
}

export const ORIGIN: Record<string, string> = {
  schedule: "Daily schedule (evening run)",
  catch_up: "Catch-up – the server was asleep at the scheduled time",
  manual: "You clicked Generate now",
  regenerate: "You clicked Regenerate",
  url: "Create from URL",
};

/** "Your PC is online" / "last seen 5 min ago" for the video worker. */
export function workerText(w?: { mode: string; online?: boolean; name?: string; last_seen?: string | null }): string {
  if (!w || w.mode !== "pc") return "";
  if (w.online) return `Your PC${w.name ? ` (${w.name})` : ""} is online`;
  return w.last_seen ? `Your PC is offline – last seen ${ago(w.last_seen)}` : "Your PC hasn't connected yet";
}
