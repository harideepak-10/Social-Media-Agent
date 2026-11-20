import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Bookmark, CalendarClock, Eye, Heart, Loader2, MessageCircle, MousePointerClick, Pencil, Play, RefreshCw, Repeat2,
  Send, Share2, Sparkles, ThumbsUp, Type, Video, Volume2, Wand2,
} from "lucide-react";
import { api, type ItemDetail, type Platform, type SceneTexts, type Storyboard } from "../lib/api";
import { PLATFORMS, ago, finalCaption, fmtDate } from "../lib/ui";
import { Button, Card, Field, Modal, inputCls, useToast } from "./ui";

const useRefreshItem = (id: number) => {
  const qc = useQueryClient();
  return (d?: ItemDetail) => {
    if (d) qc.setQueryData(["item", id], d);
    qc.invalidateQueries({ queryKey: ["item", id] });
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["meta"] });
    qc.invalidateQueries({ queryKey: ["calendar"] });
  };
};

// ── when it goes out ───────────────────────────────────────────────────────
export function ScheduleCard({ item, defaultTime }: { item: ItemDetail; defaultTime?: string }) {
  const toast = useToast();
  const refresh = useRefreshItem(item.id);
  const [day, setDay] = useState(item.date);
  const [time, setTime] = useState(item.publish_time);
  useEffect(() => { setDay(item.date); setTime(item.publish_time); }, [item.date, item.publish_time]);
  const dirty = day !== item.date || time !== item.publish_time;
  const today = new Date().toISOString().slice(0, 10);
  const save = useMutation({
    mutationFn: () => api.update(item.id, { date: day, publish_time: time }),
    onSuccess: (d) => { refresh(d); toast("ok", `Goes out ${fmtDate(d.date, { weekday: "short", day: "numeric", month: "short" })} at ${d.publish_time || defaultTime}`); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <Card className={clsx("p-5", item.missed && "ring-2 ring-red-300")}>
      <h2 className="flex items-center gap-2 font-bold"><CalendarClock className="size-4 text-stone-400" /> When it goes out</h2>
      {item.missed && <p className="mt-1 text-sm font-medium text-red-600">Its day has passed and it wasn't posted. Pick a new date.</p>}
      <div className="mt-3 grid grid-cols-2 gap-3">
        <Field label="Day">
          <input type="date" value={day} min={today} onChange={(e) => setDay(e.target.value)} className={inputCls} />
        </Field>
        <Field label="Time">
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={inputCls} />
        </Field>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-stone-500">
          {time ? <>Own time. <button onClick={() => setTime("")} className="font-semibold underline">Use the default ({defaultTime})</button></> : <>Uses the default posting time ({defaultTime}).</>}
          {item.status !== "approved" && " Only approved items go out."}
        </p>
        <Button variant="primary" className="px-3 py-1.5 text-xs" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Card>
  );
}

// ── how it will look on each platform ──────────────────────────────────────
const CUT = { instagram: { lines: 2, chars: 125, more: "more" }, linkedin: { lines: 3, chars: 210, more: "see more" }, facebook: { lines: 5, chars: 400, more: "See more" } };

function cut(text: string, p: Platform): { shown: string; truncated: boolean } {
  const { lines, chars } = CUT[p];
  const ls = text.split("\n");
  let out = "";
  for (let i = 0; i < ls.length; i++) {
    const next = (i ? "\n" : "") + ls[i];
    if (i >= lines || out.length + next.length > chars) {
      if (i < lines && out.length < chars) {  // cut inside this line at a word boundary
        const room = chars - out.length;
        const part = next.slice(0, room).replace(/\s+\S*$/, "");
        out += part;
      }
      return { shown: out.trimEnd(), truncated: true };
    }
    out += next;
  }
  return { shown: out, truncated: false };
}

export function PlatformPreview({ item, captions, tags }: { item: ItemDetail; captions: ItemDetail["captions"]; tags: string[] }) {
  const [p, setP] = useState<Platform>(item.platforms[0] ?? "instagram");
  const [expanded, setExpanded] = useState(false);
  useEffect(() => setExpanded(false), [p]);
  const { data: assets } = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const name = meta?.company.name ?? "Your company";
  const text = finalCaption(captions[p] ?? "", tags.join(" "), p);
  const { shown, truncated } = cut(text, p);
  const vertical = item.kind === "video" && p !== "linkedin" && item.media_vertical;
  const src = vertical ? item.media_vertical : item.media;

  const avatar = (
    <span className="grid size-9 shrink-0 place-items-center overflow-hidden rounded-full bg-stone-100 ring-1 ring-stone-200">
      {assets?.logo ? <img src={assets.logo} alt="" className="size-full object-contain p-1" /> : <span className="text-sm font-bold">{name[0]}</span>}
    </span>
  );
  const media = !src ? null : item.kind === "video" ? (
    <div className={clsx("relative bg-black", vertical ? "mx-auto aspect-[9/16] max-h-[28rem]" : "aspect-video")}>
      <video src={src} poster={vertical ? undefined : item.thumb} muted playsInline preload="metadata" controls className="size-full object-contain" />
    </div>
  ) : <img src={src} alt="" className="w-full" />;
  const caption = (
    <p className="whitespace-pre-wrap break-words text-[13.5px] leading-snug text-stone-900">
      {p === "instagram" && <b className="mr-1">{name.toLowerCase().replace(/\s+/g, "")}</b>}
      {expanded ? text : shown}
      {truncated && !expanded && <>… <button onClick={() => setExpanded(true)} className="font-medium text-stone-500 hover:underline">{CUT[p].more}</button></>}
      {!text && <span className="text-stone-400">No caption</span>}
    </p>
  );

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-stone-100 px-5 py-3">
        <h2 className="font-bold">How it will look</h2>
        <div className="flex gap-1">
          {PLATFORMS.filter((x) => item.platforms.includes(x.id)).map((x) => (
            <button key={x.id} onClick={() => setP(x.id)}
              className={clsx("rounded-lg px-2.5 py-1 text-xs font-semibold", p === x.id ? "bg-ink-900 text-white" : "text-stone-500 hover:bg-stone-100")}>{x.label}</button>
          ))}
        </div>
      </div>
      <div className="bg-stone-100 p-3 sm:p-5">
        <div className="mx-auto max-w-[26rem] overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-stone-200">
          {p === "instagram" && (
            <>
              <div className="flex items-center gap-2.5 px-3 py-2.5">{avatar}<b className="text-[13px]">{name.toLowerCase().replace(/\s+/g, "")}</b></div>
              {media}
              <div className="flex items-center gap-4 px-3 pt-2.5 text-stone-900">
                <Heart className="size-6" /><MessageCircle className="size-6" /><Send className="size-6" /><Bookmark className="ml-auto size-6" />
              </div>
              <div className="px-3 pb-3 pt-2">{caption}</div>
            </>
          )}
          {p === "linkedin" && (
            <>
              <div className="flex items-start gap-2.5 px-4 pt-3">
                {avatar}
                <div className="leading-tight"><b className="text-[13.5px]">{name}</b><div className="text-xs text-stone-500">Company page · now</div></div>
              </div>
              <div className="px-4 pb-3 pt-2.5">{caption}</div>
              {media}
              <div className="flex justify-around border-t border-stone-100 px-2 py-1.5 text-xs font-semibold text-stone-500">
                <span className="flex items-center gap-1.5"><ThumbsUp className="size-4" />Like</span><span className="flex items-center gap-1.5"><MessageCircle className="size-4" />Comment</span>
                <span className="flex items-center gap-1.5"><Repeat2 className="size-4" />Repost</span><span className="flex items-center gap-1.5"><Send className="size-4" />Send</span>
              </div>
            </>
          )}
          {p === "facebook" && (
            <>
              <div className="flex items-start gap-2.5 px-4 pt-3">
                {avatar}
                <div className="leading-tight"><b className="text-[13.5px]">{name}</b><div className="text-xs text-stone-500">Just now · 🌐</div></div>
              </div>
              <div className="px-4 pb-3 pt-2.5">{caption}</div>
              {media}
              <div className="flex justify-around border-t border-stone-100 px-2 py-1.5 text-xs font-semibold text-stone-500">
                <span className="flex items-center gap-1.5"><ThumbsUp className="size-4" />Like</span><span className="flex items-center gap-1.5"><MessageCircle className="size-4" />Comment</span>
                <span className="flex items-center gap-1.5"><Share2 className="size-4" />Share</span>
              </div>
            </>
          )}
        </div>
        <p className="mt-2 text-center text-[11px] text-stone-500">
          {truncated ? `People see the first ${CUT[p].lines} lines – put the hook there.` : "The whole caption is visible without tapping."}
        </p>
      </div>
    </Card>
  );
}

// ── edit buttons under the preview ─────────────────────────────────────────
export function EditBar({ item }: { item: ItemDetail }) {
  const [poster, setPoster] = useState(false);
  const [scenes, setScenes] = useState(false);
  const canEdit = !["published", "dry_run", "generating", "queued"].includes(item.status) && !item.deleted_at;
  if (!canEdit || (!item.editable.poster_text && !item.editable.video_scenes)) return null;
  return (
    <Card className="flex flex-wrap items-center gap-3 p-4">
      <div className="min-w-0 flex-1 text-sm">
        <div className="font-semibold">{item.kind === "post" ? "Change a word without regenerating" : "Change scenes or the voice"}</div>
        <div className="text-xs text-stone-500">{item.kind === "post" ? "Edit the text on the poster – it re-renders in about 10 seconds, same design." : "Edit the texts and voice-over, let the AI rewrite a scene, or pick another voice."}</div>
      </div>
      {item.editable.poster_text && <Button variant="dark" icon={<Type className="size-4" />} onClick={() => setPoster(true)}>Edit text</Button>}
      {item.editable.video_scenes && <Button variant="dark" icon={<Video className="size-4" />} onClick={() => setScenes(true)}>Edit scenes</Button>}
      {poster && <PosterTextEditor item={item} onClose={() => setPoster(false)} />}
      {scenes && <SceneEditor item={item} onClose={() => setScenes(false)} />}
    </Card>
  );
}

// ── poster text editor ─────────────────────────────────────────────────────
type TextNode = { node: Text; original: string; lead: string; trail: string };

function collectTexts(doc: Document): TextNode[] {
  const out: TextNode[] = [];
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      const parent = n.parentElement?.tagName.toLowerCase() ?? "";
      if (["script", "style", "noscript", "title"].includes(parent)) return NodeFilter.FILTER_REJECT;
      return (n.textContent ?? "").trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.textContent ?? "";
    out.push({ node: n as Text, original: t.trim(), lead: t.match(/^\s*/)?.[0] ?? "", trail: t.match(/\s*$/)?.[0] ?? "" });
  }
  return out;
}

function PosterTextEditor({ item, onClose }: { item: ItemDetail; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefreshItem(item.id);
  const { data, error, isLoading } = useQuery({ queryKey: ["design", item.id, item.media], queryFn: () => api.design(item.id), staleTime: 0 });
  const parsed = useMemo(() => {
    if (!data) return null;
    const doc = new DOMParser().parseFromString(data.html, "text/html");
    return { doc, nodes: collectTexts(doc) };
  }, [data]);
  const [values, setValues] = useState<string[]>([]);
  useEffect(() => { if (parsed) setValues(parsed.nodes.map((n) => n.original)); }, [parsed]);

  const html = useMemo(() => {
    if (!parsed || values.length !== parsed.nodes.length) return "";
    parsed.nodes.forEach((n, i) => { n.node.textContent = n.lead + values[i] + n.trail; });
    return "<!DOCTYPE html>\n" + parsed.doc.documentElement.outerHTML;
  }, [parsed, values]);
  const [previewHtml, setPreviewHtml] = useState("");
  useEffect(() => { const t = setTimeout(() => setPreviewHtml(html), 350); return () => clearTimeout(t); }, [html]);
  const changed = parsed ? values.some((v, i) => v !== parsed.nodes[i]?.original) : false;

  const frameBox = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.3);
  useEffect(() => {
    const el = frameBox.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(el.clientWidth / 1080));
    ro.observe(el);
    return () => ro.disconnect();
  }, [parsed]);

  const save = useMutation({
    mutationFn: () => api.saveDesign(item.id, html),
    onSuccess: ({ item: d, issues }) => {
      refresh(d);
      toast(issues.length ? "error" : "ok", issues.length ? `Saved – but check the layout: ${issues.slice(0, 2).join("; ")}` : "Poster updated");
      onClose();
    },
    onError: (e: Error) => toast("error", e.message),
  });

  return (
    <Modal open onClose={onClose} title="Edit the poster text"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={<Pencil className="size-4" />} disabled={!changed} loading={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Rendering…" : "Save & re-render"}
        </Button>
      </>}>
      {isLoading ? <div className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="size-4 animate-spin" /> Loading the design…</div>
        : error ? <p className="text-sm text-red-600">{(error as Error).message}</p>
        : parsed && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_11rem]">
            <div className="space-y-2.5">
              <p className="text-xs text-stone-500">Every text on the poster, top to bottom. Keep lengths similar so the design still fits.</p>
              {parsed.nodes.map((n, i) => (
                <div key={i}>
                  {(values[i] ?? "").length > 48 || n.original.length > 48 ? (
                    <textarea rows={2} value={values[i] ?? ""} onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
                      className={clsx(inputCls, "resize-y text-sm", values[i] !== n.original && "ring-2 ring-brand-400")} />
                  ) : (
                    <input value={values[i] ?? ""} onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
                      className={clsx(inputCls, "text-sm", values[i] !== n.original && "ring-2 ring-brand-400")} />
                  )}
                </div>
              ))}
            </div>
            <div className="order-first mx-auto w-36 sm:order-none sm:mx-0 sm:w-auto">
              <div className="sticky top-0">
                <div className="text-xs font-semibold text-stone-500">Live preview</div>
                <div ref={frameBox} className="relative mt-1 w-full overflow-hidden rounded-lg ring-1 ring-stone-200" style={{ aspectRatio: "1080 / 1350" }}>
                  {previewHtml && (
                    <iframe title="Poster preview" srcDoc={previewHtml} sandbox="allow-same-origin"
                      style={{ width: 1080, height: 1350, transform: `scale(${scale})`, transformOrigin: "0 0", border: 0, pointerEvents: "none" }} />
                  )}
                </div>
                <p className="mt-1 text-[11px] text-stone-400">The saved poster is rendered at full size on the server.</p>
              </div>
            </div>
          </div>
        )}
    </Modal>
  );
}

// ── video scene editor ─────────────────────────────────────────────────────
type Board = Storyboard["board"];
const FIELDS: Record<"festive" | "intro" | "scene" | "grid" | "outro", [keyof SceneTexts, string, boolean?][]> = {
  festive: [["greeting", "Small word (e.g. Happy)"], ["name", "Festival name"], ["quote", "Quote – put one {word} in braces to highlight it", true], ["voice", "Voice-over", true]],
  intro: [["eyebrow", "Small label"], ["headline", "Headline"], ["accent", "Headline (coloured part)"], ["sub", "Sub-line", true], ["voice", "Voice-over", true]],
  scene: [["eyebrow", "Small label"], ["headline", "Headline"], ["accent", "Headline (coloured part)"], ["voice", "Voice-over", true]],
  grid: [["eyebrow", "Small label"], ["headline", "Headline"], ["accent", "Headline (coloured part)"], ["voice", "Voice-over", true]],
  outro: [["headline", "Headline"], ["accent", "Headline (coloured part)"], ["cta", "Button text"], ["url", "Website shown"], ["voice", "Voice-over", true]],
};

function SceneEditor({ item, onClose }: { item: ItemDetail; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefreshItem(item.id);
  const { data, error, isLoading } = useQuery({ queryKey: ["storyboard", item.id, item.media], queryFn: () => api.storyboard(item.id), staleTime: 0 });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [board, setBoard] = useState<Board | null>(null);
  useEffect(() => { if (data) setBoard(structuredClone(data.board)); }, [data]);
  const changed = !!board && !!data && JSON.stringify(board) !== JSON.stringify(data.board);

  const setPart = (part: string, patch: Partial<SceneTexts>) => setBoard((b) => {
    if (!b) return b;
    const n = structuredClone(b);
    if (part.startsWith("scene:")) n.scenes[Number(part.slice(6))] = { ...n.scenes[Number(part.slice(6))], ...patch };
    else (n as unknown as Record<string, SceneTexts>)[part] = { ...((n as unknown as Record<string, SceneTexts>)[part] ?? {}), ...patch };
    return n;
  });

  const preview = useMutation({ mutationFn: () => api.voicePreview(board?.voice_name ?? ""), onSuccess: ({ url }) => new Audio(url).play(),
    onError: (e: Error) => toast("error", e.message) });
  const save = useMutation({
    mutationFn: () => {
      const b = board!;
      const edits: Record<string, unknown> = { scenes: b.scenes.map(({ screen: _s, ...rest }) => rest) };
      for (const k of ["festive", "intro", "grid", "outro"] as const) if (b[k]) edits[k] = b[k];
      return api.saveStoryboard(item.id, edits, b.voice_name);
    },
    onSuccess: (d) => {
      refresh(d);
      toast("ok", d.status === "queued" ? "Saved – your PC will rebuild the video" : "Saved – rebuilding the video (a few minutes)");
      onClose();
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const parts: { id: string; title: string; kind: keyof typeof FIELDS; d: SceneTexts }[] = board ? [
    ...(board.festive?.name ? [{ id: "festive", title: "Festival greeting", kind: "festive" as const, d: board.festive }] : []),
    ...(board.intro ? [{ id: "intro", title: "Opening", kind: "intro" as const, d: board.intro }] : []),
    ...board.scenes.map((sc, i) => ({ id: `scene:${i}`, title: `Scene ${i + 1}`, kind: "scene" as const, d: sc })),
    ...(board.grid && (board.grid.items?.length ?? 0) > 0 ? [{ id: "grid", title: "Features overview", kind: "grid" as const, d: board.grid }] : []),
    ...(board.outro ? [{ id: "outro", title: "Ending", kind: "outro" as const, d: board.outro }] : []),
  ] : [];

  return (
    <Modal open onClose={onClose} title="Edit scenes & voice"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={<RefreshCw className="size-4" />} disabled={!changed} loading={save.isPending} onClick={() => save.mutate()}>Save & rebuild video</Button>
      </>}>
      {isLoading ? <div className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="size-4 animate-spin" /> Loading the storyboard…</div>
        : error ? <p className="text-sm text-red-600">{(error as Error).message}</p>
        : board && (
          <div className="space-y-5">
            <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200">
              <label className="text-sm font-semibold" htmlFor="voice-pick">Voice for this video</label>
              <div className="mt-1.5 flex gap-2">
                <select id="voice-pick" value={board.voice_name} onChange={(e) => setBoard({ ...board, voice_name: e.target.value })} className={clsx(inputCls, "min-w-0 flex-1")}>
                  {(settings?.catalog.voices ?? [{ id: board.voice_name, label: board.voice_name }]).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
                <Button variant="outline" icon={<Volume2 className="size-4" />} loading={preview.isPending} onClick={() => preview.mutate()}>Listen</Button>
              </div>
            </div>
            {parts.map((p) => <ScenePart key={p.id} item={item} part={p.id} title={p.title} kind={p.kind} d={p.d} onChange={(patch) => setPart(p.id, patch)} />)}
            <p className="text-xs text-stone-500">Rebuilding takes a few minutes{item.status === "approved" ? " – the video goes back to “Needs review” so you can check it" : ""}. The current version stays until the new one is ready.</p>
          </div>
        )}
    </Modal>
  );
}

function ScenePart({ item, part, title, kind, d, onChange }: {
  item: ItemDetail; part: string; title: string; kind: keyof typeof FIELDS; d: SceneTexts; onChange: (patch: Partial<SceneTexts>) => void;
}) {
  const toast = useToast();
  const [ask, setAsk] = useState("");
  const [open, setOpen] = useState(false);
  const rewrite = useMutation({
    mutationFn: () => api.rewritePart(item.id, part, ask),
    onSuccess: ({ texts }) => { onChange(texts); setOpen(false); setAsk(""); toast("ok", `${title} rewritten – check it, then save`); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <section className="rounded-xl p-3 ring-1 ring-stone-200">
      <div className="flex items-center gap-3">
        {d.screen && <img src={d.screen} alt="" className="h-12 w-20 shrink-0 rounded-md object-cover object-top ring-1 ring-stone-200" />}
        <h3 className="flex-1 font-bold">{title}</h3>
        <Button variant="ghost" className="px-2.5 py-1 text-xs" icon={<Wand2 className="size-3.5" />} onClick={() => setOpen((o) => !o)}>AI rewrite</Button>
      </div>
      {open && (
        <div className="mt-2 flex gap-2">
          <input value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="e.g. shorter, mention the free demo" className={clsx(inputCls, "min-w-0 flex-1 text-sm")}
            onKeyDown={(e) => e.key === "Enter" && rewrite.mutate()} />
          <Button variant="dark" className="px-3 text-xs" icon={<Sparkles className="size-3.5" />} loading={rewrite.isPending} onClick={() => rewrite.mutate()}>Rewrite</Button>
        </div>
      )}
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {FIELDS[kind].filter(([k]) => d[k] !== undefined || k === "voice").map(([k, label, wide]) => (
          <label key={k} className={clsx("block", wide && "sm:col-span-2")}>
            <span className="text-xs font-semibold text-stone-500">{label}</span>
            {wide ? (
              <textarea rows={2} value={String(d[k] ?? "")} onChange={(e) => onChange({ [k]: e.target.value })} className={clsx(inputCls, "mt-0.5 resize-y text-sm")} />
            ) : (
              <input value={String(d[k] ?? "")} onChange={(e) => onChange({ [k]: e.target.value })} className={clsx(inputCls, "mt-0.5 text-sm")} />
            )}
          </label>
        ))}
        {kind === "scene" && (d.bullets ?? []).map((b, i) => (
          <label key={`b${i}`} className="block sm:col-span-2">
            <span className="text-xs font-semibold text-stone-500">Point {i + 1}</span>
            <input value={b.text} onChange={(e) => onChange({ bullets: (d.bullets ?? []).map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })}
              className={clsx(inputCls, "mt-0.5 text-sm")} />
          </label>
        ))}
      </div>
    </section>
  );
}

// ── results after posting ──────────────────────────────────────────────────
const NUM: [keyof NonNullable<ItemDetail["metrics"]>, string, typeof Heart][] = [
  ["likes", "Likes", Heart], ["comments", "Comments", MessageCircle], ["shares", "Shares", Share2],
  ["reach", "Reach", Eye], ["views", "Views", Play], ["clicks", "Clicks", MousePointerClick],
];

export function MetricsCard({ item }: { item: ItemDetail }) {
  const toast = useToast();
  const refresh = useRefreshItem(item.id);
  const r = useMutation({
    mutationFn: () => api.refreshMetrics(item.id),
    onSuccess: (d) => { refresh(d); toast("ok", "Results updated"); },
    onError: (e: Error) => toast("error", e.message),
  });
  if (!["published", "partial"].includes(item.status)) return null;
  const rows = Object.entries(item.metrics_detail ?? {}) as [Platform, NonNullable<ItemDetail["metrics_detail"][Platform]>][];
  const fetched = rows.map(([, m]) => m.fetched_at).filter(Boolean).sort().pop();
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-bold">Results</h2>
        <Button variant="outline" className="px-2.5 py-1 text-xs" icon={<RefreshCw className="size-3.5" />} loading={r.isPending} onClick={() => r.mutate()}>Refresh</Button>
      </div>
      {!rows.length ? (
        <p className="mt-2 text-sm text-stone-500">No numbers yet. They're fetched every 6 hours after posting{Object.values(item.results ?? {}).some((x) => x?.dry_run) ? " (test-mode posts have none)" : ""}.</p>
      ) : (
        <>
          {item.metrics && (
            <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
              {NUM.map(([k, label, Icon]) => (
                <div key={k} className="rounded-lg bg-stone-50 px-2 py-2 text-center ring-1 ring-stone-200/70">
                  <Icon className="mx-auto size-3.5 text-stone-400" />
                  <div className="mt-0.5 font-bold tabular-nums">{(item.metrics![k] ?? 0).toLocaleString()}</div>
                  <div className="text-[10px] uppercase tracking-wide text-stone-500">{label}</div>
                </div>
              ))}
            </div>
          )}
          <table className="mt-3 w-full text-xs">
            <tbody>
              {rows.map(([p, m]) => (
                <tr key={p} className="border-t border-stone-100">
                  <td className="py-1.5 pr-2 font-semibold">{PLATFORMS.find((x) => x.id === p)?.label ?? p}</td>
                  <td className="py-1.5 text-stone-600">
                    {NUM.some(([k]) => m[k] !== undefined) &&
                      NUM.filter(([k]) => (m[k] ?? 0) > 0 || ["likes", "comments"].includes(k)).map(([k, label]) => `${(m[k] ?? 0).toLocaleString()} ${label.toLowerCase()}`).join(" · ")}
                    {m.error && <span className="block text-[11px] text-red-600" title={m.error}>Couldn't update just now – showing the last numbers ({m.error.slice(0, 60)})</span>}
                    {m.notes && <span className="block text-[11px] text-stone-400" title={m.notes}>Some numbers aren't available for this post</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {fetched && <p className="mt-2 text-[11px] text-stone-400">Updated {ago(fetched)}</p>}
        </>
      )}
    </Card>
  );
}
