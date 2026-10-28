import { useMemo, useState } from "react";
import { addDays, api, ApiError, dayKey, fmtTime, Issue, list, zonedToIso } from "../api";
import { atLeast, Confirm, Loading, Modal, post, useAction, useLoad, useMe } from "../ui";

type Shift = {
  id: number; location: number; department: number | null; position: number | null; employee: number | null;
  start: string; end: string; break_minutes: number; notes: string; status: "draft" | "published";
  modified_since_publish: boolean; version: number; hours: number;
};
type Emp = { id: number; name: string };

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function weekStartOf(date: string, weekStart: number): string {
  const d = new Date(date + "T00:00:00Z");
  return addDays(date, -((d.getUTCDay() + 6 - weekStart) % 7));
}

export default function Schedule() {
  const me = useMe();
  const tz = me.timezone;
  const canEdit = atLeast(me, "manager");
  const today = dayKey(new Date(), tz);
  const [mode, setMode] = useState<"week" | "month">("week");
  const [anchor, setAnchor] = useState(today);
  const [loc, setLoc] = useState<number | "">("");
  const [editing, setEditing] = useState<Partial<Shift> | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [notice, setNotice] = useState<{ text: string; issues: Issue[] } | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [over, setOver] = useState("");

  const meta = useLoad(async () => ({
    locations: await list("/locations/"), employees: (await list<Emp>("/employees/")),
    org: await api("/organization/"),
  }), []);
  const weekStart = meta.data?.org?.week_start ?? 0;

  const range = useMemo(() => {
    if (mode === "week") { const s = weekStartOf(anchor, weekStart); return { first: s, days: 7 }; }
    const first = anchor.slice(0, 8) + "01";
    const s = weekStartOf(first, weekStart);
    const last = new Date(Date.UTC(+anchor.slice(0, 4), +anchor.slice(5, 7), 0)).toISOString().slice(0, 10);
    const e = addDays(weekStartOf(last, weekStart), 7);
    return { first: s, days: (new Date(e).getTime() - new Date(s).getTime()) / 86400000 };
  }, [mode, anchor, weekStart]);

  const start = zonedToIso(range.first, "00:00", tz);
  const end = zonedToIso(addDays(range.first, range.days), "00:00", tz);
  const shifts = useLoad(
    () => list<Shift>(`/shifts/?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}${loc ? `&location=${loc}` : ""}`),
    [start, end, loc],
  );
  const empName = (id: number | null) => meta.data?.employees.find((e: Emp) => e.id === id)?.name ?? "Open";
  const days = Array.from({ length: range.days }, (_, i) => addDays(range.first, i));
  const byCell = (emp: number | null, day: string) =>
    (shifts.data ?? []).filter((s) => s.employee === emp && dayKey(s.start, tz) === day);
  const drafts = (shifts.data ?? []).filter((s) => s.status === "draft").length;

  const move = async (shift: Shift, employee: number | null) => {
    if (shift.employee === employee) return;
    try {
      const r = await api(`/shifts/${shift.id}/`, { method: "PATCH", body: { employee, version: shift.version } });
      const bad = (r.issues as Issue[]).filter((i) => i.code !== "unstaffed");
      if (bad.length) setNotice({ text: "Assigned, with conflicts:", issues: bad });
      else setNotice(null);
    } catch (e) {
      setNotice({ text: (e as Error).message, issues: (e as ApiError).issues ?? [] });
    }
    shifts.reload();
  };

  const step = (n: number) => {
    if (mode === "week") setAnchor(addDays(anchor, 7 * n));
    else { const d = new Date(anchor.slice(0, 8) + "01T00:00:00Z"); d.setUTCMonth(d.getUTCMonth() + n); setAnchor(d.toISOString().slice(0, 10)); }
  };

  const chip = (s: Shift) => (
    <div key={s.id} className={`chip ${s.status === "draft" ? "draft" : ""} ${s.modified_since_publish ? "modified" : ""} ${s.employee ? "" : "open"}`}
      draggable={canEdit} onDragStart={() => setDragId(s.id)} onDragEnd={() => { setDragId(null); setOver(""); }}
      tabIndex={0} role="button" aria-label={`${empName(s.employee)} ${fmtTime(s.start, tz)} to ${fmtTime(s.end, tz)}`}
      onClick={() => canEdit && setEditing(s)} onKeyDown={(e) => e.key === "Enter" && canEdit && setEditing(s)}
      title={s.notes || undefined}>
      {fmtTime(s.start, tz)}–{fmtTime(s.end, tz)}
      {s.modified_since_publish && <span className="badge bad" style={{ marginLeft: 4 }}>changed</span>}
      {mode === "month" && <div className="muted">{empName(s.employee)}</div>}
    </div>
  );

  const rows: (number | null)[] = [...(meta.data?.employees.map((e: Emp) => e.id) ?? []), null];

  return (
    <>
      <div className="top">
        <h1 style={{ margin: 0 }}>Schedule</h1>
        <button onClick={() => step(-1)} aria-label="Previous">‹</button>
        <button onClick={() => setAnchor(today)}>Today</button>
        <button onClick={() => step(1)} aria-label="Next">›</button>
        <strong>{mode === "week" ? `${range.first} – ${addDays(range.first, 6)}` : anchor.slice(0, 7)}</strong>
        <span className="spacer" />
        <select value={mode} onChange={(e) => setMode(e.target.value as "week" | "month")} aria-label="View">
          <option value="week">Week</option><option value="month">Month</option>
        </select>
        <select value={loc} onChange={(e) => setLoc(e.target.value ? +e.target.value : "")} aria-label="Location">
          <option value="">All locations</option>
          {meta.data?.locations.map((l: any) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        {canEdit && <button onClick={() => setEditing({ start: zonedToIso(today, "09:00", tz), end: zonedToIso(today, "17:00", tz), location: loc || undefined })}>Add shift</button>}
        {canEdit && <TemplateButton locs={meta.data?.locations ?? []} weekStart={range.first} onDone={shifts.reload} />}
        {canEdit && <button className="primary" disabled={!loc || mode !== "week" || !drafts} onClick={() => setConfirmPublish(true)}
          title={!loc ? "Choose a location to publish" : mode !== "week" ? "Switch to week view" : ""}>Publish week{drafts ? ` (${drafts})` : ""}</button>}
      </div>

      {notice && (
        <div className="issues" role="status">
          <strong>{notice.text}</strong>
          <ul>{notice.issues.map((i, n) => <li key={n} className={i.severity === "error" ? "e" : ""}>{i.severity}: {i.message}</li>)}</ul>
          <button className="link" onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}

      <Loading loading={shifts.loading || meta.loading} error={shifts.error || meta.error}>
        <div className="table-wrap">
          {mode === "week" ? (
            <div className="grid" style={{ gridTemplateColumns: "130px repeat(7, minmax(90px, 1fr))" }}>
              <div className="head">Employee</div>
              {days.map((d, i) => <div className={`head ${d === today ? "today" : ""}`} key={d}>{DOW[(i + weekStart) % 7]} {d.slice(5)}</div>)}
              {rows.map((emp) => (
                <Row key={emp ?? "open"} label={emp ? empName(emp) : "Open shifts"} days={days}>
                  {(d) => (
                    <div key={d} className={`cell ${over === `${emp}|${d}` ? "over" : ""}`}
                      onDragOver={(e) => { if (canEdit && dragId) { e.preventDefault(); setOver(`${emp}|${d}`); } }}
                      onDrop={() => { const s = shifts.data?.find((x) => x.id === dragId); setOver(""); if (s) move(s, emp); }}>
                      {byCell(emp, d).map(chip)}
                    </div>
                  )}
                </Row>
              ))}
            </div>
          ) : (
            <div className="month">
              {DOW.map((_, i) => <div className="dow" key={i}>{DOW[(i + weekStart) % 7]}</div>)}
              {days.map((d) => (
                <div key={d} className={d.slice(0, 7) !== anchor.slice(0, 7) ? "out" : ""}>
                  <strong>{+d.slice(8)}</strong>
                  {(shifts.data ?? []).filter((s) => dayKey(s.start, tz) === d).map(chip)}
                </div>
              ))}
            </div>
          )}
          {!shifts.data?.length && <div className="empty">No shifts in this period.{canEdit && " Use “Add shift” or apply a template."}</div>}
        </div>
      </Loading>

      {editing && <ShiftDialog shift={editing} emps={meta.data?.employees ?? []} locs={meta.data?.locations ?? []} tz={tz}
        onClose={() => setEditing(null)} onSaved={(issues) => { setEditing(null); if (issues.length) setNotice({ text: "Saved. Review:", issues }); shifts.reload(); }} />}
      {confirmPublish && <PublishDialog loc={+loc} start={start} end={end} onClose={() => setConfirmPublish(false)}
        onDone={(t, issues) => { setConfirmPublish(false); setNotice({ text: t, issues }); shifts.reload(); }} />}
    </>
  );
}

function Row({ label, days, children }: { label: string; days: string[]; children: (d: string) => React.ReactNode }) {
  return <>
    <div className="rowname">{label}</div>
    {days.map((d) => children(d))}
  </>;
}

function PublishDialog({ loc, start, end, onClose, onDone }: { loc: number; start: string; end: string; onClose: () => void; onDone: (t: string, i: Issue[]) => void }) {
  const a = useAction();
  const [blocking, setBlocking] = useState<Issue[]>([]);
  return (
    <Modal title="Publish schedule" onClose={onClose}>
      <p>Publishing makes draft shifts for this location and week visible to employees and notifies them. Blocking conflicts prevent publication.</p>
      {blocking.length > 0 && <div className="issues"><strong>Cannot publish:</strong><ul>{blocking.map((i, n) => <li key={n} className="e">{i.message} (shift {i.shift_id})</li>)}</ul></div>}
      {a.error && <div className="error">{a.error}</div>}
      <div className="actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={a.busy} onClick={() => a.run(async () => {
          try {
            const r = await post("/shifts/publish/", { location: loc, start, end });
            onDone(`Published ${r.published} shift(s).`, r.warnings.filter((w: Issue) => w.code !== "unstaffed"));
          } catch (e) { if (e instanceof ApiError && e.issues.length) setBlocking(e.issues); else throw e; }
        })}>Publish</button>
      </div>
    </Modal>
  );
}

function TemplateButton({ locs, weekStart, onDone }: { locs: any[]; weekStart: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const tpl = useLoad(() => list("/templates/"), [open]);
  const a = useAction();
  const [name, setName] = useState("");
  const [loc, setLoc] = useState("");
  const [rows, setRows] = useState("0,09:00,17:00,30\n1,09:00,17:00,30");
  return (
    <>
      <button onClick={() => setOpen(true)}>Templates</button>
      {open && (
        <Modal title="Schedule templates" onClose={() => setOpen(false)}>
          <Loading loading={tpl.loading} error={tpl.error} empty={!tpl.data?.length}>
            <table><tbody>{tpl.data?.map((t: any) => (
              <tr key={t.id}><td>{t.name}</td><td>{t.shifts.length} shifts</td>
                <td><button disabled={a.busy} onClick={() => a.run(async () => { await post(`/templates/${t.id}/apply/`, { week_start: weekStart }); onDone(); setOpen(false); })}>Apply to week of {weekStart}</button></td></tr>
            ))}</tbody></table>
          </Loading>
          <h2>New template</h2>
          <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label>Location<select value={loc} onChange={(e) => setLoc(e.target.value)}><option value="">Choose…</option>{locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
          <label>Shifts, one per line: weekday(0=Mon), start, end, break minutes<textarea rows={4} value={rows} onChange={(e) => setRows(e.target.value)} /></label>
          {a.error && <div className="error">{a.error}</div>}
          <div className="actions"><button onClick={() => setOpen(false)}>Close</button>
            <button className="primary" disabled={a.busy || !name || !loc} onClick={() => a.run(async () => {
              const shifts = rows.split("\n").filter(Boolean).map((r) => { const [w, s, e, b] = r.split(",").map((x) => x.trim()); return { weekday: +w, start: s, end: e, break_minutes: +(b || 0) }; });
              await post("/templates/", { name, location: +loc, shifts }); tpl.reload(); setName("");
            })}>Save template</button></div>
        </Modal>
      )}
    </>
  );
}

function ShiftDialog({ shift, emps, locs, tz, onClose, onSaved }: { shift: Partial<Shift>; emps: Emp[]; locs: any[]; tz: string; onClose: () => void; onSaved: (i: Issue[]) => void }) {
  const isNew = !shift.id;
  const date0 = shift.start ? dayKey(shift.start, tz) : "";
  const [date, setDate] = useState(date0);
  const [from, setFrom] = useState(shift.start ? fmtTime(shift.start, tz) : "09:00");
  const [to, setTo] = useState(shift.end ? fmtTime(shift.end, tz) : "17:00");
  const [employee, setEmployee] = useState(shift.employee ? String(shift.employee) : "");
  const [location, setLocation] = useState(shift.location ? String(shift.location) : "");
  const [brk, setBrk] = useState(shift.break_minutes ?? 0);
  const [notes, setNotes] = useState(shift.notes ?? "");
  const [repeat, setRepeat] = useState(false);
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [until, setUntil] = useState("");
  const [del, setDel] = useState(false);
  const a = useAction();

  const body = () => {
    const s = zonedToIso(date, from, tz);
    const endDate = to <= from ? addDays(date, 1) : date; // overnight shifts roll to the next day
    return { location: +location, employee: employee ? +employee : null, start: s, end: zonedToIso(endDate, to, tz), break_minutes: +brk, notes };
  };
  const save = () => a.run(async () => {
    if (isNew && repeat) {
      await post("/shifts/recurring/", { ...body(), weekdays, until });
      onSaved([]);
    } else {
      const r = isNew ? await post("/shifts/", body()) : await api(`/shifts/${shift.id}/`, { method: "PATCH", body: { ...body(), version: shift.version } });
      onSaved((r.issues as Issue[]).filter((i) => i.code !== "unstaffed"));
    }
  });
  return (
    <Modal title={isNew ? "New shift" : "Edit shift"} onClose={onClose}>
      {shift.status === "published" && <div className="banner">This shift is published. Changes notify the employee and are logged.</div>}
      <div className="row2">
        <label>Date<input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
        <label>Location<select value={location} onChange={(e) => setLocation(e.target.value)} required><option value="">Choose…</option>{locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        <label>Start<input type="time" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>End<input type="time" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <label>Employee<select value={employee} onChange={(e) => setEmployee(e.target.value)}><option value="">Open shift</option>{emps.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
        <label>Break (minutes)<input type="number" min={0} value={brk} onChange={(e) => setBrk(+e.target.value)} /></label>
      </div>
      <label>Notes<input maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      {isNew && (
        <>
          <label className="inline"><input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} /> Repeat weekly</label>
          {repeat && (
            <div>
              {DOW.map((d, i) => <label className="inline" key={d} style={{ marginRight: 8 }}><input type="checkbox" checked={weekdays.includes(i)} onChange={(e) => setWeekdays(e.target.checked ? [...weekdays, i] : weekdays.filter((x) => x !== i))} />{d}</label>)}
              <label>Until<input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
            </div>
          )}
        </>
      )}
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <div className="actions">
        {!isNew && <button className="danger" onClick={() => setDel(true)}>Delete</button>}
        {!isNew && <button disabled={a.busy} onClick={() => a.run(async () => { await post(`/shifts/${shift.id}/duplicate/`, { days: 7 }); onSaved([]); })}>Duplicate +1 week</button>}
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={a.busy || !date || !location || (repeat && (!until || !weekdays.length))} onClick={save}>Save</button>
      </div>
      {del && <Confirm danger confirmLabel="Delete shift" text="Delete this shift? If it is published, the employee is notified." onNo={() => setDel(false)}
        onYes={() => a.run(async () => { await api(`/shifts/${shift.id}/`, { method: "DELETE" }); onSaved([]); })} />}
    </Modal>
  );
}
