import { describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, readCookie, SESSION_EXPIRED_EVENT } from "./client";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("apiRequest", () => {
  it("sends same-origin GET requests without a CSRF header", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrftoken=abc123";

    await apiRequest("/api/v1/me/");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
  });

  it("sends Django's CSRF token and a JSON body on POST", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrftoken=abc123";

    await apiRequest("/api/v1/ask/", { method: "POST", body: { question: "headcount?" } });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CSRFToken"]).toBe("abc123");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ question: "headcount?" }));
  });

  it("turns the backend's JSON error contract into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(403, { status: "forbidden", message: "Not your module." })));

    const error = await apiRequest("/api/v1/kpis/run/").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, code: "forbidden", message: "Not your module." });
  });

  it("marks 401 answers as unauthenticated", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { status: "unauthenticated", message: "Log in" })));

    const error = (await apiRequest("/api/v1/me/").catch((e: unknown) => e)) as ApiError;

    expect(error.isUnauthenticated).toBe(true);
  });

  it("announces an ended session, but not a wrong password", async () => {
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);
    try {
      vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { status: "invalid_credentials", message: "x" })));
      const wrongPassword = (await apiRequest("/api/v1/auth/login/").catch((e: unknown) => e)) as ApiError;
      expect(wrongPassword.isUnauthenticated).toBe(false);
      expect(listener).not.toHaveBeenCalled();

      vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { status: "unauthenticated", message: "x" })));
      await apiRequest("/api/v1/kpis/").catch(() => undefined);
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
    }
  });

  it("handles non-JSON error pages (e.g. a proxy's HTML 502)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Bad gateway</html>", { status: 502 })));

    const error = await apiRequest("/api/v1/me/").catch((e: unknown) => e);

    expect(error).toMatchObject({ status: 502, code: "http_502" });
  });

  it("reports an unreachable server as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));

    const error = await apiRequest("/api/v1/me/").catch((e: unknown) => e);

    expect(error).toMatchObject({ status: 0, code: "network" });
  });
});

describe("readCookie", () => {
  it("reads one cookie among several", () => {
    document.cookie = "other=1";
    document.cookie = "csrftoken=t%3Dk";
    expect(readCookie("csrftoken")).toBe("t=k");
    expect(readCookie("missing")).toBeNull();
  });
});
