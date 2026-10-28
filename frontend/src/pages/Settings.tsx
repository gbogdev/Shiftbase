import { useState } from "react";
import { api, list } from "../api";
import { Confirm, Loading, useAction, useLoad, useMe } from "../ui";

const TABS = ["Organization", "Lists", "Users", "Audit log"] as const;

export default function Settings() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Organization");
  return (
    <>
      <div className="top"><h1 style={{ margin: 0 }}>Settings</h1>
        {TABS.map((t) => <button key={t} className={tab === t ? "primary" : ""} onClick={() => setTab(t)}>{t}</button>)}</div>
      {tab === "Organization" && <Org />}
      {tab === "Lists" && <Lists />}
      {tab === "Users" && <Users />}
      {tab === "Audit log" && <Audit />}
    </>
  );
}

function Org() {
  const q = useLoad(() => api("/organization/"), []);
  const [f, setF] = useState<any>(null);
  const a = useAction();
  const [saved, setSaved] = useState(false);
  const v = f ?? q.data;
  const set = (k: string, val: unknown) => { setF({ ...v, [k]: val }); setSaved(false); };
  const bool = (k: string, label: string) => <label className="inline" style={{ display: "flex" }}><input type="checkbox" checked={v[k]} onChange={(e) => set(k, e.target.checked)} />{label}</label>;
  return (
    <Loading loading={q.loading} error={q.error}>
      {v && <form className="panel" onSubmit={(e) => { e.preventDefault(); a.run(async () => { setF(await api("/organization/", { method: "PATCH", body: v })); setSaved(true); }); }}>
        <div className="row2">
          <label>Organization name<input value={v.name} onChange={(e) => set("name", e.target.value)} required /></label>
          <label>Time zone (IANA, e.g. Europe/London)<input value={v.timezone} onChange={(e) => set("timezone", e.target.value)} required /></label>
          <label>Week starts on<select value={v.week_start} onChange={(e) => set("week_start", +e.target.value)}>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>
          <label>Date format<select value={v.date_format} onChange={(e) => set("date_format", e.target.value)}><option>YYYY-MM-DD</option><option>DD/MM/YYYY</option><option>MM/DD/YYYY</option></select></label>
          <label>Weekly hours warning threshold<input type="number" step="0.5" min={0} value={v.max_weekly_hours} onChange={(e) => set("max_weekly_hours", e.target.value)} /></label>
          <label>Minimum rest between shifts (hours)<input type="number" step="0.5" min={0} value={v.min_rest_hours} onChange={(e) => set("min_rest_hours", e.target.value)} /></label>
          <label>Warn when approving leave leaves fewer colleagues than<input type="number" min={0} value={v.leave_min_staff_warning} onChange={(e) => set("leave_min_staff_warning", +e.target.value)} /></label>
        </div>
        {bool("availability_blocks_publish", "Unavailability blocks publishing (otherwise it is a warning)")}
        {bool("swaps_need_approval", "Shift swaps need manager approval")}
        {bool("open_shift_applications_need_approval", "Open shift applications need manager approval")}
        {bool("email_notifications", "Send email notifications")}
        <p className="muted">These thresholds are your own policy settings. They are not legal advice; check local employment rules.</p>
        {a.error && <div className="error" role="alert">{a.error}</div>}
        <button className="primary" disabled={a.busy || !f}>Save</button> {saved && <span className="muted">Saved.</span>}
      </form>}
    </Loading>
  );
}

function Lists() {
  return <>
    <Simple title="Locations" path="/locations/" extra="address" />
    <Simple title="Departments" path="/departments/" />
    <Simple title="Positions" path="/positions/" />
    <Simple title="Qualifications" path="/qualifications/" />
    <Simple title="Leave types" path="/leave-types/" leave />
  </>;
}

function Simple({ title, path, extra, leave }: { title: string; path: string; extra?: string; leave?: boolean }) {
  const q = useLoad(() => list<any>(path), [path]);
  const [name, setName] = useState("");
  const [ex, setEx] = useState("");
  const [allow, setAllow] = useState("");
  const [del, setDel] = useState<any>(null);
  const a = useAction();
  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      <Loading loading={q.loading} error={q.error} empty={!q.data?.length}>
        <table><tbody>{q.data?.map((r: any) => <tr key={r.id}><td>{r.name}</td><td>{extra ? r[extra] : leave ? `${r.paid ? "Paid" : "Unpaid"}${r.annual_allowance_days != null ? `, ${r.annual_allowance_days} days/yr` : ""}` : ""}</td>
          <td><button className="danger" onClick={() => setDel(r)}>Delete</button></td></tr>)}</tbody></table>
      </Loading>
      <form className="top" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); a.run(async () => {
        await api(path, { method: "POST", body: leave ? { name, annual_allowance_days: allow || null } : extra ? { name, [extra]: ex } : { name } });
        setName(""); setEx(""); setAllow(""); q.reload(); }); }}>
        <input placeholder="Name" required value={name} onChange={(e) => setName(e.target.value)} aria-label={`New ${title} name`} />
        {extra && <input placeholder={extra} value={ex} onChange={(e) => setEx(e.target.value)} aria-label={extra} />}
        {leave && <input type="number" step="0.5" min={0} placeholder="Days/yr (optional)" value={allow} onChange={(e) => setAllow(e.target.value)} aria-label="Annual allowance" />}
        <button className="primary" disabled={a.busy}>Add</button>
      </form>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      {del && <Confirm danger confirmLabel="Delete" text={`Delete “${del.name}”? This fails if it is still in use.`} onNo={() => setDel(null)}
        onYes={() => a.run(async () => { await api(`${path}${del.id}/`, { method: "DELETE" }); setDel(null); q.reload(); })} />}
    </div>
  );
}

function Users() {
  const me = useMe();
  const q = useLoad(() => api<any[]>("/users/"), []);
  const a = useAction();
  const patch = (id: number, body: object) => a.run(async () => { await api(`/users/${id}/`, { method: "PATCH", body }); q.reload(); });
  return (
    <Loading loading={q.loading} error={q.error} empty={!q.data?.length}>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <div className="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th /></tr></thead><tbody>
        {q.data?.map((u) => {
          const editable = u.id !== me.id && (me.role === "owner" || (me.role === "admin" && ["manager", "employee"].includes(u.role)));
          return <tr key={u.id}><td>{u.name}</td><td>{u.email}</td>
            <td>{editable ? <select value={u.role} onChange={(e) => patch(u.id, { role: e.target.value })} aria-label={`Role for ${u.email}`}>
              {(me.role === "owner" ? ["admin", "manager", "employee"] : ["manager", "employee"]).map((r) => <option key={r}>{r}</option>)}</select> : u.role}</td>
            <td>{editable && <button className="danger" onClick={() => patch(u.id, { is_active: false })}>Deactivate</button>}</td></tr>;
        })}
      </tbody></table></div>
      <p className="muted">Invite new people from the Employees page. Deactivating an account signs the person out immediately.</p>
    </Loading>
  );
}

function Audit() {
  const q = useLoad(() => api<any[]>("/audit/"), []);
  return (
    <Loading loading={q.loading} error={q.error} empty={!q.data?.length}>
      <div className="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th></tr></thead><tbody>
        {q.data?.map((r) => <tr key={r.id}><td>{new Date(r.at).toLocaleString()}</td><td>{r.actor ?? "system"}</td><td>{r.action}</td><td>{r.target}</td></tr>)}
      </tbody></table></div>
      <p className="muted">Showing the latest 500 entries. The audit log is read-only.</p>
    </Loading>
  );
}
