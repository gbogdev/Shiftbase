import { useState } from "react";
import { api, dayKey, fmtTime, list } from "../api";
import { Confirm, Loading, Status, post, useAction, useLoad, useMe } from "../ui";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function MyWork() {
  const me = useMe();
  const tz = me.timezone;
  const now = new Date().toISOString();
  const data = useLoad(async () => ({
    shifts: await list<any>(`/shifts/?start=${encodeURIComponent(now)}`),
    emps: await list<any>("/employees/"),
    swaps: await list<any>("/swaps/"),
    apps: await list<any>("/applications/"),
    leave: await list<any>("/leave/"),
    types: await list<any>("/leave-types/"),
    balances: await api<any[]>("/leave/balances/"),
  }), []);
  const a = useAction();
  const [swapFor, setSwapFor] = useState<any>(null);
  const [swapTo, setSwapTo] = useState("");
  const [cancel, setCancel] = useState<number | null>(null);
  const [lv, setLv] = useState({ leave_type: "", start_date: "", end_date: "", reason: "" });
  const d = data.data;
  const mine = d?.shifts.filter((s: any) => s.employee === me.employee_id) ?? [];
  const open = d?.shifts.filter((s: any) => !s.employee) ?? [];
  const name = (id: number) => d?.emps.find((e: any) => e.id === id)?.name ?? `#${id}`;
  const when = (s: any) => `${dayKey(s.start, tz)} ${fmtTime(s.start, tz)}–${fmtTime(s.end, tz)}`;
  const shiftOf = (id: number) => d?.shifts.find((s: any) => s.id === id);
  const act = (fn: () => Promise<unknown>) => a.run(async () => { await fn(); await data.reload(); });

  if (!me.employee_id) return <div className="panel">Your account has no employee profile, so there is nothing to show here. Ask an administrator to link one.</div>;
  return (
    <Loading loading={data.loading} error={data.error}>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <h1>My upcoming shifts</h1>
      {mine.length === 0 ? <div className="empty">No upcoming published shifts.</div> : (
        <div className="table-wrap"><table><thead><tr><th>When</th><th>Break</th><th>Notes</th><th /></tr></thead><tbody>
          {mine.map((s: any) => (
            <tr key={s.id}><td>{when(s)}{s.modified_since_publish && <span className="badge bad"> changed</span>}</td><td>{s.break_minutes} min</td><td>{s.notes}</td>
              <td><button onClick={() => { setSwapFor(s); setSwapTo(""); }}>Offer / swap</button></td></tr>
          ))}
        </tbody></table></div>
      )}

      <h2>Open shifts</h2>
      {open.length === 0 ? <div className="empty">No open shifts right now.</div> : (
        <table><tbody>{open.map((s: any) => {
          const applied = d?.apps.some((p: any) => p.shift === s.id && p.employee === me.employee_id && p.status === "pending");
          return <tr key={s.id}><td>{when(s)}</td><td>{applied ? <span className="pill info">Applied</span> : <button disabled={a.busy} onClick={() => act(() => post("/applications/", { shift: s.id }))}>Apply</button>}</td></tr>;
        })}</tbody></table>
      )}

      <h2>Shift swaps</h2>
      {d?.swaps.length === 0 ? <div className="empty">No swap requests.</div> : (
        <table><thead><tr><th>Shift</th><th>From</th><th>To</th><th>Status</th><th /></tr></thead><tbody>
          {d?.swaps.map((r: any) => {
            const s = shiftOf(r.shift);
            const canAccept = r.status === "pending" && r.from_employee !== me.employee_id && (!r.to_employee || r.to_employee === me.employee_id);
            return <tr key={r.id}><td>{s ? when(s) : `#${r.shift}`}</td><td>{name(r.from_employee)}</td><td>{r.to_employee ? name(r.to_employee) : "Anyone"}</td><td><Status s={r.status} /></td>
              <td>{canAccept && <button disabled={a.busy} onClick={() => act(() => post(`/swaps/${r.id}/accept/`))}>Accept</button>}</td></tr>;
          })}
        </tbody></table>
      )}

      <h2>Time off</h2>
      <div className="panel">
        {d?.balances.filter((b: any) => b.allowance !== null).map((b: any) => <div key={b.leave_type}>{b.leave_type}: {b.used} of {b.allowance} days used</div>)}
        <form className="row2" onSubmit={(e) => { e.preventDefault(); act(() => post("/leave/", lv)); }}>
          <label>Type<select required value={lv.leave_type} onChange={(e) => setLv({ ...lv, leave_type: e.target.value })}><option value="">Choose…</option>{d?.types.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
          <label>Reason (optional)<input value={lv.reason} onChange={(e) => setLv({ ...lv, reason: e.target.value })} /></label>
          <label>From<input type="date" required value={lv.start_date} onChange={(e) => setLv({ ...lv, start_date: e.target.value })} /></label>
          <label>To<input type="date" required min={lv.start_date} value={lv.end_date} onChange={(e) => setLv({ ...lv, end_date: e.target.value })} /></label>
          <div><button className="primary" disabled={a.busy}>Request time off</button></div>
        </form>
        {d?.types.length === 0 && <div className="muted">No leave types are configured yet. An administrator can add them in Settings.</div>}
      </div>
      {d?.leave.length ? (
        <table><thead><tr><th>Dates</th><th>Type</th><th>Status</th><th>Note</th><th /></tr></thead><tbody>
          {d.leave.filter((r: any) => r.employee === me.employee_id).map((r: any) => (
            <tr key={r.id}><td>{r.start_date} → {r.end_date}</td><td>{d.types.find((t: any) => t.id === r.leave_type)?.name}</td><td><Status s={r.status} /></td><td>{r.decision_note}</td>
              <td>{r.status === "pending" && <button onClick={() => setCancel(r.id)}>Cancel</button>}</td></tr>
          ))}
        </tbody></table>
      ) : null}

      <Availability empId={me.employee_id} />

      {swapFor && (
        <Confirm confirmLabel="Send" text={`Offer ${when(swapFor)}. Choose a colleague, or leave empty to offer it to anyone.`} onNo={() => setSwapFor(null)}
          onYes={() => act(() => post("/swaps/", { shift: swapFor.id, to_employee: swapTo || null }).then(() => setSwapFor(null)))} />
      )}
      {swapFor && (
        <div style={{ position: "fixed", bottom: 16, right: 16, zIndex: 20 }} className="panel">
          <select value={swapTo} onChange={(e) => setSwapTo(e.target.value)} aria-label="Colleague">
            <option value="">Anyone</option>
            {d?.emps.filter((e: any) => e.id !== me.employee_id).map((e: any) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
      )}
      {cancel && <Confirm text="Cancel this leave request?" confirmLabel="Cancel request" danger onNo={() => setCancel(null)} onYes={() => act(() => post(`/leave/${cancel}/cancel/`).then(() => setCancel(null)))} />}
    </Loading>
  );
}

function Availability({ empId }: { empId: number }) {
  const q = useLoad(() => api<any[]>(`/employees/${empId}/availability/`), [empId]);
  const [rows, setRows] = useState<any[] | null>(null);
  const a = useAction();
  const cur = rows ?? q.data ?? [];
  const set = (i: number, patch: any) => setRows(cur.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  return (
    <>
      <h2>My availability</h2>
      <Loading loading={q.loading} error={q.error}>
        <div className="panel">
          {cur.length === 0 && <div className="muted">No restrictions set. You are treated as generally available.</div>}
          {cur.map((r, i) => (
            <div key={i} className="top">
              <select value={r.weekday} onChange={(e) => set(i, { weekday: +e.target.value })} aria-label="Day">{DOW.map((d, n) => <option key={d} value={n}>{d}</option>)}</select>
              <input type="time" value={r.start_time.slice(0, 5)} onChange={(e) => set(i, { start_time: e.target.value })} aria-label="From" />
              <input type="time" value={r.end_time.slice(0, 5)} onChange={(e) => set(i, { end_time: e.target.value })} aria-label="To" />
              <select value={String(r.available)} onChange={(e) => set(i, { available: e.target.value === "true" })} aria-label="Type"><option value="true">Available</option><option value="false">Unavailable</option></select>
              <button onClick={() => setRows(cur.filter((_, n) => n !== i))}>Remove</button>
            </div>
          ))}
          {a.error && <div className="error">{a.error}</div>}
          <button onClick={() => setRows([...cur, { weekday: 0, start_time: "09:00", end_time: "17:00", available: false }])}>Add period</button>{" "}
          <button className="primary" disabled={a.busy || rows === null} onClick={() => a.run(async () => { await api(`/employees/${empId}/availability/`, { method: "PUT", body: cur }); setRows(null); q.reload(); })}>Save availability</button>
        </div>
      </Loading>
    </>
  );
}
