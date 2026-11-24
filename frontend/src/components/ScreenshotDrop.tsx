// Optional screenshots for "Create from URL": drag & drop / pick / paste, uploaded right away, each with a caption.
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ImagePlus, Loader2, X } from "lucide-react";
import { api } from "../lib/api";
import { useToast } from "./ui";

export interface Shot { id: string; preview: string; ref?: string; caption: string; error?: string }

export default function ScreenshotDrop({ shots, onChange, max = 8 }: { shots: Shot[]; onChange: (s: Shot[]) => void; max?: number }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const latest = useRef(shots);
  latest.current = shots;
  const set = (fn: (s: Shot[]) => Shot[]) => onChange(fn(latest.current));

  const add = (files: FileList | File[]) => {
    const imgs = Array.from(files).filter((f) => f.type.startsWith("image/"));
    const room = max - latest.current.length;
    if (imgs.length > room) toast("error", `Up to ${max} screenshots`);
    for (const file of imgs.slice(0, Math.max(0, room))) {
      if (file.size > 10_000_000) { toast("error", `${file.name} is over 10 MB`); continue; }
      const id = Math.random().toString(36).slice(2);
      const caption = file.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").replace(/^(screenshot|screen shot|image|img)\s*[\d\s:.at-]*/i, "").trim().slice(0, 80);
      set((s) => [...s, { id, preview: URL.createObjectURL(file), caption }]);
      api.uploadScreenshot(file)
        .then((r) => set((s) => s.map((x) => (x.id === id ? { ...x, ref: r.ref } : x))))
        .catch((e: Error) => {
          toast("error", e.message);
          set((s) => s.filter((x) => x.id !== id));
        });
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
  }, [max]);

  return (
    <div className="mt-2 space-y-2">
      {shots.length > 0 && (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {shots.map((s, i) => (
            <li key={s.id} className="flex items-center gap-2 rounded-xl bg-white p-2 ring-1 ring-stone-200">
              <div className="relative h-14 w-20 shrink-0 overflow-hidden rounded-lg bg-stone-100">
                <img src={s.preview} alt="" className="size-full object-cover object-top" />
                {!s.ref && <span className="absolute inset-0 grid place-items-center bg-white/60"><Loader2 className="size-4 animate-spin text-stone-600" /></span>}
              </div>
              <input value={s.caption} maxLength={200} placeholder={`What does screen ${i + 1} show?`}
                onChange={(e) => set((all) => all.map((x) => (x.id === s.id ? { ...x, caption: e.target.value } : x)))}
                className="min-w-0 flex-1 rounded-lg bg-stone-50 px-2.5 py-2 text-xs outline-none ring-1 ring-stone-200 focus:bg-white focus:ring-ink-900" />
              <button type="button" onClick={() => set((all) => all.filter((x) => x.id !== s.id))} title="Remove"
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
          <ImagePlus className="size-6 text-stone-400" />
          <span className="text-sm font-semibold text-stone-700">Drop screenshots, click to choose, or paste (Ctrl+V)</span>
          <span className="text-xs text-stone-400">PNG or JPG · up to {max} · {shots.length ? `${max - shots.length} more` : "optional"}</span>
        </button>
      )}
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden
        onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
    </div>
  );
}
