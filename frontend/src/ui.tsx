import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError } from "./api";

export type Me = {
  id: number; email: string; name: string; role: "owner" | "admin" | "manager" | "employee";
  timezone: string; organization_name: string; date_format: string; employee_id: number | null;
};
export const MeCtx = createContext<Me>(null as unknown as Me);
export const useMe = () => useContext(MeCtx);
const RANK = { employee: 1, manager: 2, admin: 3, owner: 4 };
export const atLeast = (me: Me, role: keyof typeof RANK) => RANK[me.role] >= RANK[role];

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => {
    setLoading(true);
    return fn().then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload };
}

export function Loading({ error, loading, empty, children }: { error?: string; loading?: boolean; empty?: boolean; children: ReactNode }) {
  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="error" role="alert">{error}</div>;
  if (empty) return <div className="empty">Nothing here yet.</div>;
  return <>{children}</>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h1>{title}</h1>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ text, confirmLabel = "Confirm", danger, onYes, onNo }: { text: string; confirmLabel?: string; danger?: boolean; onYes: () => void; onNo: () => void }) {
  return (
    <Modal title="Please confirm" onClose={onNo}>
      <p>{text}</p>
      <div className="actions">
        <button onClick={onNo}>Cancel</button>
        <button className={danger ? "danger" : "primary"} onClick={onYes}>{confirmLabel}</button>
      </div>
    </Modal>
  );
}

/** Runs an async action, exposing busy/error state for a form or button. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setError("");
    try { return await fn(); } catch (e) { setError(e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong"); }
    finally { setBusy(false); }
  };
  return { busy, error, run, setError };
}

export const post = (path: string, body?: unknown) => api(path, { method: "POST", body: body ?? {} });
