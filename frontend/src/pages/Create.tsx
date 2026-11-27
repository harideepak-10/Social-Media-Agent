import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Film, Globe, ImageIcon, ListChecks, Palette, ScanSearch, Sparkles, Wand2 } from "lucide-react";
import { api, type VideoLength, type VideoStyle } from "../lib/api";
import ScreenshotDrop, { type Shot } from "../components/ScreenshotDrop";
import { ago, displayTitle } from "../lib/ui";
import { Button, Card, StatusBadge, useToast } from "../components/ui";

const IDEAS = [
  "Explain the main features for business owners",
  "Focus on how it saves time",
  "Show the pricing and plans",
  "Target restaurant owners",
  "Make it fun and energetic",
];

export default function Create() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<"video" | "post">("video");
  const [notes, setNotes] = useState("");
  const [touched, setTouched] = useState(false);
  const [length, setLength] = useState<VideoLength>("short");
  const [outline, setOutline] = useState(true);
  const [style, setStyle] = useState<VideoStyle>("tour");
  const [shots, setShots] = useState<Shot[]>([]);
  const uploading = shots.some((s) => !s.ref);
  const recInPost = kind === "post" && shots.some((s) => s.video);

  const cleaned = url.trim();
  const hasInput = !!cleaned || !!notes.trim() || shots.length > 0;
  const valid = !cleaned || /^(https?:\/\/)?([\w-]+\.)+[\w-]{2,}(:\d+)?(\/\S*)?$/i.test(cleaned) || /^(https?:\/\/)?localhost(:\d+)?(\/\S*)?$/i.test(cleaned);
  // only this PC can open these – the job goes to the PC worker (run_video_worker.bat)
  const local = /^(https?:\/\/)?(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|[\w-]+\.(local|lan)(?=[:/]|$))/i.test(cleaned);

  const recent = useQuery({ queryKey: ["items", "recent-url"], queryFn: () => api.items({ q: "", limit: 60 }), refetchInterval: 10000 });
  const fromLinks = (recent.data?.items ?? []).filter((i) => i.source_url || i.source === "prompt").slice(0, 6);

  const create = useMutation({
    mutationFn: () => api.fromUrl(cleaned, kind, notes, {
      length, outline, style,
      screenshots: shots.filter((s) => s.ref).map((s) => ({ ref: s.ref!, caption: s.caption })),
    }),
    onSuccess: ({ id }) => {
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
      toast("ok", "Started – you can watch the progress here");
      nav(`/items/${id}`);
    },
    onError: (e: Error) => toast("error", e.message),
  });

  return (
    <div className="mx-auto max-w-6xl px-5 py-8 md:px-10">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Create a video or post</h1>
      <p className="mt-1 text-sm text-stone-500">Paste a link, write a prompt, add screenshots or screen recordings – any of them. With a link the agent explores the whole site and uses its design; without one it uses your brand and your prompt.</p>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="p-4 sm:p-6 md:p-8">
          <form onSubmit={(e) => { e.preventDefault(); setTouched(true); if (valid && hasInput) create.mutate(); }} className="space-y-7">
            <div>
              <label className="text-sm font-bold">Website link <span className="font-normal text-stone-400">(optional)</span></label>
              <div className={clsx("mt-2 flex items-center gap-3 rounded-xl bg-stone-50 px-4 py-3 ring-1 transition focus-within:bg-white focus-within:ring-2",
                touched && cleaned && !valid ? "ring-red-300 focus-within:ring-red-500" : "ring-stone-200 focus-within:ring-ink-900")}>
                <Globe className="size-5 shrink-0 text-stone-400" />
                <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} onBlur={() => setTouched(true)}
                  placeholder="https://www.krypsos.tech/restaurant-pos/" inputMode="url"
                  className="w-full bg-transparent text-base outline-none placeholder:text-stone-400" />
              </div>
              {touched && cleaned && !valid && <p className="mt-1.5 text-xs text-red-600">That doesn't look like a website link.</p>}
              {cleaned && valid && local && (
                <p className="mt-1.5 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-800 ring-1 ring-indigo-200">
                  <b>Local address</b> – only your PC can open it, so your PC makes this one. Keep <code>run_video_worker.bat</code> running and the site started.
                </p>
              )}
              <p className="mt-1.5 text-xs text-stone-400">Paste the home page – the agent finds the other pages itself. Leave it empty to make it from your prompt and uploads (your own brand). Free-hosted sites (e.g. Render) that are asleep are woken up automatically. Sites that need a login: run <code className="rounded bg-stone-100 px-1">python cli.py login --url …</code> once.</p>
            </div>

            <div>
              <div className="flex items-baseline justify-between gap-2">
                <label className="text-sm font-bold" htmlFor="prompt">Prompt <span className="font-normal text-stone-400">(optional with a link)</span></label>
                <span className={clsx("text-xs tabular-nums", notes.length > 7500 ? "text-amber-600" : "text-stone-400")}>{notes.length.toLocaleString()} / 8,000</span>
              </div>
              <textarea id="prompt" value={notes} onChange={(e) => setNotes(e.target.value)} rows={notes.length > 300 ? 10 : 5} maxLength={8000}
                placeholder={"Tell the agent what to make – as short or as detailed as you like.\ne.g. A 60-second video for clinic owners about our appointment booking: start with the no-show problem, show booking → reminder → check-in, mention the free trial, friendly tone."}
                className="mt-2 w-full resize-y rounded-xl bg-stone-50 p-4 text-sm leading-relaxed outline-none ring-1 ring-stone-200 focus:bg-white focus:ring-2 focus:ring-ink-900" />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {IDEAS.map((idea) => (
                  <button type="button" key={idea} onClick={() => setNotes((n) => (n.trim() ? `${n.trim()}\n${idea}` : idea))}
                    className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600 hover:bg-stone-200">+ {idea}</button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-sm font-bold">What should it make?</label>
              <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {([
                  ["video", Film, "Walkthrough video", "16:9 + 9:16 with voice-over and music · 5–15 min to make"],
                  ["post", ImageIcon, "Designed post", "1080×1350 image with captions · about 1 min"],
                ] as const).map(([k, Icon, title, sub]) => (
                  <button type="button" key={k} onClick={() => setKind(k)}
                    className={clsx("flex items-start gap-3 rounded-xl p-4 text-left ring-1 transition",
                      kind === k ? "bg-brand-50 ring-2 ring-brand-600" : "bg-white ring-stone-200 hover:ring-stone-300")}>
                    <span className={clsx("grid size-10 shrink-0 place-items-center rounded-lg", kind === k ? "bg-brand-600 text-white" : "bg-stone-100 text-stone-500")}>
                      <Icon className="size-5" />
                    </span>
                    <span><span className="block font-semibold">{title}</span><span className="mt-0.5 block text-xs text-stone-500">{sub}</span></span>
                  </button>
                ))}
              </div>
            </div>

            {kind === "video" && (
              <div>
                <label className="text-sm font-bold">Style</label>
                <div className="mb-5 mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {([
                    ["tour", "Product tour", "Full-screen app, a cursor clicks through the pages, each section lights up with a label – like a launch demo"],
                    ["classic", "Classic", "Screens in a browser window with headline and points beside them"],
                  ] as const).map(([k, t, d]) => (
                    <button type="button" key={k} onClick={() => setStyle(k)}
                      className={clsx("rounded-xl p-3 text-left ring-1 transition",
                        style === k ? "bg-brand-50 ring-2 ring-brand-600" : "bg-white ring-stone-200 hover:ring-stone-300")}>
                      <span className="block text-sm font-semibold">{t}{k === "tour" && <span className="ml-1.5 rounded bg-brand-600 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">New</span>}</span>
                      <span className="mt-0.5 block text-xs text-stone-500">{d}</span>
                    </button>
                  ))}
                </div>
                <label className="text-sm font-bold">How long?</label>
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {([
                    ["short", "Short", "45–60 s highlight · Reels & LinkedIn"],
                    ["full", "Full walkthrough", "2–4 min · every main page + how it works"],
                    ["series", "Series", "One short Reel per page, one a day (up to 5)"],
                  ] as const).map(([k, t, d]) => (
                    <button type="button" key={k} onClick={() => setLength(k)}
                      className={clsx("rounded-xl p-3 text-left ring-1 transition",
                        length === k ? "bg-brand-50 ring-2 ring-brand-600" : "bg-white ring-stone-200 hover:ring-stone-300")}>
                      <span className="block text-sm font-semibold">{t}</span>
                      <span className="mt-0.5 block text-xs text-stone-500">{d}</span>
                    </button>
                  ))}
                </div>
                <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200">
                  <input type="checkbox" checked={outline} onChange={(e) => setOutline(e.target.checked)} className="mt-0.5 size-4 accent-brand-600" />
                  <span>
                    <span className="flex items-center gap-1.5 text-sm font-semibold"><ListChecks className="size-4 text-stone-500" /> Show me the outline first</span>
                    <span className="block text-xs text-stone-500">Check, reorder, rename or remove scenes before the video is made – saves a slow re-render.</span>
                  </span>
                </label>
              </div>
            )}

            <div>
              <label className="text-sm font-bold">{kind === "video" ? "Your screenshots or screen recordings" : "Your screenshots"} <span className="font-normal text-stone-400">(optional)</span></label>
              <p className="mt-0.5 text-xs text-stone-500">
                {kind === "video"
                  ? "Add screens the agent can't reach itself – e.g. inside your app after login. A screenshot becomes a scene with your caption; from a screen recording (Win+Alt+R) the agent cuts the best moments into clips that play in the video."
                  : "Add a screen of your product – the post shows it instead of a captured one."}
              </p>
              <ScreenshotDrop shots={shots} onChange={setShots} max={kind === "video" ? 25 : 2} allowVideo={kind === "video"} />
              {recInPost && <p className="mt-1.5 text-xs text-red-600">Screen recordings are for videos – remove them, or switch to Walkthrough video.</p>}
            </div>


            <Button type="submit" variant="primary" className="w-full py-3 text-base" loading={create.isPending}
              icon={<Wand2 className="size-5" />} disabled={!hasInput || !valid || uploading || recInPost}>
              {uploading ? "Uploading…" : kind === "post" ? "Create post"
                : length === "series" ? "Create series" : outline ? "Create outline" : "Create video"}
            </Button>
          </form>
        </Card>

        <div className="space-y-6">
          <Card className="p-4 sm:p-6">
            <h2 className="font-bold">How it works</h2>
            <ol className="mt-4 space-y-4">
              {[
                [ScanSearch, "Reads the website", "Main pages, product screens and what the business does."],
                [Palette, "Uses its brand", "Name, tagline and colours taken from the site itself."],
                [Sparkles, "Designs the content", "Storyboard or poster by the AI art director – fresh every time."],
                [ArrowRight, "Waits for your OK", "It lands in the queue for review. Nothing is posted until you approve."],
              ].map(([Icon, t, d], i) => {
                const I = Icon as typeof Globe;
                return (
                  <li key={i} className="flex gap-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-stone-100 text-stone-600"><I className="size-4" /></span>
                    <span><span className="block text-sm font-semibold">{t as string}</span><span className="block text-xs text-stone-500">{d as string}</span></span>
                  </li>
                );
              })}
            </ol>
          </Card>

          <Card className="p-4 sm:p-6">
            <h2 className="font-bold">Recently created here</h2>
            {fromLinks.length === 0 ? (
              <p className="mt-2 text-sm text-stone-400">Nothing yet – your first one will show up here.</p>
            ) : (
              <ul className="mt-3 divide-y divide-stone-100">
                {fromLinks.map((i) => (
                  <li key={i.id}>
                    <Link to={`/items/${i.id}`} className="flex items-center gap-3 py-2.5 hover:opacity-80">
                      <div className="size-11 shrink-0 overflow-hidden rounded-lg bg-stone-100">
                        {i.thumb && i.status !== "generating" ? <img src={i.thumb} className="size-full object-cover" alt="" /> : null}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold">{displayTitle(i)}</div>
                        <div className="text-xs text-stone-400">{i.kind} · {ago(i.created_at)}</div>
                      </div>
                      <StatusBadge status={i.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
