import { useState } from "react";
import { api, list } from "../api";
import { atLeast, Confirm, Loading, Modal, post, useAction, useLoad, useMe } from "../ui";

export default function Employees() {
  const me = useMe();
  const admin = atLeast(me, "admin");
  const [archived, setArchived] = useState(false);
  const q = useLoad(async () => ({
    emps: await list<any>(`/employees/${archived ? "?archived=1" : ""}`),
    depts: await list<any>("/departments/"), poss: await list<any>("/positions/"),
    locs: await list<any>("/locations/"), quals: await list<any>("/qualifications/"),
  }), [archived]);
  const [edit, setEdit] = useState<any>(null);
  const [confirm, setConfirm] = useState<{ emp: any; kind: "archive" | "deactivate" } | null>(null);
  const [invite, setInvite] = useState<any>(null);
  const a = useAction();
  const nm = (rows: any[] | undefined, id: number | null) => rows?.find((r) => r.id === id)?.name ?? "";
  return (
    <>
      <div className="top">
        <h1 style={{ margin: 0 }}>Employees</h1><span className="spacer" />
        <label className="inline" style={{ margin: 0 }}><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
        {admin && <button className="primary" onClick={() => setEdit({ name: "", email: "", status: "active", locations: [], qualifications: [], contracted_hours: 0 })}>Add employee</button>}
      </div>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <Loading loading={q.loading} error={q.error} empty={!q.data?.emps.length}>
        <div className="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Department</th><th>Position</th><th>Locations</th><th>Hours</th><th>Status</th><th>Account</th><th /></tr></thead><tbody>
          {q.data?.emps.map((e: any) => (
            <tr key={e.id}><td>{e.name}</td><td>{e.email}</td><td>{nm(q.data!.depts, e.department)}</td><td>{nm(q.data!.poss, e.position)}</td>
              <td>{e.locations.map((l: number) => nm(q.data!.locs, l)).join(", ")}</td><td>{e.contracted_hours}</td><td><span className={`badge ${e.status !== "active" ? "draft" : ""}`}>{e.status}</span></td>
              <td>{e.user ? "Active" : admin ? <button className="link" onClick={() => a.run(async () => setInvite(await post("/invitations/", { email: e.email, employee: e.id })))}>Invite</button> : "—"}</td>
              <td>{admin && e.status !== "archived" && <>
                <button onClick={() => setEdit(e)}>Edit</button>{" "}
                {e.status === "active" && <button onClick={() => setConfirm({ emp: e, kind: "deactivate" })}>Deactivate</button>}{" "}
                <button className="danger" onClick={() => setConfirm({ emp: e, kind: "archive" })}>Archive</button></>}</td></tr>
          ))}
        </tbody></table></div>
      </Loading>

      {edit && <EditEmployee emp={edit} data={q.data!} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload(); }} />}
      {confirm && <Confirm danger confirmLabel={confirm.kind === "archive" ? "Archive" : "Deactivate"}
        text={confirm.kind === "archive" ? `Archive ${confirm.emp.name}? Their login is disabled and they are hidden from lists. Shifts, time records and approvals are kept.` : `Deactivate ${confirm.emp.name}? They can no longer sign in.`}
        onNo={() => setConfirm(null)} onYes={() => a.run(async () => { await post(`/employees/${confirm.emp.id}/${confirm.kind}/`); setConfirm(null); q.reload(); })} />}
      {invite && <Modal title="Invitation sent" onClose={() => setInvite(null)}>
        <p>An activation email was sent. The link expires on {new Date(invite.expires_at).toLocaleString()}.</p>
        {invite.debug_link && <p className="muted">Development link: <a href={invite.debug_link}>{invite.debug_link}</a></p>}
        <div className="actions"><button className="primary" onClick={() => { setInvite(null); q.reload(); }}>OK</button></div></Modal>}
    </>
  );
}

function EditEmployee({ emp, data, onClose, onSaved }: { emp: any; data: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ ...emp, department: emp.department ?? "", position: emp.position ?? "", hourly_rate: emp.hourly_rate ?? "" });
  const a = useAction();
  const multi = (key: "locations" | "qualifications", id: number, on: boolean) => setF({ ...f, [key]: on ? [...f[key], id] : f[key].filter((x: number) => x !== id) });
  const body = { ...f, department: f.department || null, position: f.position || null, hourly_rate: f.hourly_rate === "" ? null : f.hourly_rate, start_date: f.start_date || null };
  return (
    <Modal title={emp.id ? "Edit employee" : "Add employee"} onClose={onClose}>
      <div className="row2">
        <label>Name<input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label>Email<input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label>Department<select value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })}><option value="">—</option>{data.depts.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label>Position<select value={f.position} onChange={(e) => setF({ ...f, position: e.target.value })}><option value="">—</option>{data.poss.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label>Contracted hours / week<input type="number" min={0} step="0.5" value={f.contracted_hours} onChange={(e) => setF({ ...f, contracted_hours: e.target.value })} /></label>
        <label>Hourly rate (optional)<input type="number" min={0} step="0.01" value={f.hourly_rate} onChange={(e) => setF({ ...f, hourly_rate: e.target.value })} /></label>
        <label>Start date<input type="date" value={f.start_date ?? ""} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
        <label>Phone<input value={f.phone ?? ""} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
      </div>
      <strong>Locations</strong><div>{data.locs.map((l: any) => <label className="inline" key={l.id} style={{ marginRight: 10 }}><input type="checkbox" checked={f.locations.includes(l.id)} onChange={(e) => multi("locations", l.id, e.target.checked)} />{l.name}</label>)}</div>
      <strong>Qualifications</strong><div>{data.quals.length ? data.quals.map((l: any) => <label className="inline" key={l.id} style={{ marginRight: 10 }}><input type="checkbox" checked={f.qualifications.includes(l.id)} onChange={(e) => multi("qualifications", l.id, e.target.checked)} />{l.name}</label>) : <span className="muted">None defined (add in Settings).</span>}</div>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={a.busy || !f.name || !f.email} onClick={() => a.run(async () => { await api(emp.id ? `/employees/${emp.id}/` : "/employees/", { method: emp.id ? "PATCH" : "POST", body }); onSaved(); })}>Save</button></div>
    </Modal>
  );
}
