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
  created_at: string | null;
  published_at: string | null;
}

export interface PublishResult { ok: boolean; dry_run?: boolean; id: string; error: string }

export interface ItemDetail extends Item {
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
  week: { date: string; kind: "video" | "post" | "none"; festivals: string[] }[];
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

export interface CalEvent { id: number; date: string; title: string; details: string; remind_days_before: number }
export interface CalDay {
  date: string; in_month: boolean; kind: Kind; festivals: string[]; events: CalEvent[];
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
      if (WAKE_CODES.has(res.status) && attempt < (safe ? 8 : 4)) { setWaking(true); await sleep(8000); continue; }
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
  action: (id: number, action: "approve" | "reject" | "regenerate" | "publish") =>
    request<ItemDetail>(`/api/items/${id}/${action}`, { method: "POST" }),
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
  generate: (kind?: "video" | "post") =>
    request<{ ok: boolean; date: string }>("/api/generate", { method: "POST", body: JSON.stringify({ kind }) }),
};
