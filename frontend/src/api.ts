export class ApiError extends Error {
  constructor(message: string, public status: number, public issues: Issue[] = []) {
    super(message);
  }
}
export type Issue = { severity: "error" | "warning"; code: string; message: string; shift_id?: number };

function cookie(name: string): string {
  return document.cookie.split("; ").find((c) => c.startsWith(name + "="))?.split("=")[1] ?? "";
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; raw?: boolean } = {}): Promise<T> {
  const method = opts.method ?? "GET";
  if (method !== "GET" && !cookie("csrftoken")) await fetch("/api/auth/csrf/", { credentials: "same-origin" });
  const res = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken") },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (res.status === 204) return undefined as T;
  if (opts.raw) return res as unknown as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(messageOf(data) || `Request failed (${res.status})`, res.status, data.issues ?? []);
  }
  return data as T;
}

function messageOf(data: any): string {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.join(" ");
  const first = Object.entries(data)[0];
  return first ? `${first[0]}: ${[first[1]].flat().join(" ")}` : "";
}

export const list = async <T = any>(path: string): Promise<T[]> => {
  const d = await api<any>(path);
  return Array.isArray(d) ? d : d.results;
};

// ---- time zone helpers: all stored times are UTC, all displayed times use the organization zone ----
export function fmtTime(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));
}
export function dayKey(iso: string | Date, tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(typeof iso === "string" ? new Date(iso) : iso);
}
function offsetMs(at: number, tz: string): number {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
      hour: "numeric", minute: "numeric", second: "numeric" }).formatToParts(new Date(at)).map((x) => [x.type, +x.value]),
  );
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(at / 1000) * 1000;
}
/** "2026-03-02", "09:00" interpreted in `tz` -> ISO UTC string. */
export function zonedToIso(date: string, time: string, tz: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const [h, mi] = time.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, h, mi);
  let utc = guess - offsetMs(guess, tz);
  utc = guess - offsetMs(utc, tz);
  return new Date(utc).toISOString();
}
export function addDays(date: string, n: number): string {
  const d = new Date(date + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export function localTimeOf(iso: string, tz: string): string {
  return fmtTime(iso, tz);
}
