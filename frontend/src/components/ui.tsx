import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import { CheckCircle2, Loader2, X, XCircle } from "lucide-react";
import type { Status } from "../lib/api";
import { STATUS } from "../lib/ui";

// ── Button ─────────────────────────────────────────────────────────────────
type Variant = "primary" | "dark" | "success" | "danger" | "ghost" | "outline";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm shadow-brand-600/20",
  dark: "bg-ink-900 text-white hover:bg-black",
  success: "bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm shadow-emerald-600/20",
  danger: "bg-white text-red-600 ring-1 ring-red-200 hover:bg-red-50",
  ghost: "text-stone-600 hover:bg-stone-100",
  outline: "bg-white text-stone-800 ring-1 ring-stone-200 hover:bg-stone-50",
};

export function Button({ variant = "outline", loading, icon, className, children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-semibold transition",
        "disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-900",
        VARIANTS[variant], className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ── Status badge / progress ────────────────────────────────────────────────
export function StatusBadge({ status, className }: { status: Status; className?: string }) {
  const s = STATUS[status] ?? STATUS.rejected;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1", s.cls, className)}>
      <span className={clsx("size-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={clsx("h-1.5 w-full overflow-hidden rounded-full bg-stone-200", className)}>
      <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-amber-500 transition-all duration-700"
        style={{ width: `${Math.max(3, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-2xl bg-white ring-1 ring-stone-200/80 shadow-[0_1px_2px_rgba(0,0,0,.04)]", className)}>{children}</div>;
}

export function Chip({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex items-center gap-1 rounded-md bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-600", className)}>{children}</span>;
}

// ── Confirm dialog ─────────────────────────────────────────────────────────
export function Confirm({ open, title, body, confirmLabel, variant = "primary", onConfirm, onClose }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; variant?: Variant;
  onConfirm: () => void; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid items-end justify-items-center bg-black/40 backdrop-blur-[2px] sm:place-items-center sm:p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-t-2xl bg-white p-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] shadow-2xl sm:rounded-2xl sm:pb-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold">{title}</h3>
        <div className="mt-2 text-sm text-stone-600">{body}</div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant={variant} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Toasts ─────────────────────────────────────────────────────────────────
type Toast = { id: number; kind: "ok" | "error"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-50 flex flex-col items-stretch gap-2 md:inset-x-auto md:bottom-5 md:right-5 md:items-end">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto flex max-w-sm items-start gap-3 rounded-xl bg-ink-900 px-4 py-3 text-sm text-white shadow-xl">
            {t.kind === "ok" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-400" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-400" />}
            <span className="flex-1">{t.text}</span>
            <button onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} className="text-white/50 hover:text-white"><X className="size-4" /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white/60 px-6 py-16 text-center">
      <div className="grid size-12 place-items-center rounded-xl bg-brand-50 text-brand-600">{icon}</div>
      <h3 className="mt-4 font-bold">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-stone-500">{text}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// ── Form bits ──────────────────────────────────────────────────────────────
export function Switch({ checked, onChange, label, sub, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; sub?: ReactNode; disabled?: boolean;
}) {
  return (
    <label className={clsx("flex cursor-pointer items-start justify-between gap-4", disabled && "cursor-not-allowed opacity-60")}>
      {(label || sub) && (
        <span className="min-w-0">
          {label && <span className="block text-sm font-semibold text-stone-800">{label}</span>}
          {sub && <span className="mt-0.5 block text-xs text-stone-500">{sub}</span>}
        </span>
      )}
      <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className={clsx("relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition", checked ? "bg-emerald-500" : "bg-stone-300")}>
        <span className={clsx("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", checked ? "left-[22px]" : "left-0.5")} />
      </button>
    </label>
  );
}

export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={clsx("block", className)}>
      <span className="text-sm font-semibold text-stone-800">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1 block text-xs text-stone-400">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg bg-stone-50 px-3 py-2.5 text-sm outline-none ring-1 ring-stone-200 transition focus:bg-white focus:ring-2 focus:ring-ink-900 disabled:opacity-60";

export function SaveBar({ dirty, saving, onSave, onDiscard, label }: {
  dirty: boolean; saving: boolean; onSave: () => void; onDiscard: () => void; label?: string;
}) {
  if (!dirty) return null;
  return (
    <div className="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-10 mt-6 md:bottom-4 flex items-center justify-between gap-3 rounded-2xl bg-ink-900 px-5 py-3 text-white shadow-xl">
      <span className="text-sm">{label ?? "You have unsaved changes"}</span>
      <div className="flex gap-2">
        <Button variant="ghost" className="text-white/70 hover:bg-white/10 hover:text-white" onClick={onDiscard}>Discard</Button>
        <Button variant="primary" loading={saving} onClick={onSave}>Save changes</Button>
      </div>
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid items-end justify-items-center bg-black/40 backdrop-blur-[2px] sm:place-items-center sm:p-4" onClick={onClose}>
      <div className="flex max-h-[92dvh] w-full max-w-lg flex-col rounded-t-2xl bg-white shadow-2xl sm:max-h-[90vh] sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex shrink-0 items-center justify-between border-b border-stone-100 px-5 py-4 sm:px-6">
          <h3 className="text-lg font-bold">{title}</h3>
          <button onClick={onClose} aria-label="Close" className="-mr-1 grid size-9 place-items-center text-stone-400 hover:text-stone-800"><X className="size-5" /></button>
        </div>
        <div className="min-h-0 overflow-y-auto px-5 py-5 sm:px-6">{children}</div>
        {footer && <div className="flex shrink-0 justify-end gap-2 border-t border-stone-100 px-5 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:px-6 sm:pb-4">{footer}</div>}
      </div>
    </div>
  );
}

/** Shown while the free backend is waking up (see fetchWithWake in lib/api.ts). */
export function WakeBanner() {
  const [on, setOn] = useState(false);
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const h = (e: Event) => { setOn((e as CustomEvent<boolean>).detail); setSecs(0); };
    window.addEventListener("dma:waking", h);
    return () => window.removeEventListener("dma:waking", h);
  }, []);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [on]);
  if (!on) return null;
  return (
    <div className="fixed inset-x-0 top-0 z-[60] flex justify-center p-3">
      <div className="flex items-center gap-3 rounded-full bg-ink-900 px-5 py-2.5 text-sm text-white shadow-xl">
        <Loader2 className="size-4 animate-spin text-amber-400" />
        Waking up the server… free hosting sleeps when idle · {secs}s
      </div>
    </div>
  );
}
