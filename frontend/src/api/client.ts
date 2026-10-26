/**
 * Same-origin JSON client for the Django API (/api/v1/...).
 *
 * The browser sends the Django session cookie automatically (same origin). Unsafe methods also
 * send Django's CSRF token, read from the `csrftoken` cookie that Django sets when it serves the
 * app. Errors follow the backend's JSON contract `{ "status": <code>, "message": <text> }`.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** The session is missing or has ended (not: wrong password at sign-in). */
  get isUnauthenticated(): boolean {
    return this.status === 401 && this.code === "unauthenticated";
  }
}

/** Fired on `window` when an API call finds that the Django session has ended. */
export const SESSION_EXPIRED_EVENT = "druksmart:session-expired";

export function readCookie(name: string): string | null {
  for (const part of document.cookie ? document.cookie.split(";") : []) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export function csrfToken(): string | null {
  return readCookie("csrftoken");
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["X-CSRFToken"] = token;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network", "The DrukSmart server could not be reached.");
  }

  let data: unknown = null;
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const payload = (data ?? {}) as { status?: unknown; message?: unknown };
    const code = typeof payload.status === "string" ? payload.status : `http_${response.status}`;
    const message =
      typeof payload.message === "string"
        ? payload.message
        : `The server answered with an unexpected error (HTTP ${response.status}).`;
    const apiError = new ApiError(response.status, code, message);
    if (apiError.isUnauthenticated) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    throw apiError;
  }
  if (data === null) {
    throw new ApiError(response.status, "invalid_response", "The server sent an unreadable answer.");
  }
  return data as T;
}
