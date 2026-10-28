import { useState } from "react";
import { list } from "../api";
import { atLeast, Loading, useLoad, useMe } from "../ui";
import { api } from "../api";

const REPORTS: [string, string][] = [
  ["scheduled-hours", "Scheduled hours"], ["worked-hours", "Worked hours"], ["absences", "Absences"],
  ["overtime", "Overtime warnings"], ["open-shifts", "Open shifts"], ["attendance-discrepancies", "Attendance discrepancies"],
  ["coverage", "Staffing coverage"], ["labor-cost", "Labor cost (admins)"],
];

export default function Reports() {
  const me = useMe();
  const [name, setName] = useState("scheduled-hours");
  const [from, setFrom] = useState(() => new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10));
  const [to, setTo] = useState(() => new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10));
  const [emp, setEmp] = useState("");
  const [dept, setDept] = useState("");
  const [loc, setLoc] = useState("");
  const meta = useLoad(async () => ({ emps: await list<any>("/employees/"), depts: await list<any>("/departments/"), locs: await list<any>("/locations/") }), []);
  const qs = `start=${from}T00:00:00Z&end=${to}T00:00:00Z${emp ? `&employee=${emp}` : ""}${dept ? `&department=${dept}` : ""}${loc ? `&location=${loc}` : ""}`;
  const q = useLoad(() => api<{ columns: string[]; rows: any[][] }>(`/reports/${name}/?${qs}`), [name, qs]);
  return (
    <>
      <div className="top">
        <h1 style={{ margin: 0 }}>Reports</h1><span className="spacer" />
        <a className="btn" href={`/api/reports/${name}/?${qs}&export=csv`}>Export CSV</a>
      </div>
      <div className="panel top">
        <select value={name} onChange={(e) => setName(e.target.value)} aria-label="Report">
          {REPORTS.filter(([k]) => k !== "labor-cost" || atLeast(me, "admin")).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
        <select value={emp} onChange={(e) => setEmp(e.target.value)} aria-label="Employee"><option value="">All employees</option>{meta.data?.emps.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        <select value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Department"><option value="">All departments</option>{meta.data?.depts.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        <select value={loc} onChange={(e) => setLoc(e.target.value)} aria-label="Location"><option value="">All locations</option>{meta.data?.locs.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      </div>
      <Loading loading={q.loading} error={q.error} empty={!q.data?.rows.length}>
        <div className="table-wrap"><table><thead><tr>{q.data?.columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
          <tbody>{q.data?.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{String(v ?? "")}</td>)}</tr>)}</tbody></table></div>
      </Loading>
    </>
  );
}
