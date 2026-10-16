export class ApiError extends Error {
  status: number;
  fields: Record<string, string>;
  current?: unknown;
  constructor(status: number, message: string, fields: Record<string, string> = {}, current?: unknown) {
    super(message);
    this.status = status;
    this.fields = fields;
    this.current = current;
  }
}

type Json = Record<string, unknown> | unknown[];

export async function api<T>(path: string, init: { method?: string; body?: Json } = {}): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: init.method ?? "GET",
    credentials: "same-origin",
    headers: init.body ? { "content-type": "application/json" } : undefined,
    body: init.body ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/auth/")) {
    window.dispatchEvent(new Event("airops:unauthorised"));
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    let fields: Record<string, string> = {};
    let current: unknown;
    try {
      const body = await res.json();
      const e = body.error ?? body;
      msg = e.message ?? (typeof e.detail === "string" ? e.detail : msg);
      fields = e.fields ?? {};
      current = e.current;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, msg, fields, current);
  }
  return (await res.json()) as T;
}
