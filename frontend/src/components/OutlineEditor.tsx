// Phase 6: the video's outline (storyboard) before anything is rendered – reorder, remove, rename scenes, pick the
// voice, then "Make video". Rendering is the slow part, so mistakes are fixed here for free.
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowDown, ArrowUp, Clapperboard, Film, Globe, ListOrdered, Loader2, MonitorPlay, Save, Trash2, Undo2, Volume2, Workflow,
} from "lucide-react";
import { api, type ItemDetail, type SceneTexts, type Storyboard } from "../lib/api";
import { Button, Card, inputCls, useToast } from "./ui";

type Board = Storyboard["board"];

const TYPE: Record<string, { label: string; icon: typeof Globe; cls: string }> = {
  tour: { label: "Page tour", icon: Globe, cls: "bg-sky-50 text-sky-700 ring-sky-200" },
  feature: { label: "Screen", icon: MonitorPlay, cls: "bg-amber-50 text-amber-800 ring-amber-200" },
  workflow: { label: "How it works", icon: Workflow, cls: "bg-violet-50 text-violet-700 ring-violet-200" },
  clip: { label: "Your recording", icon: Film, cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
};

function seconds(sc: SceneTexts): number {
  const words = String(sc.voice ?? "").split(/\s+/).filter(Boolean).length;
  const base = sc.type === "tour" ? 8.5 : sc.type === "workflow" ? 2.6 + 1.5 * (sc.steps?.length ?? 0)
    : sc.type === "clip" ? 1.7 + (sc.clip_s ?? 6.5) : 6.4;
  return Math.min(Math.max(base, words ? words / 2.6 + 1.2 : 0), 16);
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export default function OutlineEditor({ item }: { item: ItemDetail }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({ queryKey: ["storyboard", item.id, "outline"], queryFn: () => api.storyboard(item.id), staleTime: 0 });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [board, setBoard] = useState<Board | null>(null);
  const [order, setOrder] = useState<number[]>([]);
  const [keepGrid, setKeepGrid] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    if (!data) return;
    setBoard(structuredClone(data.board));
    setOrder(data.board.scenes.map((_, i) => i));
  }, [data]);

  const removed = board ? board.scenes.map((_, i) => i).filter((i) => !order.includes(i)) : [];
  const hasGrid = !!board?.grid && (board.grid.items?.length ?? 0) > 0;
  const total = useMemo(() => {
    if (!board) return 0;
    let t = (board.festive?.name ? 5.8 : 0) + 4.6 + 5 + (hasGrid && keepGrid ? 6 : 0);
    for (const i of order) t += seconds(board.scenes[i]);
    return t;
  }, [board, order, hasGrid, keepGrid]);
  const changed = !!board && !!data && (JSON.stringify(board) !== JSON.stringify(data.board)
    || order.join() !== data.board.scenes.map((_, i) => i).join() || (hasGrid && !keepGrid));

  const setScene = (i: number, patch: Partial<SceneTexts>) =>
    setBoard((b) => { if (!b) return b; const n = structuredClone(b); n.scenes[i] = { ...n.scenes[i], ...patch }; return n; });
  const setPart = (k: "intro" | "outro", patch: Partial<SceneTexts>) =>
    setBoard((b) => (b ? { ...b, [k]: { ...(b[k] ?? {}), ...patch } } : b));
  const move = (pos: number, dir: -1 | 1) => setOrder((o) => {
    const n = [...o]; const j = pos + dir;
    if (j < 0 || j >= n.length) return o;
    [n[pos], n[j]] = [n[j], n[pos]];
    return n;
  });

  const preview = useMutation({ mutationFn: () => api.voicePreview(board?.voice_name ?? ""), onSuccess: ({ url }) => new Audio(url).play(),
    onError: (e: Error) => toast("error", e.message) });
  const save = useMutation({
    mutationFn: (render: boolean) => {
      const b = board!;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const edits: Record<string, unknown> = { scenes: b.scenes.map(({ screen, screen_tall, clip, clip_s, ...rest }) => rest), order };
      if (b.intro) edits.intro = b.intro;
      if (b.outro) edits.outro = b.outro;
      if (b.festive) edits.festive = b.festive;
      if (hasGrid) edits.grid = keepGrid ? b.grid : null;
      return api.saveOutline(item.id, edits, b.voice_name, render);
    },
    onSuccess: (d, render) => {
      qc.setQueryData(["item", item.id], d);
      qc.invalidateQueries({ queryKey: ["item", item.id] });
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
      qc.invalidateQueries({ queryKey: ["storyboard", item.id] });
      toast("ok", !render ? "Outline saved" : d.status === "queued" ? "Your PC will make the video now" : "Making the video – a few minutes");
    },
    onError: (e: Error) => toast("error", e.message),
  });

  if (isLoading || !board) return (
    <Card className="grid min-h-60 place-items-center p-8 text-sm text-stone-500">
      {error ? <span className="text-red-600">{(error as Error).message}</span> : <span className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" /> Loading the outline…</span>}
    </Card>
  );

  const series = item.options?.series_total ? ` · part ${item.options.series_part} of ${item.options.series_total}` : "";
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-stone-200 bg-violet-50/60 px-5 py-4">
        <span className="grid size-10 place-items-center rounded-xl bg-violet-600 text-white"><ListOrdered className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="font-bold">Video outline</h2>
          <p className="text-xs text-stone-500">{order.length} scenes · about {mmss(total)}{item.options?.length === "full" ? " · full walkthrough" : " · short"}{series}. Nothing is rendered yet – change anything, then press Make video.</p>
        </div>
      </div>

      <div className="space-y-3 p-4 sm:p-5">
        <Fixed title="Opening" d={board.intro ?? {}} onChange={(p) => setPart("intro", p)} />

        <ol className="space-y-2">
          {order.map((i, pos) => {
            const sc = board.scenes[i];
            const t = TYPE[sc.type ?? "feature"] ?? TYPE.feature;
            const Icon = t.icon;
            const isOpen = open === i;
            return (
              <li key={i} className={clsx("rounded-xl ring-1 transition", isOpen ? "ring-2 ring-ink-900" : "ring-stone-200")}>
                <div className="flex items-center gap-3 p-2.5">
                  <span className="w-5 text-center text-sm font-bold tabular-nums text-stone-400">{pos + 1}</span>
                  <div className="relative h-14 w-24 shrink-0 overflow-hidden rounded-lg bg-stone-100 ring-1 ring-stone-200">
                    {sc.clip ? (
                      <>
                        <video src={sc.clip} poster={sc.screen} muted loop playsInline preload="none" className="size-full object-cover object-top"
                          onMouseEnter={(e) => e.currentTarget.play().catch(() => null)} onMouseLeave={(e) => e.currentTarget.pause()} />
                        <span className="pointer-events-none absolute bottom-0.5 left-0.5 rounded bg-black/70 px-1 text-[10px] font-semibold text-white">▶ hover</span>
                      </>
                    ) : sc.screen ? <img src={sc.screen} alt="" className="size-full object-cover object-top" />
                      : <span className="grid size-full place-items-center text-violet-500"><Workflow className="size-6" /></span>}
                  </div>
                  <button type="button" onClick={() => setOpen(isOpen ? null : i)} className="min-w-0 flex-1 text-left">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1", t.cls)}><Icon className="size-3" />{t.label}</span>
                      {sc.page_name && <span className="truncate text-[11px] text-stone-400">{sc.page_name}</span>}
                      <span className="text-[11px] tabular-nums text-stone-400">~{Math.round(seconds(sc))}s</span>
                    </div>
                    <div className="mt-0.5 truncate text-sm font-semibold">{sc.headline} <span className="text-brand-700">{sc.accent}</span></div>
                  </button>
                  <div className="flex shrink-0 items-center">
                    <IconBtn title="Move up" disabled={pos === 0} onClick={() => move(pos, -1)}><ArrowUp className="size-4" /></IconBtn>
                    <IconBtn title="Move down" disabled={pos === order.length - 1} onClick={() => move(pos, 1)}><ArrowDown className="size-4" /></IconBtn>
                    <IconBtn title="Remove scene" disabled={order.length <= 1} onClick={() => setOrder((o) => o.filter((x) => x !== i))}><Trash2 className="size-4" /></IconBtn>
                  </div>
                </div>
                {isOpen && (
                  <div className="grid grid-cols-1 gap-2 border-t border-stone-100 p-3 sm:grid-cols-2">
                    <Text label="Small label" v={sc.eyebrow} on={(v) => setScene(i, { eyebrow: v })} />
                    <Text label="Page" v={sc.page_name} on={(v) => setScene(i, { page_name: v })} />
                    <Text label="Headline" v={sc.headline} on={(v) => setScene(i, { headline: v })} />
                    <Text label="Headline (coloured part)" v={sc.accent} on={(v) => setScene(i, { accent: v })} />
                    {(sc.bullets ?? []).map((b, j) => (
                      <Text key={`b${j}`} wide label={`Point ${j + 1}`} v={b.text}
                        on={(v) => setScene(i, { bullets: (sc.bullets ?? []).map((x, k) => (k === j ? { ...x, text: v } : x)) })} />
                    ))}
                    {(sc.steps ?? []).map((st, j) => (
                      <div key={`s${j}`} className="grid grid-cols-[2rem_1fr_1.4fr] items-end gap-2 sm:col-span-2">
                        <span className="grid size-8 place-items-center rounded-full bg-violet-600 text-xs font-bold text-white">{j + 1}</span>
                        <Text label="Step" v={st.title} on={(v) => setScene(i, { steps: (sc.steps ?? []).map((x, k) => (k === j ? { ...x, title: v } : x)) })} />
                        <Text label="Description" v={st.desc} on={(v) => setScene(i, { steps: (sc.steps ?? []).map((x, k) => (k === j ? { ...x, desc: v } : x)) })} />
                      </div>
                    ))}
                    <Text wide area label="Voice-over" v={sc.voice} on={(v) => setScene(i, { voice: v })} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>

        {removed.length > 0 && (
          <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200">
            <div className="text-xs font-semibold text-stone-500">Removed – click to put back</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {removed.map((i) => (
                <button key={i} type="button" onClick={() => setOrder((o) => [...o, i])}
                  className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-medium text-stone-600 ring-1 ring-stone-200 hover:ring-stone-400">
                  <Undo2 className="size-3" /> {board.scenes[i].headline || `Scene ${i + 1}`}
                </button>
              ))}
            </div>
          </div>
        )}

        {hasGrid && (
          <label className="flex cursor-pointer items-center gap-3 rounded-xl p-3 ring-1 ring-stone-200">
            <input type="checkbox" checked={keepGrid} onChange={(e) => setKeepGrid(e.target.checked)} className="size-4 accent-brand-600" />
            <span className="text-sm"><b>Features overview</b> <span className="text-stone-500">– {board.grid?.items?.length} features in a grid, ~6s</span></span>
          </label>
        )}

        <Fixed title="Ending" d={board.outro ?? {}} onChange={(p) => setPart("outro", p)} />

        <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200">
          <label className="text-sm font-semibold" htmlFor="outline-voice">Voice</label>
          <div className="mt-1.5 flex gap-2">
            <select id="outline-voice" value={board.voice_name} onChange={(e) => setBoard({ ...board, voice_name: e.target.value })} className={clsx(inputCls, "min-w-0 flex-1")}>
              {(settings?.catalog.voices ?? [{ id: board.voice_name, label: board.voice_name }]).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
            <Button variant="outline" icon={<Volume2 className="size-4" />} loading={preview.isPending} onClick={() => preview.mutate()}>Listen</Button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-stone-200 bg-stone-50 px-5 py-3">
        <span className="mr-auto text-xs text-stone-500">Estimated length <b className="tabular-nums text-stone-800">{mmss(total)}</b></span>
        <Button variant="outline" icon={<Save className="size-4" />} disabled={!changed} loading={save.isPending && save.variables === false}
          onClick={() => save.mutate(false)}>Save outline</Button>
        <Button variant="primary" icon={<Clapperboard className="size-4" />} loading={save.isPending && save.variables === true}
          onClick={() => save.mutate(true)}>Make video</Button>
      </div>
    </Card>
  );
}

function Fixed({ title, d, onChange }: { title: string; d: SceneTexts; onChange: (p: Partial<SceneTexts>) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl bg-stone-50 ring-1 ring-stone-200">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 p-3 text-left">
        <span className="text-xs font-bold uppercase tracking-wide text-stone-400">{title}</span>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{d.headline} <span className="text-brand-700">{d.accent}</span></span>
      </button>
      {open && (
        <div className="grid grid-cols-1 gap-2 border-t border-stone-200 p-3 sm:grid-cols-2">
          <Text label="Headline" v={d.headline} on={(v) => onChange({ headline: v })} />
          <Text label="Headline (coloured part)" v={d.accent} on={(v) => onChange({ accent: v })} />
          {d.sub !== undefined && <Text wide label="Sub-line" v={d.sub} on={(v) => onChange({ sub: v })} />}
          {d.cta !== undefined && <Text label="Button text" v={d.cta} on={(v) => onChange({ cta: v })} />}
          {d.url !== undefined && <Text label="Website shown" v={d.url} on={(v) => onChange({ url: v })} />}
          <Text wide area label="Voice-over" v={d.voice} on={(v) => onChange({ voice: v })} />
        </div>
      )}
    </div>
  );
}

function Text({ label, v, on, wide, area }: { label: string; v?: string; on: (v: string) => void; wide?: boolean; area?: boolean }) {
  return (
    <label className={clsx("block", wide && "sm:col-span-2")}>
      <span className="text-xs font-semibold text-stone-500">{label}</span>
      {area ? <textarea rows={2} maxLength={400} value={v ?? ""} onChange={(e) => on(e.target.value)} className={clsx(inputCls, "mt-0.5 resize-y text-sm")} />
        : <input maxLength={400} value={v ?? ""} onChange={(e) => on(e.target.value)} className={clsx(inputCls, "mt-0.5 text-sm")} />}
    </label>
  );
}

function IconBtn({ children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" {...rest} className="grid size-8 place-items-center rounded-lg text-stone-500 hover:bg-stone-100 hover:text-stone-900 disabled:opacity-30 disabled:hover:bg-transparent">{children}</button>;
}
