// Typed client for the agent's JSON API (app/api.py).

export type Status =
  | "generating" | "pending_approval" | "approved" | "published" | "dry_run"
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
  created_at: string | null;
  published_at: string | null;
}

export interface PublishResult { ok: boolean; dry_run?: boolean; id: string; error: string }

export interface QualityReport {
  passed: boolean | null;
  score: number | null;
  summary: string;
  problems: string[];
  checks: { name: string; status: "ok" | "warn" | "fail"; detail: string }[];
}

export interface ItemDetail extends Item {
  quality_report: QualityReport | Record<string, never>;
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
  counts: Partial<Record<Status, number>>;
  week: { date: string; kind: "video" | "post" | "none"; festivals: string[]; occasions?: { name: string; status: OccStatus; kind: string }[] }[];
  times: { generate: string; publish: string; timezone: string };
  video: { formats: string[]; voiceover: boolean };
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
  items: { id: number; kind: "video" | "post"; status: Status; topic: string; source_url: string; thumb: string }[];
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
export interface Connections { public_url: string; meta: MetaConn; linkedin: LinkedInConn }

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
      // A JSON error body means our own app answered (a real error), not the host waking up.
      const fromApp = (res.headers.get("content-type") || "").includes("application/json");
      if (WAKE_CODES.has(res.status) && !fromApp && attempt < (safe ? 8 : 4)) { setWaking(true); await sleep(8000); continue; }
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
  items: (params: { status?: string; kind?: string; q?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<{ total: number; items: Item[] }>(`/api/items?${qs}`);
  },
  item: (id: number) => request<ItemDetail>(`/api/items/${id}`),
  update: (id: number, body: { captions?: ItemDetail["captions"]; hashtags?: string; platforms?: Platform[] }) =>
    request<ItemDetail>(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  action: (id: number, action: "approve" | "reject" | "regenerate" | "publish" | "stop" | "check") =>
    request<ItemDetail>(`/api/items/${id}/${action}`, { method: "POST" }),
  deleteItem: (id: number) => request<{ ok: boolean }>(`/api/items/${id}`, { method: "DELETE" }),
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
  setApp: (platform: "meta" | "linkedin", id: string, secret: string) =>
    request<Connections>(`/api/connections/apps/${platform}`, { method: "PUT", body: JSON.stringify({ id, secret }) }),
  removeApp: (platform: "meta" | "linkedin") => request<Connections>(`/api/connections/apps/${platform}`, { method: "DELETE" }),
  connectStart: (platform: "meta" | "linkedin") => request<{ url: string }>(`/api/connections/${platform}/start`),
  connectSelect: (platform: "meta" | "linkedin", id: string) =>
    request<Connections>(`/api/connections/${platform}/select`, { method: "POST", body: JSON.stringify({ id }) }),
  metaManual: (page_id: string, page_token: string, ig_user_id: string) =>
    request<Connections>("/api/connections/meta/manual", { method: "PUT", body: JSON.stringify({ page_id, page_token, ig_user_id }) }),
  linkedinManual: (access_token: string, org_id: string) =>
    request<Connections>("/api/connections/linkedin/manual", { method: "PUT", body: JSON.stringify({ access_token, org_id }) }),
  testConnection: (platform: "meta" | "linkedin") =>
    request<{ ok: boolean; results?: Record<string, string>; error?: string }>(`/api/connections/${platform}/test`, { method: "POST" }),
  disconnect: (platform: "meta" | "linkedin") => request<Connections>(`/api/connections/${platform}`, { method: "DELETE" }),
  generate: (kind?: "video" | "post") =>
    request<{ ok: boolean; date: string }>("/api/generate", { method: "POST", body: JSON.stringify({ kind }) }),
};
