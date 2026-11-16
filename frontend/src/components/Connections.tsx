import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Copy, ExternalLink, KeyRound, Link2, LogIn, Plug, RefreshCw, Unplug, XCircle } from "lucide-react";
import { api, type Connections as TConn } from "../lib/api";
import { Button, Card, Confirm, Field, Modal, inputCls, useToast } from "./ui";

type P = "meta" | "linkedin";

function BrandIcon({ kind, size = 40 }: { kind: "facebook" | "instagram" | "linkedin"; size?: number }) {
  const style = { width: size, height: size };
  if (kind === "instagram")
    return <span style={{ ...style, background: "radial-gradient(circle at 30% 107%, #fdf497 0%, #fd5949 45%, #d6249f 60%, #285AEB 90%)" }}
      className="grid shrink-0 place-items-center rounded-xl text-white"><svg viewBox="0 0 24 24" width={size * .55} height={size * .55} fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="5" /><circle cx="12" cy="12" r="4" /><circle cx="17.5" cy="6.5" r="1" fill="currentColor" /></svg></span>;
  return <span style={{ ...style, background: kind === "facebook" ? "#1877F2" : "#0A66C2" }}
    className="grid shrink-0 place-items-center rounded-xl font-extrabold text-white" >{kind === "facebook" ? <span style={{ fontSize: size * .6, lineHeight: 1 }}>f</span> : <span style={{ fontSize: size * .42 }}>in</span>}</span>;
}

function useConnMutation<T>(fn: (v: T) => Promise<TConn | unknown>, ok?: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: (d) => {
      if (d && typeof d === "object" && "meta" in (d as object)) qc.setQueryData(["connections"], d);
      qc.invalidateQueries({ queryKey: ["connections"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
      if (ok) toast("ok", ok);
    },
    onError: (e: Error) => toast("error", e.message),
  });
}

export default function ConnectionsTab() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const { data, isLoading } = useQuery({ queryKey: ["connections"], queryFn: api.connections });

  // back from Facebook / LinkedIn login
  useEffect(() => {
    const result = params.get("result");
    if (!result) return;
    const name = params.get("platform") === "meta" ? "Facebook & Instagram" : "LinkedIn";
    if (result === "ok") toast("ok", `${name} connected`);
    else if (result === "choose") toast("ok", "Logged in – now pick the Page to post to");
    else toast("error", `${name}: ${params.get("msg") || "connection failed"}`);
    setParams({ tab: "connections" }, { replace: true });
  }, [params, setParams, toast]);

  if (isLoading || !data) return <div className="shimmer h-96 rounded-2xl bg-stone-200/60" />;
  const localUrl = /localhost|127\.0\.0\.1/.test(data.public_url);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl bg-white p-5 text-sm text-stone-600 ring-1 ring-stone-200/80">
        Connect your company accounts so approved content is posted for real. Until a platform is connected, it runs in <b>test mode</b> (marked as published, nothing is posted).
        Tokens are stored encrypted on your server.
        {localUrl && (
          <div className="mt-3 flex gap-2 rounded-xl bg-amber-50 p-3 text-amber-900 ring-1 ring-amber-200">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span><b>PUBLIC_BASE_URL is {data.public_url}.</b> Login with Facebook/LinkedIn and Instagram posting need your public address (e.g. your Render URL) – set it in the environment settings first.</span>
          </div>
        )}
      </div>
      <MetaCard c={data} />
      <LinkedInCard c={data} />
    </div>
  );
}

// ── Facebook + Instagram ───────────────────────────────────────────────────
function MetaCard({ c }: { c: TConn }) {
  const m = c.meta;
  const [appOpen, setAppOpen] = useState(false);
  const [manual, setManual] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const start = useConnMutation(async () => { const { url } = await api.connectStart("meta"); window.location.href = url; return null; });
  const select = useConnMutation((id: string) => api.connectSelect("meta", id), "Page connected");
  const disconnect = useConnMutation(() => api.disconnect("meta"), "Facebook & Instagram disconnected");

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b border-stone-100 p-6">
        <div className="flex -space-x-2"><BrandIcon kind="facebook" /><BrandIcon kind="instagram" /></div>
        <div className="min-w-0 flex-1">
          <h2 className="font-bold">Facebook Page + Instagram</h2>
          <p className="text-xs text-stone-500">One Meta login connects your Facebook Page and the Instagram Business account linked to it.</p>
        </div>
        <ConnBadge on={m.connected} source={m.source} />
      </div>

      <div className="p-6">
        {m.pending_choices.length > 0 && !m.connected ? (
          <ChoosePage title="Which Facebook Page should the agent post to?" items={m.pending_choices.map((p) => ({
            id: p.id, name: p.name, picture: p.picture, sub: p.ig_username ? `Instagram: @${p.ig_username}` : "No Instagram Business account linked",
          }))} busy={select.isPending} onPick={(id) => select.mutate(id)} />
        ) : m.connected ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Account icon={<BrandIcon kind="facebook" size={36} />} label="Facebook Page" value={m.page_name || m.page_id} sub={`ID ${m.page_id}`} picture={m.picture} />
              <Account icon={<BrandIcon kind="instagram" size={36} />} label="Instagram" value={m.ig_username ? `@${m.ig_username}` : m.ig_user_id || "Not linked"}
                warn={!m.ig_user_id ? "Link an Instagram Business/Creator account to this Page in Instagram settings, then reconnect." : undefined} />
            </div>
            <ConnActions platform="meta" onReconnect={m.source !== "env" && m.method === "oauth" ? () => start.mutate(undefined) : undefined}
              onDisconnect={m.source === "env" ? undefined : () => setConfirm(true)} reconnecting={start.isPending} envNote={m.source === "env"} />
          </>
        ) : (
          <Steps
            appDone={m.app_configured} appLabel={m.app_configured ? `Meta app ${m.app_id}` : "Add your Meta app (one time)"} onApp={() => setAppOpen(true)}
            connectLabel="Connect with Facebook" connectIcon={<BrandIcon kind="facebook" size={18} />} onConnect={() => start.mutate(undefined)} connecting={start.isPending}
            onManual={() => setManual(true)} />
        )}
      </div>

      <AppModal open={appOpen} onClose={() => setAppOpen(false)} platform="meta" redirect={m.redirect_uri} current={m.app_id}
        title="Meta app" idLabel="App ID" secretLabel="App secret"
        steps={<>
          <li>Open <Ext href="https://developers.facebook.com/apps">developers.facebook.com/apps</Ext> → <b>Create app</b> → type <b>Business</b>.</li>
          <li>Add the product <b>Facebook Login for Business</b>. Under its <b>Settings</b>, paste the redirect URL below into <b>Valid OAuth Redirect URIs</b>.</li>
          <li>Under <b>App settings → Basic</b>, copy the <b>App ID</b> and <b>App secret</b> here.</li>
          <li>While the app is in development mode only you (app admins) can connect – that's fine for your own Page. For other people, Meta's App Review is needed.</li>
        </>} />
      <ManualMeta open={manual} onClose={() => setManual(false)} />
      <Confirm open={confirm} title="Disconnect Facebook & Instagram?" body="Approved content will no longer be posted there (test mode) until you connect again."
        confirmLabel="Disconnect" variant="danger" onConfirm={() => disconnect.mutate(undefined)} onClose={() => setConfirm(false)} />
    </Card>
  );
}

// ── LinkedIn ───────────────────────────────────────────────────────────────
function LinkedInCard({ c }: { c: TConn }) {
  const l = c.linkedin;
  const [appOpen, setAppOpen] = useState(false);
  const [manual, setManual] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const start = useConnMutation(async () => { const { url } = await api.connectStart("linkedin"); window.location.href = url; return null; });
  const select = useConnMutation((id: string) => api.connectSelect("linkedin", id), "LinkedIn Page connected");
  const disconnect = useConnMutation(() => api.disconnect("linkedin"), "LinkedIn disconnected");
  const expiring = l.expires_in_days !== null && l.expires_in_days < 10;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b border-stone-100 p-6">
        <BrandIcon kind="linkedin" />
        <div className="min-w-0 flex-1">
          <h2 className="font-bold">LinkedIn Company Page</h2>
          <p className="text-xs text-stone-500">Posts go out as your company Page. You must be an admin of the Page.</p>
        </div>
        <ConnBadge on={l.connected} source={l.source} warn={l.connected && expiring} />
      </div>
      <div className="p-6">
        {l.pending_choices.length > 0 && !l.connected ? (
          <ChoosePage title="Which LinkedIn Page should the agent post to?" items={l.pending_choices.map((o) => ({ id: o.id, name: o.name, sub: `Organization ${o.id}` }))}
            busy={select.isPending} onPick={(id) => select.mutate(id)} />
        ) : l.connected ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Account icon={<BrandIcon kind="linkedin" size={36} />} label="Company Page" value={l.org_name || l.org_id} sub={`Organization ${l.org_id}`} />
              <Account icon={<span className={clsx("grid size-9 place-items-center rounded-xl", expiring ? "bg-amber-100 text-amber-700" : "bg-stone-100 text-stone-500")}><KeyRound className="size-4" /></span>}
                label="Access" value={l.expires_in_days === null ? "No expiry info" : `Expires in ${l.expires_in_days} days`}
                sub={l.auto_refresh ? "Renews automatically" : "LinkedIn tokens last 60 days – reconnect before it expires"}
                warn={expiring && !l.auto_refresh ? "Expiring soon – click Reconnect." : undefined} />
            </div>
            <ConnActions platform="linkedin" onReconnect={l.source !== "env" && l.method === "oauth" ? () => start.mutate(undefined) : undefined}
              onDisconnect={l.source === "env" ? undefined : () => setConfirm(true)} reconnecting={start.isPending} envNote={l.source === "env"} />
          </>
        ) : (
          <Steps
            appDone={l.app_configured} appLabel={l.app_configured ? `LinkedIn app ${l.app_id}` : "Add your LinkedIn app (one time)"} onApp={() => setAppOpen(true)}
            connectLabel="Connect with LinkedIn" connectIcon={<BrandIcon kind="linkedin" size={18} />} onConnect={() => start.mutate(undefined)} connecting={start.isPending}
            onManual={() => setManual(true)} />
        )}
      </div>
      <AppModal open={appOpen} onClose={() => setAppOpen(false)} platform="linkedin" redirect={l.redirect_uri} current={l.app_id}
        title="LinkedIn app" idLabel="Client ID" secretLabel="Client secret"
        steps={<>
          <li>Open <Ext href="https://www.linkedin.com/developers/apps">linkedin.com/developers/apps</Ext> → <b>Create app</b> and link it to your Company Page (a Page admin must verify it).</li>
          <li>In <b>Products</b>, request <b>Community Management API</b> (needed to post as the Page).</li>
          <li>In <b>Auth</b>, add the redirect URL below under <b>Authorized redirect URLs</b>, then copy the <b>Client ID</b> and <b>Client secret</b> here.</li>
        </>} />
      <ManualLinkedIn open={manual} onClose={() => setManual(false)} />
      <Confirm open={confirm} title="Disconnect LinkedIn?" body="Approved content will no longer be posted to LinkedIn (test mode) until you connect again."
        confirmLabel="Disconnect" variant="danger" onConfirm={() => disconnect.mutate(undefined)} onClose={() => setConfirm(false)} />
    </Card>
  );
}

// ── shared pieces ──────────────────────────────────────────────────────────
function ConnBadge({ on, source, warn }: { on: boolean; source: string; warn?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ring-1",
      warn ? "bg-amber-50 text-amber-800 ring-amber-200" : on ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-stone-100 text-stone-500 ring-stone-200")}>
      <span className={clsx("size-1.5 rounded-full", warn ? "bg-amber-500" : on ? "bg-emerald-500" : "bg-stone-400")} />
      {on ? (warn ? "Expiring soon" : source === "env" ? "Connected (.env)" : "Connected") : "Test mode"}
    </span>
  );
}

function Steps({ appDone, appLabel, onApp, connectLabel, connectIcon, onConnect, connecting, onManual }: {
  appDone: boolean; appLabel: string; onApp: () => void; connectLabel: string; connectIcon: ReactNode;
  onConnect: () => void; connecting: boolean; onManual: () => void;
}) {
  return (
    <div className="space-y-3">
      <ol className="space-y-3">
        <li className="flex flex-wrap items-center gap-3 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
          <span className={clsx("grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold", appDone ? "bg-emerald-600 text-white" : "bg-ink-900 text-white")}>
            {appDone ? <CheckCircle2 className="size-4" /> : 1}
          </span>
          <span className="flex-1 text-sm font-semibold">{appLabel}</span>
          <Button onClick={onApp} icon={<Plug className="size-4" />}>{appDone ? "Change" : "Set up"}</Button>
        </li>
        <li className={clsx("flex flex-wrap items-center gap-3 rounded-xl p-3 ring-1", appDone ? "bg-white ring-stone-200" : "bg-stone-50 opacity-60 ring-stone-200/70")}>
          <span className="grid size-7 shrink-0 place-items-center rounded-full bg-ink-900 text-xs font-bold text-white">2</span>
          <span className="flex-1 text-sm font-semibold">Log in and pick your company Page</span>
          <Button variant="dark" disabled={!appDone} loading={connecting} onClick={onConnect} icon={connectIcon}>{connectLabel}</Button>
        </li>
      </ol>
      <button onClick={onManual} className="inline-flex items-center gap-1.5 text-xs font-medium text-stone-500 hover:text-stone-900">
        <KeyRound className="size-3.5" /> Already have tokens? Enter them manually
      </button>
    </div>
  );
}

function Account({ icon, label, value, sub, picture, warn }: { icon: ReactNode; label: string; value: string; sub?: string; picture?: string; warn?: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
      {picture ? <img src={picture} alt="" className="size-9 rounded-xl object-cover" /> : icon}
      <div className="min-w-0">
        <div className="text-[11px] font-bold uppercase tracking-wider text-stone-400">{label}</div>
        <div className="truncate font-semibold">{value}</div>
        {sub && <div className="text-xs text-stone-500">{sub}</div>}
        {warn && <div className="mt-1 flex gap-1 text-xs text-amber-700"><AlertTriangle className="mt-0.5 size-3 shrink-0" />{warn}</div>}
      </div>
    </div>
  );
}

function ConnActions({ platform, onReconnect, onDisconnect, reconnecting, envNote }: {
  platform: P; onReconnect?: () => void; onDisconnect?: () => void; reconnecting: boolean; envNote?: boolean;
}) {
  const [result, setResult] = useState<{ ok: boolean; lines: string[] } | null>(null);
  const test = useMutation({
    mutationFn: () => api.testConnection(platform),
    onSuccess: (r) => setResult({ ok: r.ok, lines: r.ok ? Object.values(r.results ?? {}) : [r.error ?? "Failed"] }),
    onError: (e: Error) => setResult({ ok: false, lines: [e.message] }),
  });
  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        <Button icon={<RefreshCw className="size-4" />} loading={test.isPending} onClick={() => test.mutate()}>Test connection</Button>
        {onReconnect && <Button icon={<LogIn className="size-4" />} loading={reconnecting} onClick={onReconnect}>Reconnect / change Page</Button>}
        {onDisconnect && <Button variant="danger" icon={<Unplug className="size-4" />} onClick={onDisconnect}>Disconnect</Button>}
      </div>
      {envNote && <p className="mt-2 text-xs text-stone-500">Connected through values in the environment (.env). Connect here to manage it from the dashboard.</p>}
      {result && (
        <div className={clsx("mt-3 space-y-1 rounded-xl p-3 text-sm ring-1", result.ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-red-50 text-red-800 ring-red-200")}>
          {result.lines.map((l) => <div key={l} className="flex gap-2">{result.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> : <XCircle className="mt-0.5 size-4 shrink-0" />}{l}</div>)}
        </div>
      )}
    </div>
  );
}

function ChoosePage({ title, items, onPick, busy }: { title: string; items: { id: string; name: string; sub: string; picture?: string }[]; onPick: (id: string) => void; busy: boolean }) {
  const [sel, setSel] = useState(items[0]?.id ?? "");
  return (
    <div>
      <h3 className="text-sm font-bold">{title}</h3>
      <ul className="mt-3 space-y-2">
        {items.map((p) => (
          <li key={p.id}>
            <label className={clsx("flex cursor-pointer items-center gap-3 rounded-xl p-3 ring-1 transition", sel === p.id ? "bg-ink-900 text-white ring-ink-900" : "bg-white ring-stone-200 hover:ring-stone-300")}>
              <input type="radio" checked={sel === p.id} onChange={() => setSel(p.id)} className="accent-brand-600" />
              {p.picture ? <img src={p.picture} alt="" className="size-8 rounded-lg object-cover" /> : <Link2 className="size-4" />}
              <span><span className="block text-sm font-semibold">{p.name}</span><span className={clsx("block text-xs", sel === p.id ? "text-white/60" : "text-stone-500")}>{p.sub}</span></span>
            </label>
          </li>
        ))}
      </ul>
      <Button variant="primary" className="mt-4" loading={busy} disabled={!sel} onClick={() => onPick(sel)}>Use this Page</Button>
    </div>
  );
}

function AppModal({ open, onClose, platform, redirect, current, title, idLabel, secretLabel, steps }: {
  open: boolean; onClose: () => void; platform: P; redirect: string; current: string; title: string; idLabel: string; secretLabel: string; steps: ReactNode;
}) {
  const toast = useToast();
  const [id, setId] = useState(current);
  const [secret, setSecret] = useState("");
  useEffect(() => { if (open) { setId(current); setSecret(""); } }, [open, current]);
  const save = useConnMutation(() => api.setApp(platform, id.trim(), secret.trim()), `${title} saved – you can connect now`);
  return (
    <Modal open={open} title={`Set up your ${title}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={id.trim().length < 3 || secret.trim().length < 6} loading={save.isPending}
          onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Save</Button></>}>
      <ol className="list-decimal space-y-2 pl-5 text-sm text-stone-600">{steps}</ol>
      <div className="mt-4">
        <div className="text-sm font-semibold">Redirect URL</div>
        <div className="mt-1.5 flex items-center gap-2 rounded-lg bg-stone-50 px-3 py-2 ring-1 ring-stone-200">
          <code className="min-w-0 flex-1 truncate text-xs">{redirect}</code>
          <button onClick={() => { navigator.clipboard?.writeText(redirect); toast("ok", "Copied"); }} className="rounded p-1 text-stone-500 hover:bg-white hover:text-stone-900"><Copy className="size-4" /></button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Field label={idLabel}><input value={id} onChange={(e) => setId(e.target.value)} className={inputCls} autoComplete="off" /></Field>
        <Field label={secretLabel} hint={current ? "Enter it again to change" : undefined}>
          <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} className={inputCls} autoComplete="new-password" />
        </Field>
      </div>
    </Modal>
  );
}

function ManualMeta({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [page, setPage] = useState("");
  const [token, setToken] = useState("");
  const [ig, setIg] = useState("");
  const save = useConnMutation(() => api.metaManual(page.trim(), token.trim(), ig.trim()), "Facebook & Instagram connected");
  return (
    <Modal open={open} title="Enter Meta tokens manually" onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!page.trim() || token.trim().length < 20} loading={save.isPending}
          onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Verify & connect</Button></>}>
      <p className="text-sm text-stone-500">From the Graph API Explorer: a long-lived <b>Page access token</b> (from <code>/me/accounts</code>). The Page is checked before saving.</p>
      <div className="mt-4 space-y-3">
        <Field label="Facebook Page ID"><input value={page} onChange={(e) => setPage(e.target.value)} className={inputCls} /></Field>
        <Field label="Page access token"><input type="password" value={token} onChange={(e) => setToken(e.target.value)} className={inputCls} autoComplete="new-password" /></Field>
        <Field label="Instagram Business account ID" hint="Optional – found automatically when the Page has one linked."><input value={ig} onChange={(e) => setIg(e.target.value)} className={inputCls} /></Field>
      </div>
    </Modal>
  );
}

function ManualLinkedIn({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [token, setToken] = useState("");
  const [org, setOrg] = useState("");
  const save = useConnMutation(() => api.linkedinManual(token.trim(), org.trim()), "LinkedIn connected");
  return (
    <Modal open={open} title="Enter LinkedIn token manually" onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={token.trim().length < 20 || !org.trim()} loading={save.isPending}
          onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Verify & connect</Button></>}>
      <p className="text-sm text-stone-500">An access token with <code>w_organization_social</code> (from LinkedIn's OAuth token tool). Manual tokens last 60 days and don't renew automatically.</p>
      <div className="mt-4 space-y-3">
        <Field label="Access token"><input type="password" value={token} onChange={(e) => setToken(e.target.value)} className={inputCls} autoComplete="new-password" /></Field>
        <Field label="Company Page ID" hint="The number in your Page admin URL: linkedin.com/company/12345678/admin – you can paste the whole URL.">
          <input value={org} onChange={(e) => setOrg(e.target.value)} className={inputCls} />
        </Field>
      </div>
    </Modal>
  );
}

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-semibold text-brand-700 hover:underline">{children}<ExternalLink className="size-3" /></a>;
}

