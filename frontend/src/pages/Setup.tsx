import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, ArrowRight, Building2, CalendarDays, Check, Globe, ImagePlus, Link2, Package, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { api, WEEKDAYS, type Kind, type Product, type Settings, type Weekday } from "../lib/api";
import { Button, Card, Field, inputCls, useToast } from "../components/ui";

const STEPS = [
  { id: "company", label: "Company", icon: Building2 },
  { id: "logo", label: "Logo", icon: ImagePlus },
  { id: "products", label: "Products", icon: Package },
  { id: "schedule", label: "Schedule", icon: CalendarDays },
  { id: "connect", label: "Connect", icon: Link2 },
] as const;

const PRESETS: { id: string; label: string; sub: string; plan: Record<Weekday, Kind> }[] = [
  { id: "light", label: "Light", sub: "3 posts a week", plan: { monday: "post", tuesday: "none", wednesday: "post", thursday: "none", friday: "post", saturday: "none", sunday: "none" } },
  { id: "balanced", label: "Balanced", sub: "4 posts + 1 video", plan: { monday: "video", tuesday: "post", wednesday: "post", thursday: "post", friday: "post", saturday: "none", sunday: "none" } },
  { id: "active", label: "Active", sub: "4 posts + 2 videos", plan: { monday: "video", tuesday: "post", wednesday: "post", thursday: "video", friday: "post", saturday: "post", sunday: "none" } },
];

type Company = Settings["company"];

export default function Setup() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const { data: schedule } = useQuery({ queryKey: ["schedule"], queryFn: api.schedule });
  const [company, setCompany] = useState<Company>({});
  const [products, setProducts] = useState<Product[]>([]);
  const [suggested, setSuggested] = useState<Product[]>([]);
  const [plan, setPlan] = useState<Record<Weekday, Kind> | null>(null);
  const [times, setTimes] = useState({ generate_time: "18:00", publish_time: "10:00" });
  useEffect(() => { if (settings) { setCompany(settings.company); setProducts(settings.products); } }, [settings]);
  useEffect(() => { if (schedule) { setPlan(schedule.schedule); setTimes({ generate_time: schedule.generate_time, publish_time: schedule.publish_time }); } }, [schedule]);

  const analyze = useMutation({
    mutationFn: () => api.setupAnalyze(company.website ?? ""),
    onSuccess: (r) => {
      setCompany((c) => ({ ...c, ...Object.fromEntries(Object.entries(r.company).filter(([, v]) => v)), brand_colors: { ...c.brand_colors, ...r.brand_colors } }));
      setSuggested(r.products);
      toast("ok", `Read ${r.company.name || "the website"}${r.products.length ? ` – found ${r.products.length} product${r.products.length === 1 ? "" : "s"}` : ""}. Check the details.`);
    },
    onError: (e: Error) => toast("error", e.message),
  });
  const saveCompany = useMutation({ mutationFn: () => api.saveSettings({ company }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["meta"] }); setStep(1); }, onError: (e: Error) => toast("error", e.message) });
  const saveProducts = useMutation({ mutationFn: () => api.saveSettings({ products: products.filter((p) => p.name.trim().length >= 2).map((p) => ({ ...p, name: p.name.trim() })) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); setStep(3); }, onError: (e: Error) => toast("error", e.message) });
  const saveSchedule = useMutation({ mutationFn: () => api.saveSchedule({ schedule: plan!, ...times }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["schedule"] }); qc.invalidateQueries({ queryKey: ["meta"] }); setStep(4); }, onError: (e: Error) => toast("error", e.message) });
  // mark setup as done *before* leaving – otherwise the app still thinks it isn't and sends you back here
  const markDone = async () => {
    await api.setupFinish();
    qc.setQueryData(["meta"], (m: Record<string, unknown> | undefined) => (m ? { ...m, setup_done: true } : m));
    await qc.invalidateQueries({ queryKey: ["meta"] });
  };
  const finish = useMutation({
    mutationFn: async (first: boolean) => { await markDone(); if (first) await api.generate("post"); return first; },
    onSuccess: (first) => { toast("ok", first ? "All set – your first post is being made" : "All set!"); nav("/"); },
    onError: (e: Error) => toast("error", e.message),
  });
  const skip = useMutation({ mutationFn: markDone, onSuccess: () => nav("/"), onError: (e: Error) => toast("error", e.message) });

  const setC = (k: keyof Company, v: string) => setCompany((c) => ({ ...c, [k]: v }));
  const validCompany = (company.name ?? "").trim().length >= 2 && /^https?:\/\//.test(company.website ?? "");

  return (
    <div className="mx-auto max-w-3xl px-5 py-8 md:px-10">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Set up your agent</h1>
        <button onClick={() => skip.mutate()} disabled={skip.isPending} className="text-sm font-medium text-stone-500 hover:text-stone-900 disabled:opacity-50">
          {skip.isPending ? "Skipping…" : "Skip for now"}
        </button>
      </div>
      <p className="mt-1 text-sm text-stone-500">Five short steps. You can change everything later in Settings.</p>

      <ol className="mt-6 flex gap-1.5" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s.id} className="flex-1">
            <button onClick={() => i < step && setStep(i)} disabled={i > step} aria-current={i === step ? "step" : undefined}
              className={clsx("flex w-full flex-col items-center gap-1 rounded-xl px-1 py-2 text-[11px] font-semibold sm:flex-row sm:justify-center sm:gap-2 sm:text-sm",
                i === step ? "bg-ink-900 text-white" : i < step ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100" : "bg-white text-stone-400 ring-1 ring-stone-200")}>
              {i < step ? <Check className="size-4" /> : <s.icon className="size-4" />}{s.label}
            </button>
          </li>
        ))}
      </ol>

      <Card className="mt-6 p-4 sm:p-6">
        {step === 0 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">Your company</h2>
            <Field label="Website">
              <div className="flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <Globe className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-stone-400" />
                  <input value={company.website ?? ""} onChange={(e) => setC("website", e.target.value)} placeholder="https://www.yourcompany.com" className={clsx(inputCls, "pl-9")} />
                </div>
                <Button variant="dark" icon={<Sparkles className="size-4" />} loading={analyze.isPending} disabled={(company.website ?? "").length < 4} onClick={() => analyze.mutate()}>
                  <span className="hidden sm:inline">Read my website</span><span className="sm:hidden">Read</span>
                </Button>
              </div>
            </Field>
            <p className="-mt-2 text-xs text-stone-500">The AI reads your site and fills in the details below (about 30 seconds). Then check them.</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Company name"><input value={company.name ?? ""} onChange={(e) => setC("name", e.target.value)} className={inputCls} /></Field>
              <Field label="Tagline"><input value={company.tagline ?? ""} onChange={(e) => setC("tagline", e.target.value)} className={inputCls} /></Field>
              <Field label="What you do"><input value={company.industry ?? ""} onChange={(e) => setC("industry", e.target.value)} className={inputCls} /></Field>
              <Field label="Your customers"><input value={company.audience ?? ""} onChange={(e) => setC("audience", e.target.value)} className={inputCls} /></Field>
              <Field label="Tone of voice"><input value={company.tone ?? ""} onChange={(e) => setC("tone", e.target.value)} className={inputCls} /></Field>
              <Field label="Call to action"><input value={company.call_to_action ?? ""} onChange={(e) => setC("call_to_action", e.target.value)} placeholder="Book a free demo at …" className={inputCls} /></Field>
            </div>
            <div>
              <div className="text-sm font-semibold">Brand colours</div>
              <div className="mt-2 flex flex-wrap gap-4">
                {(["primary", "secondary", "text"] as const).map((k) => (
                  <label key={k} className="flex items-center gap-2 text-sm capitalize">
                    <input type="color" value={company.brand_colors?.[k] ?? "#c8372d"} onChange={(e) => setCompany((c) => ({ ...c, brand_colors: { ...c.brand_colors, [k]: e.target.value } }))}
                      className="size-9 cursor-pointer rounded-lg border-0 bg-transparent p-0" />{k}
                  </label>
                ))}
              </div>
            </div>
            <Nav next={() => saveCompany.mutate()} nextLabel="Save & continue" disabled={!validCompany} loading={saveCompany.isPending}
              hint={!validCompany ? "Add the company name and a website starting with https://" : undefined} />
          </div>
        )}

        {step === 1 && <LogoStep onBack={() => setStep(0)} onNext={() => setStep(2)} />}

        {step === 2 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">Products & services</h2>
            <p className="text-sm text-stone-500">The agent features them in turn. Videos show the page you link for each one.</p>
            {suggested.filter((s) => !products.some((p) => p.name.toLowerCase() === s.name.toLowerCase())).length > 0 && (
              <div className="rounded-xl bg-amber-50 p-3 ring-1 ring-amber-200">
                <div className="text-sm font-semibold text-amber-900">Found on your website – tap to add</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {suggested.filter((s) => !products.some((p) => p.name.toLowerCase() === s.name.toLowerCase())).map((s) => (
                    <button key={s.name} onClick={() => setProducts((p) => [...p, s])} title={s.description}
                      className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-sm font-medium ring-1 ring-amber-300 hover:bg-amber-100"><Plus className="size-3.5" />{s.name}</button>
                  ))}
                </div>
              </div>
            )}
            <ul className="space-y-2">
              {products.map((p, i) => (
                <li key={i} className="space-y-2 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
                  <div className="flex gap-2">
                    <input value={p.name} onChange={(e) => setProducts((l) => l.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} placeholder="Product name" className={clsx(inputCls, "bg-white font-semibold")} />
                    <button onClick={() => setProducts((l) => l.filter((_, j) => j !== i))} aria-label="Remove" className="rounded-lg p-2 text-stone-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-4" /></button>
                  </div>
                  <input value={p.url} onChange={(e) => setProducts((l) => l.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))} placeholder="https://… product page" className={clsx(inputCls, "bg-white")} />
                  <textarea rows={2} value={p.description} onChange={(e) => setProducts((l) => l.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} placeholder="What it does and for whom" className={clsx(inputCls, "resize-none bg-white")} />
                </li>
              ))}
            </ul>
            <Button icon={<Plus className="size-4" />} onClick={() => setProducts((l) => [...l, { name: "", url: company.website ?? "", description: "" }])}>Add product</Button>
            <Nav back={() => setStep(1)} next={() => saveProducts.mutate()} nextLabel="Save & continue" loading={saveProducts.isPending}
              disabled={!products.some((p) => p.name.trim().length >= 2)} hint={!products.length ? "Add at least one product or service" : undefined} />
          </div>
        )}

        {step === 3 && plan && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">How often to post</h2>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {PRESETS.map((p) => {
                const on = WEEKDAYS.every((d) => plan[d] === p.plan[d]);
                return (
                  <button key={p.id} onClick={() => setPlan(p.plan)}
                    className={clsx("rounded-xl p-3 text-left ring-1", on ? "bg-brand-50 ring-2 ring-brand-500" : "ring-stone-200 hover:bg-stone-50")}>
                    <div className="font-semibold">{p.label}</div><div className="text-xs text-stone-500">{p.sub}</div>
                  </button>
                );
              })}
            </div>
            <div className="grid grid-cols-7 gap-1 text-center text-[11px]">
              {WEEKDAYS.map((d) => (
                <button key={d} onClick={() => setPlan({ ...plan, [d]: plan[d] === "post" ? "video" : plan[d] === "video" ? "none" : "post" })}
                  className={clsx("rounded-lg py-2 font-semibold", plan[d] === "video" ? "bg-pink-600 text-white" : plan[d] === "post" ? "bg-sky-600 text-white" : "bg-stone-100 text-stone-400")}>
                  {d.slice(0, 3)}<span className="block text-[10px] font-normal opacity-80">{plan[d] === "none" ? "off" : plan[d]}</span>
                </button>
              ))}
            </div>
            <p className="text-xs text-stone-500">Tap a day to switch post → video → off.</p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Prepare (day before)"><input type="time" value={times.generate_time} onChange={(e) => setTimes({ ...times, generate_time: e.target.value })} className={inputCls} /></Field>
              <Field label="Post at"><input type="time" value={times.publish_time} onChange={(e) => setTimes({ ...times, publish_time: e.target.value })} className={inputCls} /></Field>
            </div>
            <Nav back={() => setStep(2)} next={() => saveSchedule.mutate()} nextLabel="Save & continue" loading={saveSchedule.isPending} />
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">Connect your accounts</h2>
            <p className="text-sm text-stone-600">
              Until LinkedIn, Facebook and Instagram are connected, the agent runs in <b>test mode</b>: it prepares everything and you can review it, but nothing is posted.
              You can connect now or any time later.
            </p>
            <Link to="/settings?tab=connections" className="block">
              <Button className="w-full" icon={<Link2 className="size-4" />}>Open Connections (LinkedIn, Facebook, Instagram)</Button>
            </Link>
            <div className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900 ring-1 ring-emerald-200">
              <b>You're ready.</b> The agent prepares content every evening at {times.generate_time} for your approval.
            </div>
            <div className="flex flex-col gap-2 sm:flex-row-reverse">
              <Button variant="primary" icon={<Sparkles className="size-4" />} loading={finish.isPending && finish.variables} onClick={() => finish.mutate(true)}>Finish & make my first post</Button>
              <Button variant="outline" loading={finish.isPending && !finish.variables} onClick={() => finish.mutate(false)}>Finish</Button>
              <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={() => setStep(3)} className="sm:mr-auto">Back</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function Nav({ back, next, nextLabel, disabled, loading, hint }: { back?: () => void; next: () => void; nextLabel: string; disabled?: boolean; loading?: boolean; hint?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-stone-100 pt-4">
      {back && <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={back}>Back</Button>}
      <span className="flex-1 text-xs text-stone-500">{hint}</span>
      <Button variant="primary" disabled={disabled} loading={loading} onClick={next}>{nextLabel} <ArrowRight className="size-4" /></Button>
    </div>
  );
}

function LogoStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: assets } = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const upload = useMutation({
    mutationFn: (f: File) => api.uploadLogo(f),
    onSuccess: (a) => { qc.setQueryData(["assets"], a); toast("ok", "Logo saved"); },
    onError: (e: Error) => toast("error", e.message),
  });
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold">Your logo</h2>
      <p className="text-sm text-stone-500">A PNG with a transparent background works best. Light and dark versions are made automatically – it goes on every post and video.</p>
      <div className="flex flex-wrap items-center gap-4">
        <div className="grid h-24 w-48 place-items-center rounded-xl bg-[repeating-conic-gradient(#f5f5f4_0%_25%,#fff_0%_50%)] bg-[length:16px_16px] ring-1 ring-stone-200">
          {assets?.logo ? <img src={assets.logo} alt="Your logo" className="max-h-20 max-w-44 object-contain" /> : <span className="text-xs text-stone-400">No logo yet</span>}
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-ink-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-black">
          <Upload className="size-4" /> {upload.isPending ? "Uploading…" : assets?.logo ? "Replace logo" : "Upload logo"}
          <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" className="sr-only" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
        </label>
      </div>
      <p className="text-xs text-stone-500">No logo? The agent tries to take it from your website, which is slower and less reliable.</p>
      <Nav back={onBack} next={onNext} nextLabel={assets?.logo ? "Continue" : "Skip for now"} />
    </div>
  );
}
