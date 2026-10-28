import { useEffect, useState } from "react";
import { dayKey, fmtTime, list } from "../api";
import { Loading, post, useAction, useLoad, useMe } from "../ui";

export default function Time() {
  const me = useMe();
  const tz = me.timezone;
  const q = useLoad(() => list<any>("/time/"), []);
  const a = useAction();
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 30000); return () => clearInterval(t); }, []);
  const mine = (q.data ?? []).filter((e) => e.employee === me.employee_id);
  const open = mine.find((e) => !e.clock_out);
  const act = (path: string) => a.run(async () => { await post(path); await q.reload(); });

  if (!me.employee_id) return <div className="panel">Your account has no employee profile, so you cannot clock in.</div>;
  const elapsed = open ? Math.floor((Date.now() - new Date(open.clock_in).getTime()) / 60000) : 0;
  return (
    <>
      <h1>Time clock</h1>
      <div className="panel">
        {open ? (
          <>
            <div>Clocked in since {fmtTime(open.clock_in, tz)} ({Math.floor(elapsed / 60)}h {elapsed % 60}m){open.break_started_at && " — on break"}</div>
            <div className="top">
              {open.break_started_at
                ? <button disabled={a.busy} onClick={() => act("/time/break-end/")}>End break</button>
                : <button disabled={a.busy} onClick={() => act("/time/break-start/")}>Start break</button>}
              <button className="primary" disabled={a.busy} onClick={() => act("/time/clock-out/")}>Clock out</button>
            </div>
          </>
        ) : (
          <>
            <div className="muted">You are not clocked in.</div>
            <div className="top"><button className="primary" disabled={a.busy} onClick={() => act("/time/clock-in/")}>Clock in</button></div>
          </>
        )}
        {a.error && <div className="error" role="alert">{a.error}</div>}
        <div className="muted" style={{ fontSize: 12 }}>Times are shown in {tz}. Your clock-in time is recorded by the server, not your device.</div>
      </div>
      <h2>Recent entries</h2>
      <Loading loading={q.loading} error={q.error} empty={!mine.length}>
        <div className="table-wrap"><table><thead><tr><th>Date</th><th>In</th><th>Out</th><th>Break</th><th>Worked</th><th>Scheduled</th><th>Status</th></tr></thead><tbody>
          {mine.slice(0, 30).map((e) => (
            <tr key={e.id}><td>{dayKey(e.clock_in, tz)}</td><td>{fmtTime(e.clock_in, tz)}</td><td>{e.clock_out ? fmtTime(e.clock_out, tz) : "—"}</td><td>{e.break_minutes}m</td>
              <td>{e.clock_out ? e.worked_hours.toFixed(2) + "h" : "—"}</td><td>{e.scheduled_hours != null ? e.scheduled_hours.toFixed(2) + "h" : "unscheduled"}</td>
              <td><span className="badge">{e.status}</span>{" "}{e.status === "open" && e.clock_out && <button className="link" disabled={a.busy} onClick={() => a.run(async () => { await post("/time/submit/", { ids: [e.id] }); await q.reload(); })}>Submit</button>}</td></tr>
          ))}
        </tbody></table></div>
      </Loading>
    </>
  );
}
