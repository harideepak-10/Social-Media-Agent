// Typed client for the agent's JSON API (app/api.py).

export type Status =
  | "generating" | "queued" | "pending_approval" | "approved" | "publishing" | "published" | "dry_run"
  | "partial" | "failed" | "rejected";

export type Platform = "instagram" | "facebook" | "linkedin";

export interface Item {
  id: number;
  date: string;
  kind: "video" | "post";
  status: Status;
  source: string;
  source_url: string;
  notes: string;
  topic: string;
  product: string;
  format: string;
  theme: string;
  media: string;
  media_vertical: string;
  thumb: string;
  platforms: Platform[];
  stage: string;
  progress: number;
  error: string;
  quality: { passed: boolean | null; score: number | null; issues: number } | null;
  origin: "" | "schedule" | "catch_up" | "manual" | "regenerate" | "url";
  created_at: string | null;
  published_at: string | null;
  publish_time: string;          // "HH:MM" for this item, "" = default posting time
  job: string;                   // "rebuild" while an edited video is being rebuilt
  deleted_at: string | null;     // in the bin
  missed: boolean;               // approved, but its day passed without posting
  metrics: Metrics | null;
}

export interface Metrics { likes: number; comments: number; shares: number; reach: number; views: number; clicks: number; engagement?: number }
export type PlatformMetrics = Partial<Metrics> & { fetched_at?: string; error?: string; notes?: string };

export interface PublishResult { ok: boolean; dry_run?: boolean; id: string; url?: string; error: string }

export interface QualityReport {
  passed: boolean | null;
  score: number | null;
  summary: string;
  problems: string[];
  checks: { name: string; status: "ok" | "warn" | "fail"; detail: string }[];
}

export interface ItemDetail extends Item {
  quality_report: QualityReport | Record<string, never>;
  metrics_detail: Partial<Record<Platform, PlatformMetrics>>;
  editable: { poster_text: boolean; video_scenes: boolean };
  files: string[];  // where the files are saved, relative to the project folder
  angle: string;
  captions: Partial<Record<Platform, string>>;
  hashtags: string;
  results: Partial<Record<Platform, PublishResult>>;
  script: Record<string, unknown> | string | null;
  previews: Partial<Record<Platform, string>>;
}

export interface Meta {
  company: { name: string; website: string; tagline: string };
  platforms: Record<Platform, boolean>;
  products: string[];
  counts: Partial<Record<Status | "bin" | "missed", number>>;
  agent: AgentState;
  setup_done: boolean;
  week: { date: string; kind: "video" | "post" | "none"; festivals: string[]; occasions?: { name: string; status: OccStatus; kind: string }[] }[];
  times: { generate: string; publish: string; timezone: string };
  video: { formats: string[]; voiceover: boolean };
  video_worker: VideoWorker;
}

export interface AgentState { paused: boolean; paused_until: string; active_today: boolean }

export interface SceneTexts {
  eyebrow?: string; headline?: string; accent?: string; sub?: string; voice?: string; cta?: string; url?: string;
  greeting?: string; name?: string; quote?: string;
  bullets?: { icon: string; text: string }[]; badges?: { value: string; label: string }[]; screen?: string;
}
export interface Storyboard {
  board: { festive?: SceneTexts; intro?: SceneTexts; scenes: SceneTexts[]; grid?: SceneTexts & { items?: unknown[] }; outro?: SceneTexts; voice_name: string };
  theme: string; product: string;
}

export interface InsightGroup { name: string; posts: number; avg_engagement: number; avg_reach: number }
export interface InsightPost extends Metrics { id: number; kind: string; topic: string; format: string; theme: string; product: string; date: string; weekday: string; per_platform: Record<string, Partial<Metrics>> }
export interface Insights {
  days: number; published: number; measured: number; totals: Metrics & { engagement: number };
  per_platform: Record<string, Metrics>; top: InsightPost[];
  by_format: InsightGroup[]; by_theme: InsightGroup[]; by_product: InsightGroup[]; by_kind: InsightGroup[]; by_source: InsightGroup[]; by_weekday: InsightGroup[];
  summary: { text: string; tips: string; created_at: string; days: number } | null;
}

export interface VideoWorker {
  mode: "server" | "pc";
  online?: boolean;
  name?: string;
  last_seen?: string | null;
  state?: string;
}

export type Kind = "video" | "post" | "none";
export type Weekday = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";
export const WEEKDAYS: Weekday[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

export interface Schedule {
  schedule: Record<Weekday, Kind>;
  generate_time: string;
  publish_time: string;
  timezone: string;
  always_post_on_festivals: boolean;
  festival_lookahead_days: number;
  post_priority: string[];
  next_runs: Record<string, string | null>;
}

export interface CalEvent { id: number; date: string; title: string; details: string; remind_days_before: number; paused?: boolean }
export interface CalDay {
  date: string; in_month: boolean; kind: Kind; festivals: string[]; events: CalEvent[];
  occasions: { name: string; kind: string; status: OccStatus; post_date: string; key: string }[];
  items: { id: number; kind: "video" | "post"; status: Status; topic: string; source_url: string; thumb: string; publish_time: string; movable: boolean }[];
}

export interface Product { name: string; url: string; description: string }
export interface Settings {
  company: { name?: string; tagline?: string; website?: string; industry?: string; audience?: string; tone?: string;
    call_to_action?: string; brand_colors?: { primary?: string; secondary?: string; text?: string } };
  products: Product[];
  video: { formats?: string[]; max_seconds?: number; fps?: number; voiceover?: boolean; voice?: string; background_music?: boolean; themes?: string[] };
  post: { self_review?: boolean; formats?: string[]; themes?: string[] };
  creative: { fallback?: boolean };
  catalog: {
    post_formats: { id: string; label: string; needs: string[] }[];
    post_themes: { id: string; label: string; bg: string; surface: string; ink: string; accent: string; accent2: string }[];
    video_themes: { id: string; bg: string; bg2: string; ink: string; accent: string; accent2: string }[];
    voices: { id: string; label: string }[];
  };
  engine: { llm_provider: string; model: string; design_model: string; image_provider: string; tts_provider: string; anthropic_key: boolean };
}
export type OccStatus = "approved" | "skipped" | "pending" | "paused";
export interface Occasion {
  date: string; name: string; kind: "festival" | "special" | "suggestion" | "event"; status: OccStatus;
  rule: "always" | "never" | "ask"; timing: number; note: string; source: string; key: string;
  reason: string; product: string; post_date: string;
}

export interface MetaConn {
  app_configured: boolean; app_id: string; redirect_uri: string; connected: boolean; source: string; method: string;
  page_id: string; page_name: string; picture: string; ig_user_id: string; ig_username: string; connected_at: number | null;
  pending_choices: { id: string; name: string; picture: string; ig_username: string }[];
}
export interface LinkedInConn {
  app_configured: boolean; app_id: string; redirect_uri: string; connected: boolean; source: string; method: string;
  org_id: string; org_name: string; expires_at: number | null; expires_in_days: number | null; auto_refresh: boolean;
  connected_at: number | null; pending_choices: { id: string; name: string }[];
}
export interface InstagramConn {
  app_configured: boolean; app_id: string; redirect_uri: string; connected: boolean; source: string; method: string;
  ig_user_id: string; username: string; picture: string; account_type: string; expires_in_days: number | null; connected_at: number | null;
  config_id: string; login: string; never_expires: boolean;
  pending_choices: { id: string; username: string; name: string; picture: string }[];
}
export type ConnPlatform = "instagram" | "meta" | "linkedin";
export interface Connections { public_url: string; instagram: InstagramConn; meta: MetaConn; linkedin: LinkedInConn }

export interface Assets { logo: string | null; music: { name: string; size: number; url: string }[] }
export interface HealthCheck { name: string; status: "ok" | "warn" | "fail"; detail: string }

const TOKEN_KEY = "dma_token";
export const auth = {
  get token() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set(token: string) { try { localStorage.setItem(TOKEN_KEY, token); } catch { /* private mode */ } },
  clear() { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Free hosting sleeps when idle: the first request can fail with 502/503/504 while the
// server boots (~1 min). Retry quietly and let the UI show a "waking up" banner.
const WAKE_CODES = new Set([502, 503, 504]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let waking = false;
function setWaking(v: boolean) {
  if (waking !== v) { waking = v; window.dispatchEvent(new CustomEvent("dma:waking", { detail: v })); }
}

async function fetchWithWake(path: string, init: RequestInit): Promise<Response> {
  const safe = !init.method || init.method === "GET";
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(path, init);
      // A JSON body means our own app answered (maybe a real error). An HTML page instead of JSON is the host's
      // "waking up" page (or the Static Site's proxy) – the agent is still starting.
      const fromApp = (res.headers.get("content-type") || "").includes("application/json");
      const hostPage = !fromApp && (WAKE_CODES.has(res.status) || (res.headers.get("content-type") || "").includes("text/html"));
      if (hostPage && attempt < (safe ? 12 : 6)) { setWaking(true); await sleep(5000); continue; }
      setWaking(false);
      return res;
    } catch (e) {
      if (attempt >= 8) { setWaking(false); throw e; }
      setWaking(true);
      await sleep(8000);
    }
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth.token) headers.set("Authorization", `Bearer ${auth.token}`);
  const res = await fetchWithWake(path, { ...init, headers });
  if (res.status === 401 && path !== "/api/login") {
    auth.clear();
    window.dispatchEvent(new Event("dma:logout"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* not json */ }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; user: string }>("/api/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => request<{ user: string }>("/api/me"),
  meta: () => request<Meta>("/api/meta"),
  items: (params: { status?: string; kind?: string; q?: string; limit?: number; bin?: boolean } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<{ total: number; items: Item[] }>(`/api/items?${qs}`);
  },
  item: (id: number) => request<ItemDetail>(`/api/items/${id}`),
  update: (id: number, body: { captions?: ItemDetail["captions"]; hashtags?: string; platforms?: Platform[]; date?: string; publish_time?: string }) =>
    request<ItemDetail>(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  action: (id: number, action: "approve" | "reject" | "regenerate" | "publish" | "stop" | "check") =>
    request<ItemDetail>(`/api/items/${id}/${action}`, { method: "POST" }),
  deleteItem: (id: number) => request<{ ok: boolean }>(`/api/items/${id}`, { method: "DELETE" }),
  deleteForever: (id: number) => request<{ ok: boolean }>(`/api/items/${id}?forever=true`, { method: "DELETE" }),
  restore: (id: number) => request<ItemDetail>(`/api/items/${id}/restore`, { method: "POST" }),
  emptyBin: () => request<{ deleted: number }>("/api/bin/empty", { method: "POST" }),
  bulk: (ids: number[], action: "approve" | "reject" | "delete" | "restore" | "purge") =>
    request<{ done: number[]; skipped: { id: number; reason: string }[] }>("/api/items/bulk", { method: "POST", body: JSON.stringify({ ids, action }) }),
  setAgent: (paused: boolean, paused_until = "") =>
    request<AgentState>("/api/agent", { method: "PUT", body: JSON.stringify({ paused, paused_until }) }),
  design: (id: number) => request<{ html: string }>(`/api/items/${id}/design`),
  saveDesign: (id: number, html: string) =>
    request<{ item: ItemDetail; issues: string[] }>(`/api/items/${id}/design`, { method: "PUT", body: JSON.stringify({ html }) }),
  storyboard: (id: number) => request<Storyboard>(`/api/items/${id}/storyboard`),
  rewritePart: (id: number, part: string, instruction: string) =>
    request<{ part: string; texts: SceneTexts }>(`/api/items/${id}/storyboard/rewrite`, { method: "POST", body: JSON.stringify({ part, instruction }) }),
  saveStoryboard: (id: number, edits: Record<string, unknown>, voice_name: string) =>
    request<ItemDetail>(`/api/items/${id}/storyboard`, { method: "PUT", body: JSON.stringify({ edits, voice_name }) }),
  refreshMetrics: (id: number) => request<ItemDetail>(`/api/items/${id}/metrics`, { method: "POST" }),
  insights: (days = 30) => request<Insights>(`/api/insights?days=${days}`),
  refreshInsights: (days = 30) =>
    request<{ refreshed: number; summary: Insights["summary"]; report: Insights }>(`/api/insights/refresh?days=${days}`, { method: "POST" }),
  setupAnalyze: (website: string) =>
    request<{ company: Settings["company"]; brand_colors: Record<string, string>; products: Product[] }>("/api/setup/analyze", { method: "POST", body: JSON.stringify({ website }) }),
  setupFinish: () => request<{ ok: boolean }>("/api/setup/finish", { method: "POST" }),
  setupRestart: () => request<{ ok: boolean }>("/api/setup/restart", { method: "POST" }),
  deleteRejected: () => request<{ deleted: number }>("/api/items/delete-rejected", { method: "POST" }),
  fromUrl: (url: string, kind: "video" | "post", notes: string) =>
    request<{ id: number }>("/api/from-url", { method: "POST", body: JSON.stringify({ url, kind, notes }) }),
  schedule: () => request<Schedule>("/api/schedule"),
  saveSchedule: (body: Partial<Omit<Schedule, "next_runs" | "timezone">>) =>
    request<Schedule>("/api/schedule", { method: "PUT", body: JSON.stringify(body) }),
  calendar: (month: string) => request<{ month: string; days: CalDay[] }>(`/api/calendar?month=${month}`),
  events: () => request<{ events: CalEvent[]; special_days: { date: string; name: string }[] }>("/api/events"),
  addEvent: (e: Omit<CalEvent, "id">) => request<{ events: CalEvent[] }>("/api/events", { method: "POST", body: JSON.stringify(e) }),
  editEvent: (id: number, e: Omit<CalEvent, "id">) => request<{ events: CalEvent[] }>(`/api/events/${id}`, { method: "PUT", body: JSON.stringify(e) }),
  deleteEvent: (id: number) => request<{ events: CalEvent[] }>(`/api/events/${id}`, { method: "DELETE" }),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (body: Partial<Pick<Settings, "company" | "products" | "video" | "post">>) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  assets: () => request<Assets>("/api/assets"),
  uploadLogo: (file: File) => { const f = new FormData(); f.append("file", file); return request<Assets>("/api/assets/logo", { method: "POST", body: f }); },
  uploadMusic: (file: File) => { const f = new FormData(); f.append("file", file); return request<Assets>("/api/assets/music", { method: "POST", body: f }); },
  deleteMusic: (name: string) => request<Assets>(`/api/assets/music/${encodeURIComponent(name)}`, { method: "DELETE" }),
  voicePreview: (voice: string) => request<{ url: string }>("/api/voice-preview", { method: "POST", body: JSON.stringify({ voice }) }),
  health: (full = false) => request<{ checks: HealthCheck[]; platforms: Record<Platform, boolean>; next_runs: Record<string, string | null> }>(`/api/health?full=${full}`),
  occasions: (days = 60) => request<{ items: Occasion[]; default_timing: number }>(`/api/occasions?days=${days}`),
  pendingOccasions: (days = 7) => request<{ items: Occasion[] }>(`/api/occasions/pending?days=${days}`),
  decide: (key: string, status: "approved" | "skipped" | "clear", opts: { timing?: number; note?: string } = {}) =>
    request<{ ok: boolean }>("/api/occasions/decide", { method: "POST", body: JSON.stringify({ key, status, ...opts }) }),
  setRule: (name: string, rule: "always" | "never" | "ask", opts: { timing?: number; note?: string } = {}) =>
    request<{ ok: boolean }>("/api/occasions/rule", { method: "PUT", body: JSON.stringify({ name, rule, ...opts }) }),
  suggestOccasions: () => request<{ added: number }>("/api/occasions/suggest", { method: "POST" }),
  suggestionStatus: (id: string, status: "accepted" | "dismissed" | "pending") =>
    request<{ ok: boolean }>(`/api/occasions/suggestions/${id}`, { method: "POST", body: JSON.stringify({ status }) }),
  addSpecialDay: (date: string, name: string) => request<{ ok: boolean }>("/api/special-days", { method: "POST", body: JSON.stringify({ date, name }) }),
  removeSpecialDay: (mmdd: string) => request<{ ok: boolean }>(`/api/special-days/${mmdd}`, { method: "DELETE" }),
  pauseEvent: (id: number | string, paused: boolean) =>
    request<{ ok: boolean }>(`/api/events/${id}/pause`, { method: "POST", body: JSON.stringify({ paused }) }),

  connections: () => request<Connections>("/api/connections"),
  setApp: (platform: ConnPlatform, id: string, secret: string, config_id = "") =>
    request<Connections>(`/api/connections/apps/${platform}`, { method: "PUT", body: JSON.stringify({ id, secret, config_id }) }),
  removeApp: (platform: ConnPlatform) => request<Connections>(`/api/connections/apps/${platform}`, { method: "DELETE" }),
  connectStart: (platform: ConnPlatform) => request<{ url: string }>(`/api/connections/${platform}/start`),
  connectSelect: (platform: ConnPlatform, id: string) =>
    request<Connections>(`/api/connections/${platform}/select`, { method: "POST", body: JSON.stringify({ id }) }),
  instagramManual: (access_token: string) =>
    request<Connections>("/api/connections/instagram/manual", { method: "PUT", body: JSON.stringify({ access_token }) }),
  metaManual: (page_id: string, page_token: string, ig_user_id: string) =>
    request<Connections>("/api/connections/meta/manual", { method: "PUT", body: JSON.stringify({ page_id, page_token, ig_user_id }) }),
  linkedinManual: (access_token: string, org_id: string) =>
    request<Connections>("/api/connections/linkedin/manual", { method: "PUT", body: JSON.stringify({ access_token, org_id }) }),
  testConnection: (platform: ConnPlatform) =>
    request<{ ok: boolean; results?: Record<string, string>; error?: string }>(`/api/connections/${platform}/test`, { method: "POST" }),
  disconnect: (platform: ConnPlatform) => request<Connections>(`/api/connections/${platform}`, { method: "DELETE" }),
  generate: (kind?: "video" | "post", notes = "") =>
    request<{ ok: boolean; date: string }>("/api/generate", { method: "POST", body: JSON.stringify({ kind, notes }) }),
};
