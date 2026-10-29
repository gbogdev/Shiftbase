import { useState } from "react";
import { dayKey, fmtTime, list } from "../api";
import { Loading, Modal, Person, Status, post, useAction, useLoad, useMe } from "../ui";

export default function Timesheets() {
  const me = useMe();
  const tz = me.timezone;
  const [status, setStatus] = useState("submitted");
  const [from, setFrom] = useState(() => new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10));
  const [to, setTo] = useState(() => new Date(Date.now() + 86400000).toISOString().slice(0, 10));
  const qs = `start=${from}T00:00:00Z&end=${to}T00:00:00Z`;
  const q = useLoad(() => list<any>(`/time/?${qs}${status ? `&status=${status}` : ""}`), [status, from, to]);
  const [sel, setSel] = useState<number[]>([]);
  const [fix, setFix] = useState<any>(null);
  const a = useAction();
  const toggle = (id: number) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);
  return (
    <>
      <div className="top">
        <h1 style={{ margin: 0 }}>Timesheets</h1><span className="spacer" />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setSel([]); }} aria-label="Status">
          <option value="submitted">Awaiting approval</option><option value="open">Not submitted</option><option value="approved">Approved</option><option value="">All</option>
        </select>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
        <button className="primary" disabled={!sel.length || a.busy} onClick={() => a.run(async () => { await post("/time/approve/", { ids: sel }); setSel([]); q.reload(); })}>Approve selected ({sel.length})</button>
        <a className="btn" href={`/api/time/export/?${qs}`}>Export approved CSV</a>
      </div>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <Loading loading={q.loading} error={q.error} empty={!q.data?.length}>
        <div className="table-wrap"><table><thead><tr><th /><th>Employee</th><th>Date</th><th>In</th><th>Out</th><th>Break</th><th>Worked</th><th>Scheduled</th><th>Status</th><th /></tr></thead><tbody>
          {q.data?.map((e) => {
            const diff = e.scheduled_hours != null && e.clock_out ? e.worked_hours - e.scheduled_hours : null;
            return <tr key={e.id}>
              <td>{e.status === "submitted" && <input type="checkbox" aria-label="Select" checked={sel.includes(e.id)} onChange={() => toggle(e.id)} />}</td>
              <td><Person name={e.employee_name} /></td><td>{dayKey(e.clock_in, tz)}</td><td>{fmtTime(e.clock_in, tz)}</td><td>{e.clock_out ? fmtTime(e.clock_out, tz) : <span className="badge bad">no clock-out</span>}</td>
              <td>{e.break_minutes}m</td><td>{e.clock_out ? e.worked_hours.toFixed(2) : "—"}</td>
              <td>{e.scheduled_hours != null ? e.scheduled_hours.toFixed(2) : "—"}{diff !== null && Math.abs(diff) > 0.25 && <span className="badge bad"> {diff > 0 ? "+" : ""}{diff.toFixed(2)}h</span>}</td>
              <td><Status s={e.status} /></td>
              <td>{e.status !== "approved" && <button onClick={() => setFix(e)}>Correct</button>}</td></tr>;
          })}
        </tbody></table></div>
      </Loading>
      {fix && <Correct entry={fix} tz={tz} onClose={() => setFix(null)} onDone={() => { setFix(null); q.reload(); }} />}
    </>
  );
}

function Correct({ entry, tz, onClose, onDone }: { entry: any; tz: string; onClose: () => void; onDone: () => void }) {
  const [inT, setIn] = useState(fmtTime(entry.clock_in, tz));
  const [outT, setOut] = useState(entry.clock_out ? fmtTime(entry.clock_out, tz) : "");
  const [brk, setBrk] = useState(entry.break_minutes);
  const [reason, setReason] = useState("");
  const a = useAction();
  const date = dayKey(entry.clock_in, tz);
  return (
    <Modal title={`Correct time record — ${entry.employee_name}`} onClose={onClose}>
      <p className="muted">The original values, your name, the time and your explanation are kept permanently.</p>
      <div className="row2">
        <label>Clock in<input type="time" value={inT} onChange={(e) => setIn(e.target.value)} /></label>
        <label>Clock out<input type="time" value={outT} onChange={(e) => setOut(e.target.value)} /></label>
        <label>Break (min)<input type="number" min={0} value={brk} onChange={(e) => setBrk(+e.target.value)} /></label>
      </div>
      <label>Explanation (required)<input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></label>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={a.busy || !reason.trim()} onClick={() => a.run(async () => {
          const { zonedToIso, addDays } = await import("../api");
          const inIso = zonedToIso(date, inT, tz);
          const outIso = outT ? zonedToIso(outT <= inT ? addDays(date, 1) : date, outT, tz) : undefined;
          await post(`/time/${entry.id}/correct/`, { clock_in: inIso, clock_out: outIso, break_minutes: brk, reason });
          onDone();
        })}>Save correction</button></div>
    </Modal>
  );
}
