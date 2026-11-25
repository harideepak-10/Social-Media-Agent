// Optional screenshots and screen recordings for "Create from URL": drag & drop / pick / paste, uploaded right away,
// each with a caption. Recordings are cut into moving clips by the PC that makes the video.
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Film, ImagePlus, Loader2, X } from "lucide-react";
import { api } from "../lib/api";
import { useToast } from "./ui";

export interface Shot { id: string; preview: string; ref?: string; caption: string; video?: boolean; seconds?: number; progress?: number }

const REC_MAX_MB = 600;
const REC_MAX_S = 300;
const REC_MAX = 5;
const isVideo = (f: File) => f.type.startsWith("video/") || /\.(mp4|mov|webm|mkv)$/i.test(f.name);

function videoSeconds(url: string): Promise<number> {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => resolve(Number.isFinite(v.duration) ? v.duration : 0);
    v.onerror = () => resolve(0);  // e.g. a .mkv the browser can't read – the server checks it
    v.src = url;
  });
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export default function ScreenshotDrop({ shots, onChange, max = 8, allowVideo = true }: {
  shots: Shot[]; onChange: (s: Shot[]) => void; max?: number; allowVideo?: boolean;
}) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const latest = useRef(shots);
  latest.current = shots;
  const set = (fn: (s: Shot[]) => Shot[]) => onChange(fn(latest.current));
  const patch = (id: string, p: Partial<Shot>) => set((s) => s.map((x) => (x.id === id ? { ...x, ...p } : x)));
  const drop = (id: string) => set((s) => s.filter((x) => x.id !== id));

  const add = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => f.type.startsWith("image/") || (allowVideo && isVideo(f)));
    if (list.length < Array.from(files).length) toast("error", allowVideo ? "Only images and screen recordings" : "Only images for a post – recordings are for videos");
    for (const file of list) {
      const video = isVideo(file);
      if (latest.current.length >= max) { toast("error", `Up to ${max} files`); break; }
      if (video && latest.current.filter((s) => s.video).length >= REC_MAX) { toast("error", `Up to ${REC_MAX} screen recordings`); continue; }
      if (!video && file.size > 10_000_000) { toast("error", `${file.name} is over 10 MB`); continue; }
      if (video && file.size > REC_MAX_MB * 1_000_000) { toast("error", `${file.name} is over ${REC_MAX_MB} MB – trim it or record a smaller window`); continue; }
      const preview = URL.createObjectURL(file);
      let seconds: number | undefined;
      if (video) {
        seconds = await videoSeconds(preview);
        if (seconds > REC_MAX_S + 5) { toast("error", `${file.name} is ${mmss(seconds)} long – recordings can be up to ${REC_MAX_S / 60} minutes`); continue; }
      }
      const id = Math.random().toString(36).slice(2);
      const caption = file.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ")
        .replace(/^(screenshot|screen shot|screen recording|recording|image|img|video)\s*[\d\s:.at-]*/i, "").trim().slice(0, 80);
      set((s) => [...s, { id, preview, caption, video, seconds, progress: video ? 0 : undefined }]);
      const up = video
        ? api.uploadRecording(file, (pct) => patch(id, { progress: pct })).then((r) => ({ ref: r.ref }))
        : api.uploadScreenshot(file).then((r) => ({ ref: r.ref }));
      up.then((r) => patch(id, { ref: r.ref, progress: undefined }))
        .catch((e: Error) => { toast("error", e.message); drop(id); });
    }
  };

  // paste a screenshot straight from the clipboard (Win+Shift+S, then Ctrl+V)
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith("image/"));
      if (files.length) { e.preventDefault(); add(files); }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [max, allowVideo]);

  return (
    <div className="mt-2 space-y-2">
      {shots.length > 0 && (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {shots.map((s, i) => (
            <li key={s.id} className={clsx("flex items-center gap-2 rounded-xl bg-white p-2 ring-1", s.video && !allowVideo ? "ring-red-300" : "ring-stone-200")}>
              <div className="relative h-14 w-20 shrink-0 overflow-hidden rounded-lg bg-stone-900">
                {s.video
                  ? <video src={s.preview} muted playsInline preload="metadata" className="size-full object-cover object-top"
                      onMouseEnter={(e) => e.currentTarget.play().catch(() => null)} onMouseLeave={(e) => e.currentTarget.pause()} />
                  : <img src={s.preview} alt="" className="size-full object-cover object-top" />}
                {s.video && <span className="absolute bottom-0.5 left-0.5 inline-flex items-center gap-0.5 rounded bg-black/70 px-1 text-[10px] font-semibold text-white"><Film className="size-2.5" />{s.seconds ? mmss(s.seconds) : "video"}</span>}
                {!s.ref && (
                  <span className="absolute inset-0 grid place-items-center bg-white/70 text-[11px] font-bold text-stone-700">
                    {s.progress !== undefined ? `${s.progress}%` : <Loader2 className="size-4 animate-spin" />}
                  </span>
                )}
              </div>
              <input value={s.caption} maxLength={200}
                placeholder={s.video ? `What happens in recording ${i + 1}?` : `What does screen ${i + 1} show?`}
                onChange={(e) => patch(s.id, { caption: e.target.value })}
                className="min-w-0 flex-1 rounded-lg bg-stone-50 px-2.5 py-2 text-xs outline-none ring-1 ring-stone-200 focus:bg-white focus:ring-ink-900" />
              <button type="button" onClick={() => drop(s.id)} title="Remove"
                className="grid size-8 shrink-0 place-items-center rounded-lg text-stone-400 hover:bg-stone-100 hover:text-stone-700">
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {shots.length < max && (
        <button type="button" onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
          className={clsx("flex w-full flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-5 text-center transition",
            over ? "border-brand-600 bg-brand-50" : "border-stone-200 bg-stone-50 hover:border-stone-300")}>
          <span className="flex items-center gap-2 text-stone-400"><ImagePlus className="size-6" />{allowVideo && <Film className="size-6" />}</span>
          <span className="text-sm font-semibold text-stone-700">
            {allowVideo ? "Drop screenshots or screen recordings, click to choose, or paste (Ctrl+V)" : "Drop screenshots, click to choose, or paste (Ctrl+V)"}
          </span>
          <span className="text-xs text-stone-400">
            PNG or JPG{allowVideo ? ` · recordings: MP4, MOV or WebM, up to ${REC_MAX_S / 60} min / ${REC_MAX_MB} MB (max ${REC_MAX})` : ""} · {shots.length ? `${max - shots.length} more` : "optional"}
          </span>
        </button>
      )}
      <input ref={input} type="file" multiple hidden
        accept={allowVideo ? "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,.mkv" : "image/png,image/jpeg,image/webp"}
        onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
    </div>
  );
}
