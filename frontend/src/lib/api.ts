// Same-origin API client. The Next.js server proxies /api/* to FastAPI,
// and the session lives in an httpOnly cookie, so no tokens are handled here.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Options = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal };

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: string[] };
    const field = first.loc?.slice(-1)[0];
    return field ? `${field}: ${first.msg}` : (first.msg ?? "Invalid input");
  }
  return "Something went wrong";
}

/** What to tell the user when the server gave no usable message of its own. */
function statusMessage(status: number): string {
  if (status === 413) return "That file is too large.";
  if (status === 429) return "Too many attempts. Wait a few minutes and try again.";
  if (status === 502 || status === 503 || status === 504) return "The server is busy or restarting. Try again in a moment.";
  if (status === 404) return "Not found.";
  if (status === 403) return "You don't have access to this.";
  return "Something went wrong";
}

async function failure(res: Response): Promise<ApiError> {
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const data = isJson ? await res.json().catch(() => ({})) : {};
  const detail = (data as { detail?: unknown }).detail;
  return new ApiError(res.status, detail === undefined ? statusMessage(res.status) : detailMessage(detail));
}

function signedOut(path: string) {
  if (typeof window !== "undefined" && !path.startsWith("/auth/")) {
    // Outside React (no router here): a full navigation to the login page is intended. It also
    // drops everything cached for the previous session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
  }
}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`/api${path}`, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? (opts.body || opts.form ? "POST" : "GET"), credentials: "same-origin", signal: opts.signal };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers = { "content-type": "application/json" };
  }
  const res = await send(path, init);
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    if (res.status === 401) signedOut(path);
    throw await failure(res);
  }
  if (!(res.headers.get("content-type") ?? "").includes("application/json")) {
    throw new ApiError(res.status, "The server sent an answer the app couldn't read. Try again.");
  }
  return (await res.json()) as T;
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

export type StreamEvent =
  | { type: "text"; delta: string }
  | { type: "status"; text: string }
  | { type: "done" }
  | { type: "error"; message: string };

/** POST and consume a Server-Sent Events response, calling onEvent for each event.
 *  Rejects if the stream ends without a `done` or `error` event (a dropped connection or a
 *  proxy timeout), so a turn can never vanish silently. */
export async function streamPost(path: string, body: unknown, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await send(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) signedOut(path);
    throw await failure(res);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let finished = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("");
        if (!data) continue;
        const event = JSON.parse(data) as StreamEvent;
        if (event.type === "done" || event.type === "error") finished = true;
        onEvent(event);
      }
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "The connection was lost before the reply finished. Your message wasn't saved; please send it again.");
  } finally {
    reader.cancel().catch(() => {});
  }
  if (!finished) throw new ApiError(0, "The reply was cut off before it finished. Your message wasn't saved; please send it again.");
}
