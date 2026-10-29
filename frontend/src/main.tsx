import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api";
import { AcceptInvite, Login, ResetPassword } from "./pages/Auth";
import { Icon } from "./icons";
import Employees from "./pages/Employees";
import Overview from "./pages/Overview";
import MyWork from "./pages/MyWork";
import Reports from "./pages/Reports";
import Requests from "./pages/Requests";
import Schedule from "./pages/Schedule";
import Settings from "./pages/Settings";
import Time from "./pages/Time";
import Timesheets from "./pages/Timesheets";
import { atLeast, Avatar, Me, MeCtx, post } from "./ui";
import "./styles.css";

function Bell() {
  const [items, setItems] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const load = () => api("/notifications/").then(setItems).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t); }, []);
  const unread = items.filter((n) => !n.read).length;
  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => { setOpen(!open); if (!open && unread) post("/notifications/read/").then(() => setTimeout(load, 500)); }}>
        <Icon name="bell" size={16} /> {unread ? <span className="count">{unread}</span> : "Alerts"}
      </button>
      {open && (
        <div className="panel" style={{ position: "absolute", right: 0, width: 320, zIndex: 5, maxHeight: 360, overflow: "auto" }}>
          {items.length === 0 && <div className="empty">No notifications.</div>}
          {items.map((n) => (
            <div key={n.id} style={{ borderBottom: "1px solid var(--border)", padding: "6px 0" }}>
              <strong>{n.title}</strong>
              <div className="muted">{n.body}</div>
              <div className="muted" style={{ fontSize: 11 }}>{new Date(n.created_at).toLocaleString()}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Shell({ me, setMe }: { me: Me; setMe: (m: Me | null) => void }) {
  const nav = useNavigate();
  const mgr = atLeast(me, "manager");
  return (
    <MeCtx.Provider value={me}>
      <div className="shell">
        <nav className="nav" aria-label="Main">
          <div className="brand"><img className="logo" src="/static/favicon.svg" alt="" />Shiftbase</div>
          {mgr && <NavLink to="/overview"><Icon name="overview" />Overview</NavLink>}
          <NavLink to="/schedule"><Icon name="calendar" />Schedule</NavLink>
          <NavLink to="/my"><Icon name="me" />My shifts &amp; requests</NavLink>
          <NavLink to="/time"><Icon name="clock" />Time clock</NavLink>
          {mgr && <div className="navlabel">Manage</div>}
          {mgr && <NavLink to="/requests"><Icon name="check" />Approvals</NavLink>}
          {mgr && <NavLink to="/timesheets"><Icon name="sheet" />Timesheets</NavLink>}
          {mgr && <NavLink to="/employees"><Icon name="users" />Employees</NavLink>}
          {mgr && <NavLink to="/reports"><Icon name="chart" />Reports</NavLink>}
          {atLeast(me, "admin") && <NavLink to="/settings"><Icon name="gear" />Settings</NavLink>}
          <div className="who">
            <span className="person"><Avatar name={me.name || me.email} size={30} /><span><strong>{me.name || me.email}</strong><br />{me.role} · {me.organization_name}</span></span><br />
            <button className="link" onClick={async () => { await post("/auth/logout/"); setMe(null); nav("/login"); }}>Sign out</button>
          </div>
        </nav>
        <main className="main">
          <div className="top"><span className="spacer" /><Bell /></div>
          <Routes>
            <Route path="/overview" element={mgr ? <Overview /> : <Navigate to="/my" />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/my" element={<MyWork />} />
            <Route path="/time" element={<Time />} />
            <Route path="/requests" element={mgr ? <Requests /> : <Navigate to="/schedule" />} />
            <Route path="/timesheets" element={mgr ? <Timesheets /> : <Navigate to="/schedule" />} />
            <Route path="/employees" element={mgr ? <Employees /> : <Navigate to="/schedule" />} />
            <Route path="/reports" element={mgr ? <Reports /> : <Navigate to="/schedule" />} />
            <Route path="/settings" element={atLeast(me, "admin") ? <Settings /> : <Navigate to="/schedule" />} />
            <Route path="*" element={<Navigate to={mgr ? "/overview" : "/my"} />} />
          </Routes>
        </main>
      </div>
    </MeCtx.Provider>
  );
}

function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => { api<Me>("/auth/me/").then(setMe).catch(() => setMe(null)); }, []);
  if (me === undefined) return <div className="loading">Loading…</div>;
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={me ? <Navigate to="/" /> : <Login onLogin={setMe} />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="*" element={me ? <Shell me={me} setMe={setMe} /> : <Navigate to="/login" />} />
      </Routes>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
