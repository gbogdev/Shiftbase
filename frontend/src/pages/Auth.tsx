import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Me, post, useAction } from "../ui";

export function Login({ onLogin }: { onLogin: (m: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [forgot, setForgot] = useState(false);
  const [sent, setSent] = useState(false);
  const a = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    a.run(async () => {
      if (forgot) { await post("/auth/password-reset/", { email }); setSent(true); return; }
      await fetch("/api/auth/csrf/", { credentials: "same-origin" });
      onLogin(await post("/auth/login/", { email, password }));
    });
  };
  return (
    <form className="panel center" onSubmit={submit}>
      <h1>{forgot ? "Reset password" : "Sign in to Shiftbase"}</h1>
      <label>Email<input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      {!forgot && <label>Password<input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
      {a.error && <div className="error" role="alert">{a.error}</div>}
      {sent && <div>If that account exists, a reset email has been sent.</div>}
      <button className="primary" disabled={a.busy}>{forgot ? "Send reset link" : "Sign in"}</button>{" "}
      <button type="button" className="link" onClick={() => { setForgot(!forgot); setSent(false); a.setError(""); }}>
        {forgot ? "Back to sign in" : "Forgot password?"}
      </button>
    </form>
  );
}

export function AcceptInvite() {
  const [q] = useSearchParams();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const a = useAction();
  if (done) return <div className="panel center">Account activated. <Link to="/login">Sign in</Link></div>;
  return (
    <form className="panel center" onSubmit={(e) => { e.preventDefault(); a.run(async () => { await api("/auth/accept-invite/", { method: "POST", body: { token: q.get("token"), name, password } }); setDone(true); }); }}>
      <h1>Activate your account</h1>
      <label>Your name<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Choose a password (10+ characters)<input type="password" required minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <button className="primary" disabled={a.busy}>Activate</button>
    </form>
  );
}

export function ResetPassword() {
  const [q] = useSearchParams();
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const a = useAction();
  if (done) return <div className="panel center">Password updated. <Link to="/login">Sign in</Link></div>;
  return (
    <form className="panel center" onSubmit={(e) => { e.preventDefault(); a.run(async () => { await api("/auth/password-reset/confirm/", { method: "POST", body: { uid: q.get("uid"), token: q.get("token"), password } }); setDone(true); }); }}>
      <h1>Choose a new password</h1>
      <label>New password<input type="password" required minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {a.error && <div className="error" role="alert">{a.error}</div>}
      <button className="primary" disabled={a.busy}>Update password</button>
    </form>
  );
}
