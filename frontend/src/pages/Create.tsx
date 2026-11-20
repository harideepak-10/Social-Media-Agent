import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Film, Globe, ImageIcon, Palette, ScanSearch, Sparkles, Wand2 } from "lucide-react";
import { api } from "../lib/api";
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

  const cleaned = url.trim();
  const valid = /^(https?:\/\/)?([\w-]+\.)+[\w-]{2,}(\/\S*)?$/i.test(cleaned) || /^(https?:\/\/)?localhost(:\d+)?(\/\S*)?$/i.test(cleaned);

  const recent = useQuery({ queryKey: ["items", "recent-url"], queryFn: () => api.items({ q: "", limit: 60 }), refetchInterval: 10000 });
  const fromLinks = (recent.data?.items ?? []).filter((i) => i.source_url).slice(0, 6);

  const create = useMutation({
    mutationFn: () => api.fromUrl(cleaned, kind, notes),
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
      <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Create from any website</h1>
      <p className="mt-1 text-sm text-stone-500">Paste a link. The agent reads the site, takes its brand colours and best screens, and makes a video or post for it.</p>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="p-4 sm:p-6 md:p-8">
          <form onSubmit={(e) => { e.preventDefault(); setTouched(true); if (valid) create.mutate(); }} className="space-y-7">
            <div>
              <label className="text-sm font-bold">Website link</label>
              <div className={clsx("mt-2 flex items-center gap-3 rounded-xl bg-stone-50 px-4 py-3 ring-1 transition focus-within:bg-white focus-within:ring-2",
                touched && cleaned && !valid ? "ring-red-300 focus-within:ring-red-500" : "ring-stone-200 focus-within:ring-ink-900")}>
                <Globe className="size-5 shrink-0 text-stone-400" />
                <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} onBlur={() => setTouched(true)}
                  placeholder="https://www.krypsos.tech/restaurant-pos/" inputMode="url"
                  className="w-full bg-transparent text-base outline-none placeholder:text-stone-400" />
              </div>
              {touched && cleaned && !valid && <p className="mt-1.5 text-xs text-red-600">That doesn't look like a website link.</p>}
              <p className="mt-1.5 text-xs text-stone-400">Tip: link straight to a product page for the best screens. Sites that need a login: run <code className="rounded bg-stone-100 px-1">python cli.py login --url …</code> once.</p>
            </div>

            <div>
              <label className="text-sm font-bold">What should it make?</label>
              <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {([
                  ["video", Film, "Promo video", "16:9 + 9:16 with voice-over and music · about 5 min"],
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

            <div>
              <label className="text-sm font-bold">Focus <span className="font-normal text-stone-400">(optional)</span></label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={400}
                placeholder="e.g. explain the booking feature, aimed at clinic owners"
                className="mt-2 w-full resize-none rounded-xl bg-stone-50 p-4 text-sm outline-none ring-1 ring-stone-200 focus:bg-white focus:ring-2 focus:ring-ink-900" />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {IDEAS.map((idea) => (
                  <button type="button" key={idea} onClick={() => setNotes(idea)}
                    className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600 hover:bg-stone-200">{idea}</button>
                ))}
              </div>
            </div>

            <Button type="submit" variant="primary" className="w-full py-3 text-base" loading={create.isPending}
              icon={<Wand2 className="size-5" />} disabled={!cleaned}>
              Create {kind === "video" ? "video" : "post"}
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
            <h2 className="font-bold">Recent from links</h2>
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
