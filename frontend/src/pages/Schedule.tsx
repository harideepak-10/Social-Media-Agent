import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowDown, ArrowUp, CalendarPlus, ChevronLeft, ChevronRight, Clock, Film, ImageIcon, Moon, Pencil, Trash2,
} from "lucide-react";
import { api, WEEKDAYS, type CalDay, type CalEvent, type Kind, type Schedule as TSchedule } from "../lib/api";
import { STATUS, fmtDate } from "../lib/ui";
import { Button, Card, Confirm, Field, Modal, SaveBar, Switch, inputCls, useToast } from "../components/ui";
import OccasionsCard, { OCC_STATUS } from "../components/Occasions";

const KIND_OPTS: { id: Kind; label: string; icon: typeof Film }[] = [
  { id: "video", label: "Video", icon: Film },
  { id: "post", label: "Post", icon: ImageIcon },
  { id: "none", label: "Off", icon: Moon },
];
const PRIORITY_LABEL: Record<string, { title: string; sub: string }> = {
  festival: { title: "Festivals & special days", sub: "Diwali, Pongal, Engineers' Day…" },
  event: { title: "Your events", sub: "Launches, webinars, offers from the list below" },
  trend: { title: "Market trends", sub: "Today's trending topics tied to a product" },
  website: { title: "Products", sub: "A feature from krypsos.tech, rotating products" },
};

const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const todayIso = () => new Date().toLocaleDateString("en-CA");

export default function Schedule() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: sched } = useQuery({ queryKey: ["schedule"], queryFn: api.schedule });
  const [draft, setDraft] = useState<TSchedule | null>(null);
  useEffect(() => { if (sched) setDraft(sched); }, [sched]);

  const dirty = useMemo(() => !!sched && !!draft && JSON.stringify({ ...draft, next_runs: 0 }) !== JSON.stringify({ ...sched, next_runs: 0 }), [sched, draft]);

  const save = useMutation({
    mutationFn: () => api.saveSchedule({
      schedule: draft!.schedule, generate_time: draft!.generate_time, publish_time: draft!.publish_time,
      always_post_on_festivals: draft!.always_post_on_festivals, festival_lookahead_days: draft!.festival_lookahead_days,
      post_priority: draft!.post_priority,
    }),
    onSuccess: (d) => {
      qc.setQueryData(["schedule"], d);
      ["calendar", "meta"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast("ok", "Schedule saved – the agent uses it from the next run");
    },
    onError: (e: Error) => toast("error", e.message),
  });

  const set = <K extends keyof TSchedule>(k: K, v: TSchedule[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const perWeek = draft ? Object.values(draft.schedule).reduce((a, k) => ({ ...a, [k]: (a[k] ?? 0) + 1 }), {} as Record<string, number>) : {};

  return (
    <div className="mx-auto max-w-7xl px-5 py-8 md:px-10">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Schedule & calendar</h1>
      <p className="mt-1 text-sm text-stone-500">Choose what the agent makes on each day, when it prepares it and when it goes out.</p>

      {!draft ? <div className="shimmer mt-8 h-64 rounded-2xl bg-stone-200/60" /> : (
        <>
          <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card className="p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-bold">Weekly plan</h2>
                <span className="text-xs text-stone-500">
                  {perWeek.video ?? 0} video{perWeek.video === 1 ? "" : "s"} · {perWeek.post ?? 0} post{perWeek.post === 1 ? "" : "s"} · {perWeek.none ?? 0} off per week
                </span>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
                {WEEKDAYS.map((d) => (
                  <div key={d} className="rounded-xl bg-stone-50 p-2 ring-1 ring-stone-200/70">
                    <div className="px-1 pb-2 text-xs font-bold uppercase tracking-wider text-stone-500">{d.slice(0, 3)}</div>
                    <div className="flex flex-col gap-1">
                      {KIND_OPTS.map(({ id, label, icon: Icon }) => {
                        const on = draft.schedule[d] === id;
                        return (
                          <button key={id} onClick={() => set("schedule", { ...draft.schedule, [d]: id })}
                            className={clsx("flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm font-semibold transition",
                              on ? (id === "video" ? "bg-pink-600 text-white" : id === "post" ? "bg-sky-600 text-white" : "bg-stone-700 text-white")
                                : "text-stone-500 hover:bg-white")}>
                            <Icon className="size-3.5" /> {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-6 grid gap-5 sm:grid-cols-2">
                <Field label="Prepare content at" hint="The day before. It waits in the queue for your approval.">
                  <div className="flex items-center gap-2"><Clock className="size-4 text-stone-400" />
                    <input type="time" value={draft.generate_time} onChange={(e) => set("generate_time", e.target.value)} className={inputCls} /></div>
                </Field>
                <Field label="Publish approved content at" hint={`On the day itself · ${draft.timezone}`}>
                  <div className="flex items-center gap-2"><Clock className="size-4 text-stone-400" />
                    <input type="time" value={draft.publish_time} onChange={(e) => set("publish_time", e.target.value)} className={inputCls} /></div>
                </Field>
              </div>
              {sched?.next_runs.generate && (
                <p className="mt-3 text-xs text-stone-400">Next preparation run: {new Date(sched.next_runs.generate).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>
              )}
            </Card>

            <Card className="p-6">
              <h2 className="font-bold">Post days: what to talk about</h2>
              <p className="mt-1 text-xs text-stone-500">The agent uses the first source that has something that day. Videos always feature a product.</p>
              <ol className="mt-4 space-y-2">
                {draft.post_priority.map((p, i) => (
                  <li key={p} className="flex items-center gap-3 rounded-xl bg-stone-50 px-3 py-2.5 ring-1 ring-stone-200/70">
                    <span className="grid size-6 place-items-center rounded-md bg-ink-900 text-xs font-bold text-white">{i + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold">{PRIORITY_LABEL[p]?.title ?? p}</span>
                      <span className="block truncate text-xs text-stone-500">{PRIORITY_LABEL[p]?.sub}</span>
                    </span>
                    <button disabled={i === 0} onClick={() => { const a = [...draft.post_priority]; [a[i - 1], a[i]] = [a[i], a[i - 1]]; set("post_priority", a); }}
                      className="rounded p-1 text-stone-400 hover:bg-white hover:text-stone-800 disabled:opacity-30"><ArrowUp className="size-4" /></button>
                    <button disabled={i === draft.post_priority.length - 1} onClick={() => { const a = [...draft.post_priority]; [a[i + 1], a[i]] = [a[i], a[i + 1]]; set("post_priority", a); }}
                      className="rounded p-1 text-stone-400 hover:bg-white hover:text-stone-800 disabled:opacity-30"><ArrowDown className="size-4" /></button>
                  </li>
                ))}
              </ol>
              <div className="mt-5 space-y-4 border-t border-stone-100 pt-5">
                <Switch checked={draft.always_post_on_festivals} onChange={(v) => set("always_post_on_festivals", v)}
                  label="Greetings on days off" sub="If an approved festival or special day falls on an 'Off' day, still make the greeting post." />
                <Field label="Default timing for greetings" hint="You can change it per festival in the list below.">
                  <select value={draft.festival_lookahead_days} onChange={(e) => set("festival_lookahead_days", Number(e.target.value))} className={inputCls}>
                    <option value={0}>On the day</option>
                    <option value={1}>1 day early (recommended)</option>
                    <option value={2}>2 days early</option>
                  </select>
                </Field>
              </div>
            </Card>
          </div>
          <SaveBar dirty={dirty} saving={save.isPending} onSave={() => save.mutate()} onDiscard={() => setDraft(sched!)} />
        </>
      )}

      <MonthCalendar />
      <OccasionsCard />
      <EventsCard />
    </div>
  );
}

// ── month calendar ─────────────────────────────────────────────────────────
function MonthCalendar() {
  const [cursor, setCursor] = useState(() => new Date());
  const month = monthKey(cursor);
  const { data } = useQuery({ queryKey: ["calendar", month], queryFn: () => api.calendar(month) });
  const [eventFor, setEventFor] = useState<string | null>(null);
  const today = todayIso();

  return (
    <Card className="mt-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-bold">{cursor.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</h2>
        <div className="flex items-center gap-1">
          <Legend />
          <Button variant="ghost" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}><ChevronLeft className="size-4" /></Button>
          <Button variant="outline" onClick={() => setCursor(new Date())}>Today</Button>
          <Button variant="ghost" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}><ChevronRight className="size-4" /></Button>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-7 gap-px overflow-hidden rounded-xl bg-stone-200 ring-1 ring-stone-200">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <div key={d} className="bg-stone-50 px-2 py-2 text-center text-xs font-bold uppercase tracking-wider text-stone-500">{d}</div>
        ))}
        {(data?.days ?? Array.from({ length: 35 }, () => null)).map((day, i) =>
          day ? <DayCell key={day.date} day={day} today={today} onAdd={() => setEventFor(day.date)} />
            : <div key={i} className="shimmer h-32 bg-white" />)}
      </div>
      <EventModal open={!!eventFor} initial={eventFor ? { date: eventFor, title: "", details: "", remind_days_before: 0 } : null}
        onClose={() => setEventFor(null)} />
    </Card>
  );
}

function DayCell({ day, today, onAdd }: { day: CalDay; today: string; onAdd: () => void }) {
  const isToday = day.date === today;
  const past = day.date < today;
  const n = Number(day.date.slice(8));
  return (
    <div className={clsx("group relative flex min-h-32 flex-col gap-1 bg-white p-2", !day.in_month && "bg-stone-50/80", past && "opacity-60")}>
      <div className="flex items-center justify-between">
        <span className={clsx("grid size-6 place-items-center rounded-full text-xs font-bold",
          isToday ? "bg-brand-600 text-white" : day.in_month ? "text-stone-800" : "text-stone-400")}>{n}</span>
        {day.kind !== "none" ? (
          <span className={clsx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase",
            day.kind === "video" ? "bg-pink-50 text-pink-700" : "bg-sky-50 text-sky-700")}>
            {day.kind === "video" ? <Film className="size-3" /> : <ImageIcon className="size-3" />}{day.kind}
          </span>
        ) : <span className="text-[10px] font-semibold uppercase text-stone-300">off</span>}
      </div>
      {day.occasions.slice(0, 2).map((o) => (
        <div key={o.name} title={`${o.name} – ${OCC_STATUS[o.status].label}`}
          className={clsx("truncate rounded px-1.5 py-0.5 text-[11px] font-medium",
            o.status === "approved" ? "bg-emerald-50 text-emerald-800" : o.status === "pending" ? "bg-amber-50 text-amber-800" : "bg-stone-100 text-stone-400 line-through")}>
          {o.status === "approved" ? "✅" : o.status === "pending" ? "⏳" : "✕"} {o.name}
        </div>
      ))}
      {day.events.map((e) => (
        <div key={e.id} title={e.details} className={clsx("truncate rounded px-1.5 py-0.5 text-[11px] font-medium",
          e.paused ? "bg-stone-100 text-stone-400 line-through" : "bg-violet-50 text-violet-800")}>📌 {e.title}</div>
      ))}
      <div className="mt-auto flex flex-wrap gap-1">
        {day.items.map((it) => (
          <Link key={it.id} to={`/items/${it.id}`} title={it.topic}
            className="relative size-8 overflow-hidden rounded-md bg-stone-100 ring-1 ring-stone-200 hover:ring-2 hover:ring-ink-900">
            {it.thumb ? <img src={it.thumb} alt="" className="size-full object-cover" /> :
              <span className="grid size-full place-items-center text-stone-400">{it.kind === "video" ? <Film className="size-3.5" /> : <ImageIcon className="size-3.5" />}</span>}
            <span className={clsx("absolute bottom-0.5 right-0.5 size-2 rounded-full ring-1 ring-white", STATUS[it.status]?.dot)} />
          </Link>
        ))}
      </div>
      {!past && (
        <button onClick={onAdd} title="Add an event on this day"
          className="absolute bottom-1.5 right-1.5 hidden rounded-md bg-white p-1 text-stone-400 shadow ring-1 ring-stone-200 hover:text-violet-700 group-hover:block">
          <CalendarPlus className="size-3.5" />
        </button>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="mr-3 hidden items-center gap-3 text-xs text-stone-500 lg:flex">
      <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-emerald-400" />Will post</span>
      <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-amber-400" />Waiting for you</span>
      <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-violet-400" />Your event</span>
      <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-amber-500" />Needs review</span>
      <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-emerald-500" />Approved</span>
    </div>
  );
}

// ── events ─────────────────────────────────────────────────────────────────
function EventsCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["events"], queryFn: api.events });
  const [editing, setEditing] = useState<CalEvent | null>(null);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<CalEvent | null>(null);
  const del = useMutation({
    mutationFn: (id: number) => api.deleteEvent(id),
    onSuccess: () => { ["events", "calendar"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); toast("ok", "Event deleted"); },
    onError: (e: Error) => toast("error", e.message),
  });
  const today = todayIso();
  const upcoming = (data?.events ?? []).filter((e) => e.date >= today);
  const past = (data?.events ?? []).filter((e) => e.date < today);

  return (
    <div className="mt-6">
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold">Your events</h2>
            <p className="mt-1 text-xs text-stone-500">Launches, webinars, offers, anniversaries. The agent posts about them on the day, or earlier if you set a reminder.</p>
          </div>
          <Button variant="dark" icon={<CalendarPlus className="size-4" />} onClick={() => setAdding(true)}>Add event</Button>
        </div>
        {upcoming.length === 0 ? (
          <p className="mt-6 rounded-xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm text-stone-400">No upcoming events. Add one and the agent will announce it.</p>
        ) : (
          <ul className="mt-5 divide-y divide-stone-100">
            {upcoming.map((e) => <EventRow key={e.id} e={e} onEdit={() => setEditing(e)} onDelete={() => setDeleting(e)} />)}
          </ul>
        )}
        {past.length > 0 && (
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer text-stone-400 hover:text-stone-700">{past.length} past event{past.length > 1 ? "s" : ""}</summary>
            <ul className="mt-2 divide-y divide-stone-100 opacity-70">
              {past.map((e) => <EventRow key={e.id} e={e} onEdit={() => setEditing(e)} onDelete={() => setDeleting(e)} />)}
            </ul>
          </details>
        )}
      </Card>
      <EventModal open={adding || !!editing} initial={editing ?? (adding ? { date: today, title: "", details: "", remind_days_before: 0 } : null)}
        id={editing?.id} onClose={() => { setAdding(false); setEditing(null); }} />
      <Confirm open={!!deleting} title="Delete this event?" body={deleting?.title} confirmLabel="Delete" variant="danger"
        onConfirm={() => deleting && del.mutate(deleting.id)} onClose={() => setDeleting(null)} />
    </div>
  );
}

function EventRow({ e, onEdit, onDelete }: { e: CalEvent; onEdit: () => void; onDelete: () => void }) {
  return (
    <li className="flex items-start gap-4 py-3">
      <div className="w-14 shrink-0 rounded-lg bg-violet-50 py-1.5 text-center text-violet-800">
        <div className="text-[10px] font-bold uppercase">{fmtDate(e.date, { month: "short" })}</div>
        <div className="text-lg font-extrabold leading-none">{Number(e.date.slice(8))}</div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{e.title} {e.paused && <span className="ml-1 rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-stone-500">paused</span>}</div>
        {e.details && <div className="mt-0.5 line-clamp-2 text-sm text-stone-500">{e.details}</div>}
        <div className="mt-1 text-xs text-stone-400">{e.remind_days_before ? `Announced from ${e.remind_days_before} day${e.remind_days_before > 1 ? "s" : ""} before` : "Announced on the day"}</div>
      </div>
      <button onClick={onEdit} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-stone-800"><Pencil className="size-4" /></button>
      <button onClick={onDelete} className="rounded-lg p-2 text-stone-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-4" /></button>
    </li>
  );
}

function EventModal({ open, initial, id, onClose }: { open: boolean; initial: Omit<CalEvent, "id"> | null; id?: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<Omit<CalEvent, "id">>({ date: "", title: "", details: "", remind_days_before: 0 });
  useEffect(() => { if (open && initial) setForm({ date: initial.date, title: initial.title, details: initial.details, remind_days_before: initial.remind_days_before }); }, [open, initial?.date, initial?.title]); // eslint-disable-line
  const save = useMutation({
    mutationFn: () => (id !== undefined ? api.editEvent(id, form) : api.addEvent(form)),
    onSuccess: () => {
      ["events", "calendar", "meta"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast("ok", id !== undefined ? "Event updated" : "Event added – the agent will post about it");
      onClose();
    },
    onError: (e: Error) => toast("error", e.message),
  });
  const valid = form.date && form.title.trim().length >= 2;
  return (
    <Modal open={open} title={id !== undefined ? "Edit event" : "Add event"} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>{id !== undefined ? "Save" : "Add event"}</Button></>}>
      <div className="space-y-4">
        <Field label="Title"><input autoFocus value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Free webinar: AI agents for small businesses" className={inputCls} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Date"><input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls} /></Field>
          <Field label="Start announcing">
            <select value={form.remind_days_before} onChange={(e) => setForm({ ...form, remind_days_before: Number(e.target.value) })} className={inputCls}>
              <option value={0}>On the day</option>
              {[1, 2, 3, 5, 7].map((n) => <option key={n} value={n}>{n} day{n > 1 ? "s" : ""} before</option>)}
            </select>
          </Field>
        </div>
        <Field label="Details for the AI" hint="Time, link, offer, who it's for – anything the post should mention.">
          <textarea rows={4} value={form.details} onChange={(e) => setForm({ ...form, details: e.target.value })}
            placeholder="6 PM IST on Zoom. Register at krypsos.tech/webinar. For restaurant and clinic owners." className={clsx(inputCls, "resize-none")} />
        </Field>
      </div>
    </Modal>
  );
}
