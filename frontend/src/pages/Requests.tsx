import { useState } from "react";
import { dayKey, fmtTime, Issue, list } from "../api";
import { Loading, Modal, post, useAction, useLoad, useMe } from "../ui";

export default function Requests() {
  const me = useMe();
  const tz = me.timezone;
  const q = useLoad(async () => ({
    leave: (await list<any>("/leave/")).filter((r) => r.status === "pending"),
    swaps: (await list<any>("/swaps/")).filter((r) => r.status === "accepted"),
    apps: (await list<any>("/applications/")).filter((r) => r.status === "pending"),
    emps: await list<any>("/employees/"),
    shifts: await list<any>(`/shifts/?start=${encodeURIComponent(new Date(Date.now() - 86400000).toISOString())}`),
    types: await list<any>("/leave-types/"),
  }), []);
  const a = useAction();
  const [result, setResult] = useState<{ text: string; issues: Issue[]; lines: string[] } | null>(null);
  const d = q.data;
  const name = (id: number) => d?.emps.find((e: any) => e.id === id)?.name ?? `#${id}`;
  const when = (id: number) => { const s = d?.shifts.find((x: any) => x.id === id); return s ? `${dayKey(s.start, tz)} ${fmtTime(s.start, tz)}–${fmtTime(s.end, tz)}` : `shift #${id}`; };
  const decide = (path: string, approve: boolean, note = "") =>
    a.run(async () => {
      const r = await post(path, { approve, note });
      if (r.staffing_warnings?.length || r.conflicting_shift_ids?.length) {
        setResult({ text: "Approved.", issues: [], lines: [
          ...r.staffing_warnings.map((w: any) => `Staffing: only ${w.available_colleagues} colleague(s) available on ${w.date}.`),
          ...(r.conflicting_shift_ids.length ? [`${r.conflicting_shift_ids.length} scheduled shift(s) fall within this leave and need reassigning.`] : []),
        ] });
      }
      await q.reload();
    });
  const empty = d && !d.leave.length && !d.swaps.length && !d.apps.length;
  return (
    <>
      <h1>Approvals</h1>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <Loading loading={q.loading} error={q.error} empty={!!empty}>
        <h2>Leave requests</h2>
        {d?.leave.length ? <table><thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th>Reason</th><th /></tr></thead><tbody>
          {d.leave.map((r: any) => <tr key={r.id}><td>{name(r.employee)}</td><td>{d.types.find((t: any) => t.id === r.leave_type)?.name}</td><td>{r.start_date} → {r.end_date} ({r.days}d)</td><td>{r.reason}</td>
            <td><button className="primary" disabled={a.busy} onClick={() => decide(`/leave/${r.id}/decide/`, true)}>Approve</button>{" "}
              <button disabled={a.busy} onClick={() => { const n = window.prompt("Reason for rejecting (shown to the employee):"); if (n !== null) decide(`/leave/${r.id}/decide/`, false, n); }}>Reject</button></td></tr>)}
        </tbody></table> : <div className="empty">No pending leave requests.</div>}
        <h2>Shift swaps awaiting approval</h2>
        {d?.swaps.length ? <table><tbody>{d.swaps.map((r: any) => <tr key={r.id}><td>{when(r.shift)}</td><td>{name(r.from_employee)} → {name(r.to_employee)}</td>
          <td><button className="primary" disabled={a.busy} onClick={() => decide(`/swaps/${r.id}/decide/`, true)}>Approve</button>{" "}<button disabled={a.busy} onClick={() => decide(`/swaps/${r.id}/decide/`, false)}>Reject</button></td></tr>)}</tbody></table> : <div className="empty">None.</div>}
        <h2>Open shift applications</h2>
        {d?.apps.length ? <table><tbody>{d.apps.map((r: any) => <tr key={r.id}><td>{when(r.shift)}</td><td>{name(r.employee)}</td>
          <td><button className="primary" disabled={a.busy} onClick={() => decide(`/applications/${r.id}/decide/`, true)}>Assign</button>{" "}<button disabled={a.busy} onClick={() => decide(`/applications/${r.id}/decide/`, false)}>Reject</button></td></tr>)}</tbody></table> : <div className="empty">None.</div>}
      </Loading>
      {result && (
        <Modal title="Approved — please review" onClose={() => setResult(null)}>
          <ul>{result.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
          <div className="actions"><button className="primary" onClick={() => setResult(null)}>OK</button></div>
        </Modal>
      )}
    </>
  );
}
