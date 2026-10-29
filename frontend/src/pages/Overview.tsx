import { Link } from "react-router-dom";
import { api, dayKey, fmtTime, list } from "../api";
import { Loading, Person, useLoad, useMe } from "../ui";

export default function Overview() {
  const me = useMe();
  const tz = me.timezone;
  const q = useLoad(async () => {
    const week = await api("/week/");
    const qs = `start=${encodeURIComponent(week.start)}&end=${encodeURIComponent(week.end)}`;
    const [shifts, emps, leave, swaps, apps, time] = await Promise.all([
      list<any>(`/shifts/?${qs}`), list<any>("/employees/"), list<any>("/leave/"), list<any>("/swaps/"),
      list<any>("/applications/"), list<any>("/time/"),
    ]);
    return { shifts, emps, leave, swaps, apps, time };
  }, []);
  const d = q.data;
  const today = dayKey(new Date(), tz);
  const name = (id: number | null) => d?.emps.find((e: any) => e.id === id)?.name ?? "";
  const todays = (d?.shifts ?? []).filter((s: any) => dayKey(s.start, tz) === today && s.employee);
  const pendingLeave = (d?.leave ?? []).filter((r: any) => r.status === "pending");
  const pendingSwaps = (d?.swaps ?? []).filter((r: any) => r.status === "accepted");
  const pendingApps = (d?.apps ?? []).filter((r: any) => r.status === "pending");
  const openShifts = (d?.shifts ?? []).filter((s: any) => !s.employee);
  const clockedIn = (d?.time ?? []).filter((e: any) => !e.clock_out);
  const approvals = pendingLeave.length + pendingSwaps.length + pendingApps.length;
  const tiles: [string, number, string, string][] = [
    ["Shifts this week", d?.shifts.length ?? 0, "/schedule", ""],
    ["Open shifts", openShifts.length, "/schedule", openShifts.length ? "warn" : ""],
    ["Waiting for approval", approvals, "/requests", approvals ? "warn" : ""],
    ["Clocked in now", clockedIn.length, "/timesheets", ""],
  ];
  return (
    <>
      <div className="top"><div><h1 style={{ margin: 0 }}>Good to see you, {me.name.split(" ")[0] || "there"}</h1>
        <div className="muted">{me.organization_name} · {today}</div></div></div>
      <Loading loading={q.loading} error={q.error}>
        <div className="stats">
          {tiles.map(([label, n, to, tone]) => (
            <Link key={label} to={to} className={`stat ${tone}`}><div className="n">{n}</div><div className="l">{label}</div></Link>
          ))}
        </div>
        <div className="cols">
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Working today ({todays.length})</h2>
            {todays.length === 0 && <div className="muted">Nobody is scheduled today.</div>}
            {todays.map((s: any) => (
              <div className="line" key={s.id}><Person name={name(s.employee)} /><span className="muted">{fmtTime(s.start, tz)}–{fmtTime(s.end, tz)}</span></div>
            ))}
          </div>
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Needs your attention</h2>
            {approvals + openShifts.length === 0 && <div className="muted">All caught up.</div>}
            {pendingLeave.map((r: any) => <div className="line" key={"l" + r.id}><span><Person name={name(r.employee)} /> <span className="muted">requested leave {r.start_date} → {r.end_date}</span></span></div>)}
            {pendingSwaps.map((r: any) => <div className="line" key={"s" + r.id}><span className="muted">Shift swap between {name(r.from_employee)} and {name(r.to_employee)}</span></div>)}
            {pendingApps.map((r: any) => <div className="line" key={"a" + r.id}><span><Person name={name(r.employee)} /> <span className="muted">applied for an open shift</span></span></div>)}
            {openShifts.length > 0 && <div className="line"><span className="muted">{openShifts.length} open shift(s) this week need staffing</span></div>}
            {approvals > 0 && <p><Link to="/requests">Review approvals →</Link></p>}
          </div>
        </div>
      </Loading>
    </>
  );
}
