import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle, ArrowDown, ArrowUp, Building2, CheckCircle2, Cpu, ExternalLink, Link2, Loader2, Music, Package, Palette, Play,
  Plus, RefreshCw, Trash2, Upload, Volume2, XCircle,
} from "lucide-react";
import { api, type HealthCheck, type Product, type Settings as TSettings } from "../lib/api";
import { PLATFORMS, pretty } from "../lib/ui";
import { Button, Card, Field, SaveBar, Switch, inputCls, useToast } from "../components/ui";
import ConnectionsTab from "../components/Connections";

const TABS = [
  { id: "connections", label: "Connections", icon: Link2 },
  { id: "company", label: "Company & brand", icon: Building2 },
  { id: "products", label: "Products", icon: Package },
  { id: "style", label: "Content style", icon: Palette },
  { id: "status", label: "Status & health", icon: Cpu },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function Settings() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabId) || "connections";
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  return (
    <div className="mx-auto max-w-6xl px-5 py-8 md:px-10">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Settings</h1>
      <p className="mt-1 text-sm text-stone-500">Everything the agent needs to know about your brand, products and style. Saved to <code className="rounded bg-stone-100 px-1">config/settings.yaml</code>.</p>

      <div className="mt-6 flex flex-wrap gap-1 rounded-xl bg-white p-1 ring-1 ring-stone-200/80 sm:inline-flex">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setParams({ tab: id })}
            className={clsx("flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition",
              tab === id ? "bg-ink-900 text-white" : "text-stone-600 hover:bg-stone-100")}>
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {!data ? <div className="shimmer h-96 rounded-2xl bg-stone-200/60" /> :
          tab === "connections" ? <ConnectionsTab /> :
          tab === "company" ? <CompanyTab s={data} /> :
          tab === "products" ? <ProductsTab s={data} /> :
          tab === "style" ? <StyleTab s={data} /> : <StatusTab s={data} />}
      </div>
    </div>
  );
}

function useSaveSettings(msg: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: api.saveSettings,
    onSuccess: (d) => { qc.setQueryData(["settings"], d); qc.invalidateQueries({ queryKey: ["meta"] }); toast("ok", msg); },
    onError: (e: Error) => toast("error", e.message),
  });
}

// ── Company ────────────────────────────────────────────────────────────────
function CompanyTab({ s }: { s: TSettings }) {
  const [c, setC] = useState(s.company);
  useEffect(() => setC(s.company), [s.company]);
  const dirty = JSON.stringify(c) !== JSON.stringify(s.company);
  const save = useSaveSettings("Brand saved – new content uses it right away");
  const set = (k: keyof TSettings["company"], v: unknown) => setC((x) => ({ ...x, [k]: v }));
  const colors = c.brand_colors ?? {};

  return (
    <>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card className="space-y-5 p-6">
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Company name"><input value={c.name ?? ""} onChange={(e) => set("name", e.target.value)} className={inputCls} /></Field>
            <Field label="Tagline"><input value={c.tagline ?? ""} onChange={(e) => set("tagline", e.target.value)} className={inputCls} /></Field>
          </div>
          <Field label="Website" hint="The agent reads it for facts and captures your logo from it.">
            <input value={c.website ?? ""} onChange={(e) => set("website", e.target.value)} className={inputCls} placeholder="https://" />
          </Field>
          <Field label="What you do"><input value={c.industry ?? ""} onChange={(e) => set("industry", e.target.value)} className={inputCls} /></Field>
          <Field label="Who you sell to" hint="The AI writes for these people.">
            <textarea rows={2} value={c.audience ?? ""} onChange={(e) => set("audience", e.target.value)} className={clsx(inputCls, "resize-none")} />
          </Field>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Tone of voice"><input value={c.tone ?? ""} onChange={(e) => set("tone", e.target.value)} className={inputCls} /></Field>
            <Field label="Call to action"><input value={c.call_to_action ?? ""} onChange={(e) => set("call_to_action", e.target.value)} className={inputCls} /></Field>
          </div>
        </Card>

        <div className="space-y-6">
          <LogoCard />
          <Card className="p-6">
            <h2 className="font-bold">Brand colours</h2>
            <p className="mt-1 text-xs text-stone-500">Used by the simple fallback designs. The premium designs follow the post/video looks.</p>
            <div className="mt-4 grid grid-cols-2 gap-4">
              {(["primary", "secondary"] as const).map((k) => (
                <label key={k} className="flex items-center gap-3 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200">
                  <input type="color" value={colors[k] ?? "#000000"} onChange={(e) => set("brand_colors", { ...colors, [k]: e.target.value })}
                    className="size-10 cursor-pointer rounded-lg border-0 bg-transparent p-0" />
                  <span><span className="block text-sm font-semibold capitalize">{k}</span><span className="font-mono text-xs text-stone-500">{colors[k]}</span></span>
                </label>
              ))}
            </div>
          </Card>
        </div>
      </div>
      <SaveBar dirty={dirty} saving={save.isPending} onSave={() => save.mutate({ company: c })} onDiscard={() => setC(s.company)} />
    </>
  );
}

function LogoCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const ref = useRef<HTMLInputElement>(null);
  const { data } = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const up = useMutation({
    mutationFn: api.uploadLogo,
    onSuccess: (d) => { qc.setQueryData(["assets"], d); toast("ok", "Logo updated – light and dark versions are made automatically"); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <h2 className="font-bold">Logo</h2>
        <Button icon={<Upload className="size-4" />} loading={up.isPending} onClick={() => ref.current?.click()}>Upload PNG</Button>
        <input ref={ref} type="file" accept="image/png,image/webp" hidden onChange={(e) => e.target.files?.[0] && up.mutate(e.target.files[0])} />
      </div>
      {data?.logo ? (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="grid h-24 place-items-center rounded-xl bg-[#ECE4D8] p-4"><img src={data.logo} alt="" className="max-h-full max-w-full" /></div>
          <div className="grid h-24 place-items-center rounded-xl bg-ink-900 p-4"><img src={data.logo} alt="" className="max-h-full max-w-full brightness-0 invert" /></div>
        </div>
      ) : (
        <p className="mt-3 rounded-xl border border-dashed border-stone-300 px-4 py-6 text-center text-sm text-stone-500">
          No logo yet. The agent captures it from your website on the first run – upload a transparent PNG for the best result.
        </p>
      )}
    </Card>
  );
}

// ── Products ───────────────────────────────────────────────────────────────
function ProductsTab({ s }: { s: TSettings }) {
  const [list, setList] = useState<Product[]>(s.products);
  useEffect(() => setList(s.products), [s.products]);
  const dirty = JSON.stringify(list) !== JSON.stringify(s.products);
  const save = useSaveSettings("Products saved");
  const valid = list.every((p) => p.name.trim().length >= 2) && new Set(list.map((p) => p.name.trim())).size === list.length;
  const upd = (i: number, k: keyof Product, v: string) => setList((l) => l.map((p, j) => (j === i ? { ...p, [k]: v } : p)));
  const move = (i: number, d: -1 | 1) => setList((l) => { const a = [...l]; [a[i], a[i + d]] = [a[i + d], a[i]]; return a; });

  return (
    <>
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-bold">Products & services</h2>
            <p className="mt-1 text-xs text-stone-500">The agent features them in turn (least recently used first). Videos capture the screens from each product's page.</p>
          </div>
          <Button variant="dark" icon={<Plus className="size-4" />} onClick={() => setList((l) => [...l, { name: "", url: "", description: "" }])}>Add product</Button>
        </div>
        <ul className="mt-5 space-y-3">
          {list.map((p, i) => (
            <li key={i} className="rounded-xl bg-stone-50 p-4 ring-1 ring-stone-200/70">
              <div className="flex gap-3">
                <span className="mt-2 grid size-7 shrink-0 place-items-center rounded-lg bg-ink-900 text-xs font-bold text-white">{i + 1}</span>
                <div className="grid min-w-0 flex-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
                  <input value={p.name} onChange={(e) => upd(i, "name", e.target.value)} placeholder="Product name" className={clsx(inputCls, "bg-white font-semibold")} />
                  <div className="flex items-center gap-2">
                    <input value={p.url} onChange={(e) => upd(i, "url", e.target.value)} placeholder="https://… product page" className={clsx(inputCls, "bg-white")} />
                    {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="rounded-lg p-2 text-stone-400 hover:bg-white hover:text-stone-800"><ExternalLink className="size-4" /></a>}
                  </div>
                  <textarea rows={2} value={p.description} onChange={(e) => upd(i, "description", e.target.value)}
                    placeholder="What it does – the AI uses this to explain it correctly" className={clsx(inputCls, "resize-none bg-white md:col-span-2")} />
                </div>
                <div className="flex flex-col gap-1">
                  <button disabled={i === 0} onClick={() => move(i, -1)} className="rounded p-1.5 text-stone-400 hover:bg-white hover:text-stone-800 disabled:opacity-30"><ArrowUp className="size-4" /></button>
                  <button disabled={i === list.length - 1} onClick={() => move(i, 1)} className="rounded p-1.5 text-stone-400 hover:bg-white hover:text-stone-800 disabled:opacity-30"><ArrowDown className="size-4" /></button>
                  <button onClick={() => setList((l) => l.filter((_, j) => j !== i))} className="rounded p-1.5 text-stone-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-4" /></button>
                </div>
              </div>
            </li>
          ))}
        </ul>
        {!valid && <p className="mt-3 text-sm text-red-600">Every product needs a unique name.</p>}
      </Card>
      <SaveBar dirty={dirty} saving={save.isPending} onSave={() => valid && save.mutate({ products: list.map((p) => ({ ...p, name: p.name.trim() })) })}
        onDiscard={() => setList(s.products)} />
    </>
  );
}

// ── Content style ──────────────────────────────────────────────────────────
function StyleTab({ s }: { s: TSettings }) {
  const [video, setVideo] = useState(s.video);
  const [post, setPost] = useState(s.post);
  useEffect(() => { setVideo(s.video); setPost(s.post); }, [s.video, s.post]);
  const dirty = JSON.stringify(video) !== JSON.stringify(s.video) || JSON.stringify(post) !== JSON.stringify(s.post);
  const save = useSaveSettings("Content style saved");
  const vFormats = video.formats ?? ["landscape", "vertical"];
  const vThemes = video.themes ?? s.catalog.video_themes.map((t) => t.id);
  const pFormats = post.formats ?? s.catalog.post_formats.map((f) => f.id);
  const pThemes = post.themes ?? s.catalog.post_themes.map((t) => t.id);
  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const problems = [
    vFormats.length === 0 && "Pick at least one video size.",
    vThemes.length === 0 && "Pick at least one video look.",
    pFormats.length < 3 && "Keep at least 3 post formats so posts don't repeat.",
    pThemes.length < 2 && "Keep at least 2 post looks.",
  ].filter(Boolean) as string[];

  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-6 p-6">
          <h2 className="font-bold">Videos</h2>
          <div>
            <div className="text-sm font-semibold">Sizes</div>
            <div className="mt-2 grid grid-cols-2 gap-3">
              {([["landscape", "16:9 wide", "LinkedIn, YouTube"], ["vertical", "9:16 tall", "Instagram & Facebook Reels"]] as const).map(([id, t, sub]) => {
                const on = vFormats.includes(id);
                return (
                  <button key={id} onClick={() => setVideo({ ...video, formats: toggle(vFormats, id) })}
                    className={clsx("flex items-center gap-3 rounded-xl p-3 text-left ring-1 transition", on ? "bg-ink-900 text-white ring-ink-900" : "bg-white ring-stone-200 hover:ring-stone-300")}>
                    <span className={clsx("shrink-0 rounded border-2", on ? "border-white" : "border-stone-400", id === "landscape" ? "h-5 w-8" : "h-8 w-5")} />
                    <span><span className="block text-sm font-semibold">{t}</span><span className={clsx("block text-xs", on ? "text-white/60" : "text-stone-500")}>{sub}</span></span>
                  </button>
                );
              })}
            </div>
          </div>
          <Field label={`Maximum length: ${video.max_seconds ?? 75} seconds`} hint="Each version takes about 3 seconds to render per second of video.">
            <input type="range" min={30} max={120} step={5} value={video.max_seconds ?? 75}
              onChange={(e) => setVideo({ ...video, max_seconds: Number(e.target.value) })} className="w-full accent-brand-600" />
          </Field>
          <Switch checked={video.voiceover ?? true} onChange={(v) => setVideo({ ...video, voiceover: v })}
            label="AI voice-over" sub="A voice explains each scene. Turn off for music-only videos." />
          {(video.voiceover ?? true) && <VoicePicker voices={s.catalog.voices} value={video.voice ?? "en-IN-PrabhatNeural"} onChange={(v) => setVideo({ ...video, voice: v })} />}
          <Switch checked={video.background_music ?? true} onChange={(v) => setVideo({ ...video, background_music: v })}
            label="Background music" sub="A random track from your library, softly under the voice." />
          {(video.background_music ?? true) && <MusicLibrary />}
          <div>
            <div className="text-sm font-semibold">Looks <span className="font-normal text-stone-400">· rotated, never twice in a row</span></div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {s.catalog.video_themes.map((t) => {
                const on = vThemes.includes(t.id);
                return (
                  <button key={t.id} onClick={() => setVideo({ ...video, themes: toggle(vThemes, t.id) })}
                    className={clsx("overflow-hidden rounded-xl text-left ring-2 transition", on ? "ring-ink-900" : "opacity-50 ring-transparent hover:opacity-80")}>
                    <div className="h-14 p-2.5" style={{ background: `radial-gradient(circle at 15% 20%, ${t.bg2}, ${t.bg})` }}>
                      <div className="h-1.5 w-10 rounded-full" style={{ background: t.ink, opacity: .85 }} />
                      <div className="mt-1 h-1.5 w-7 rounded-full" style={{ background: `linear-gradient(90deg, ${t.accent}, ${t.accent2})` }} />
                    </div>
                    <div className="flex items-center justify-between bg-white px-2.5 py-1.5 text-xs font-semibold">{pretty(t.id)}{on && <CheckCircle2 className="size-3.5 text-emerald-600" />}</div>
                  </button>
                );
              })}
            </div>
          </div>
        </Card>

        <Card className="space-y-6 p-6">
          <h2 className="font-bold">Posts</h2>
          <Switch checked={post.self_review ?? true} onChange={(v) => setPost({ ...post, self_review: v })}
            label="AI art-director review" sub="The AI looks at every rendered post and fixes problems before you see it (1–2 extra AI calls)." />
          <div>
            <div className="text-sm font-semibold">Formats <span className="font-normal text-stone-400">· {pFormats.length} of {s.catalog.post_formats.length} on · same format never within 4 posts</span></div>
            <div className="mt-2 grid gap-1.5">
              {s.catalog.post_formats.map((f) => {
                const on = pFormats.includes(f.id);
                return (
                  <button key={f.id} onClick={() => setPost({ ...post, formats: toggle(pFormats, f.id) })}
                    className={clsx("flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ring-1 transition",
                      on ? "bg-white ring-stone-300" : "bg-stone-50 text-stone-400 ring-stone-200/60")}>
                    <span className={clsx("grid size-4 shrink-0 place-items-center rounded border", on ? "border-emerald-600 bg-emerald-600 text-white" : "border-stone-300")}>
                      {on && <svg viewBox="0 0 12 12" className="size-3"><path d="M2.5 6.5l2.3 2.3L9.5 3.8" fill="none" stroke="currentColor" strokeWidth="2" /></svg>}
                    </span>
                    <span className="min-w-0 flex-1"><span className="font-semibold">{pretty(f.id)}</span> <span className="text-stone-400">– {f.label}</span></span>
                    {f.needs.includes("festival") && <span className="text-[10px] font-bold uppercase text-amber-600">festivals</span>}
                    {f.needs.includes("photo") && <span className="text-[10px] font-bold uppercase text-violet-600">AI photo</span>}
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <div className="text-sm font-semibold">Looks <span className="font-normal text-stone-400">· never twice in a row</span></div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {s.catalog.post_themes.map((t) => {
                const on = pThemes.includes(t.id);
                return (
                  <button key={t.id} title={t.label} onClick={() => setPost({ ...post, themes: toggle(pThemes, t.id) })}
                    className={clsx("overflow-hidden rounded-xl text-left ring-2 transition", on ? "ring-ink-900" : "opacity-50 ring-transparent hover:opacity-80")}>
                    <div className="relative aspect-[4/5] p-2" style={{ background: t.bg }}>
                      <div className="h-2 w-3/4 rounded-sm" style={{ background: t.ink }} />
                      <div className="mt-1 h-2 w-1/2 rounded-sm" style={{ background: t.accent }} />
                      <div className="absolute inset-x-2 bottom-2 h-1/3 rounded-md shadow" style={{ background: t.surface }} />
                    </div>
                    <div className="truncate bg-white px-2 py-1.5 text-[11px] font-semibold">{pretty(t.id)}</div>
                  </button>
                );
              })}
            </div>
          </div>
        </Card>
      </div>
      {problems.length > 0 && <p className="mt-4 text-sm text-red-600">{problems.join(" ")}</p>}
      <SaveBar dirty={dirty} saving={save.isPending} onSave={() => problems.length === 0 && save.mutate({ video, post })}
        onDiscard={() => { setVideo(s.video); setPost(s.post); }} />
    </>
  );
}

function VoicePicker({ voices, value, onChange }: { voices: { id: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  const toast = useToast();
  const audio = useRef<HTMLAudioElement | null>(null);
  const preview = useMutation({
    mutationFn: () => api.voicePreview(value),
    onSuccess: ({ url }) => { audio.current?.pause(); audio.current = new Audio(url); audio.current.play().catch(() => {}); },
    onError: (e: Error) => toast("error", `Voice preview failed: ${e.message}`),
  });
  return (
    <div className="flex items-end gap-2 pl-0 sm:pl-4">
      <Field label="Voice" className="flex-1">
        <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
          {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
      </Field>
      <Button icon={<Volume2 className="size-4" />} loading={preview.isPending} onClick={() => preview.mutate()}>Listen</Button>
    </div>
  );
}

function MusicLibrary() {
  const qc = useQueryClient();
  const toast = useToast();
  const ref = useRef<HTMLInputElement>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const { data } = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const onDone = (d: Awaited<ReturnType<typeof api.assets>>) => qc.setQueryData(["assets"], d);
  const up = useMutation({ mutationFn: api.uploadMusic, onSuccess: (d) => { onDone(d); toast("ok", "Track added"); }, onError: (e: Error) => toast("error", e.message) });
  const del = useMutation({ mutationFn: api.deleteMusic, onSuccess: onDone, onError: (e: Error) => toast("error", e.message) });
  const play = (url: string, name: string) => {
    audio.current?.pause();
    if (playing === name) { setPlaying(null); return; }
    audio.current = new Audio(url); audio.current.play().catch(() => {}); setPlaying(name);
    audio.current.onended = () => setPlaying(null);
  };
  useEffect(() => () => audio.current?.pause(), []);
  return (
    <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70 sm:ml-4">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-semibold"><Music className="size-4 text-stone-400" /> Music library</span>
        <Button icon={<Upload className="size-4" />} loading={up.isPending} onClick={() => ref.current?.click()}>Add MP3</Button>
        <input ref={ref} type="file" accept=".mp3,audio/mpeg" hidden multiple
          onChange={(e) => { Array.from(e.target.files ?? []).forEach((f) => up.mutate(f)); e.target.value = ""; }} />
      </div>
      {!data?.music.length ? (
        <p className="mt-2 text-xs text-stone-500">No tracks yet – videos will have voice only. Use royalty-free music (e.g. YouTube Audio Library).</p>
      ) : (
        <ul className="mt-2 divide-y divide-stone-200/70">
          {data.music.map((m) => (
            <li key={m.name} className="flex items-center gap-2 py-1.5 text-sm">
              <button onClick={() => play(m.url, m.name)} className="rounded-md p-1 text-stone-500 hover:bg-white hover:text-stone-900">
                {playing === m.name ? <span className="block size-4 text-center leading-4">■</span> : <Play className="size-4" />}
              </button>
              <span className="min-w-0 flex-1 truncate">{m.name}</span>
              <span className="text-xs text-stone-400">{(m.size / 1e6).toFixed(1)} MB</span>
              <button onClick={() => del.mutate(m.name)} className="rounded-md p-1 text-stone-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-4" /></button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Status ─────────────────────────────────────────────────────────────────
function StatusTab({ s }: { s: TSettings }) {
  const [full, setFull] = useState(false);
  const health = useQuery({ queryKey: ["health", full], queryFn: () => api.health(full), staleTime: 60000 });
  const counts = useMemo(() => {
    const c = { ok: 0, warn: 0, fail: 0 };
    health.data?.checks.forEach((x) => c[x.status]++);
    return c;
  }, [health.data]);
  const e = s.engine;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-bold">Health check</h2>
            <p className="mt-1 text-xs text-stone-500">Same as <code className="rounded bg-stone-100 px-1">check_agent.bat</code>. The full check also makes a tiny AI call and a voice sample.</p>
          </div>
          <div className="flex gap-2">
            <Button icon={<RefreshCw className="size-4" />} loading={health.isFetching && !full} onClick={() => { setFull(false); health.refetch(); }}>Quick check</Button>
            <Button variant="dark" loading={health.isFetching && full} onClick={() => setFull(true)}>Full check</Button>
          </div>
        </div>
        {health.isLoading ? (
          <div className="mt-6 flex items-center gap-2 text-sm text-stone-500"><Loader2 className="size-4 animate-spin" /> Checking…</div>
        ) : health.error ? (
          <p className="mt-6 text-sm text-red-600">{(health.error as Error).message}</p>
        ) : (
          <>
            <div className="mt-5 flex gap-2 text-xs font-semibold">
              <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">{counts.ok} OK</span>
              {counts.warn > 0 && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-700">{counts.warn} optional</span>}
              {counts.fail > 0 && <span className="rounded-full bg-red-50 px-2.5 py-1 text-red-700">{counts.fail} to fix</span>}
            </div>
            <ul className="mt-4 divide-y divide-stone-100">
              {health.data?.checks.map((c) => <CheckRow key={c.name} c={c} />)}
            </ul>
          </>
        )}
      </Card>

      <div className="space-y-6">
        <Card className="p-6">
          <h2 className="font-bold">Publishing</h2>
          <ul className="mt-4 space-y-3">
            {PLATFORMS.map((p) => {
              const live = health.data?.platforms[p.id];
              return (
                <li key={p.id} className="flex items-center gap-3">
                  <span className="size-2.5 rounded-full" style={{ background: p.color }} />
                  <span className="flex-1 text-sm font-semibold">{p.label}</span>
                  <span className={clsx("rounded-full px-2.5 py-0.5 text-xs font-semibold", live ? "bg-emerald-50 text-emerald-700" : "bg-stone-100 text-stone-500")}>
                    {live ? "Connected" : "Test mode"}
                  </span>
                </li>
              );
            })}
          </ul>
          <a href="/settings?tab=connections" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline"><Link2 className="size-4" /> Manage connections</a>
        </Card>

        <Card className="p-6">
          <h2 className="font-bold">AI engine</h2>
          <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-sm">
            <dt className="text-stone-500">Provider</dt><dd className="font-medium capitalize">{e.llm_provider} {e.anthropic_key ? "" : <span className="text-red-600">(no key)</span>}</dd>
            <dt className="text-stone-500">Writing</dt><dd className="font-mono text-xs leading-5">{e.model}</dd>
            <dt className="text-stone-500">Design</dt><dd className="font-mono text-xs leading-5">{e.design_model}</dd>
            <dt className="text-stone-500">AI photos</dt><dd className="font-medium">{e.image_provider === "none" ? "Off (drawn with CSS/SVG)" : pretty(e.image_provider)}</dd>
            <dt className="text-stone-500">Voice</dt><dd className="font-medium">{e.tts_provider === "edge" ? "Edge neural voices (free)" : pretty(e.tts_provider)}</dd>
          </dl>
          <p className="mt-4 text-xs text-stone-500">Change these in <code className="rounded bg-stone-100 px-1">.env</code> – keys never leave your PC.</p>
        </Card>

        {health.data?.next_runs && Object.keys(health.data.next_runs).length > 0 && (
          <Card className="p-6">
            <h2 className="font-bold">Scheduler</h2>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              {Object.entries(health.data.next_runs).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-stone-500">{k === "generate" ? "Next preparation" : k === "publish" ? "Next publish check" : k}</dt>
                  <dd className="font-medium">{v ? new Date(v).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</dd>
                </div>
              ))}
            </dl>
          </Card>
        )}
      </div>
    </div>
  );
}

function CheckRow({ c }: { c: HealthCheck }) {
  const Icon = c.status === "ok" ? CheckCircle2 : c.status === "warn" ? AlertTriangle : XCircle;
  return (
    <li className="flex gap-3 py-2.5">
      <Icon className={clsx("mt-0.5 size-4 shrink-0", c.status === "ok" ? "text-emerald-600" : c.status === "warn" ? "text-amber-500" : "text-red-600")} />
      <div className="min-w-0">
        <div className="text-sm font-semibold">{c.name}</div>
        {c.detail && <div className="break-words text-xs text-stone-500">{c.detail}</div>}
      </div>
    </li>
  );
}
