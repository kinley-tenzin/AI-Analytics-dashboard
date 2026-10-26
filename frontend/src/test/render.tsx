import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import type { UserScope } from "../api/types";
import { SessionProvider } from "../auth/session";
import { BASENAME, routes } from "../routes";
import {
  ADMIN_STATUS,
  ADMIN_USERS,
  adminDashboards,
  assistantInfoFor,
  dashboardsFor,
  overviewFor,
  reportPreview,
  reportsFor,
} from "./fixtures";

export const USERS: Record<string, UserScope> = {
  hr: { username: "demo_hr", roles: ["DrukSmart HR Manager"], domains: ["hr"], branch_restricted: false, author_domains: ["hr"] },
  accounts: {
    username: "demo_accounts",
    roles: ["DrukSmart Accounts Manager"],
    domains: ["accounts"],
    branch_restricted: false,
    author_domains: ["accounts"],
  },
  executive: {
    username: "demo_executive",
    roles: ["DrukSmart Executive"],
    domains: ["accounts", "hr"],
    branch_restricted: false,
    author_domains: [],
  },
  branch: {
    username: "demo_branch",
    roles: ["DrukSmart Branch Manager"],
    domains: ["accounts", "hr"],
    branch_restricted: true,
    author_domains: [],
  },
  admin: {
    username: "admin",
    roles: ["Administrator"],
    domains: ["accounts", "hr"],
    branch_restricted: false,
    author_domains: ["accounts", "hr"],
  },
  none: { username: "new_user", roles: [], domains: [], branch_restricted: false, author_domains: [] },
};

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const session = (user: UserScope | null) => ({ status: "ok", authenticated: !!user, user });

interface FakeBackend {
  /** Who is signed in when the app starts: a user, signed out, or the server is unreachable. */
  user: UserScope | "anonymous" | "down";
  /** Answer to POST /api/v1/auth/login/ (default: sign in as `loginAs` or reject). */
  login?: (body: { username: string; password: string }) => Response;
  loginAs?: UserScope;
  /** Extra routes, e.g. { "/api/v1/kpis/": () => json(401, ...) }. */
  routes?: Record<string, (init?: RequestInit) => Response>;
}

/** A fake Django backend for the app's same-origin API calls. Returns the fetch mock. */
export function mockBackend(config: FakeBackend) {
  let current: UserScope | null = typeof config.user === "object" ? config.user : null;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (config.user === "down") throw new TypeError("Failed to fetch");
    if (url.startsWith("/api/v1/auth/session/")) return json(200, session(current));
    if (url.startsWith("/api/v1/auth/login/")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (config.login) {
        const response = config.login(body);
        if (response.ok) current = config.loginAs ?? null;
        return response;
      }
      if (config.loginAs && body.password === "correct-horse") {
        current = config.loginAs;
        return json(200, session(current));
      }
      return json(401, { status: "invalid_credentials", message: "Username or password is incorrect." });
    }
    if (url.startsWith("/api/v1/auth/logout/")) {
      current = null;
      return json(200, session(null));
    }
    const route = Object.entries(config.routes ?? {}).find(([path]) => url.startsWith(path));
    if (route) return route[1](init);
    if (url.startsWith("/api/v1/portal/overview/") && current) return json(200, overviewFor(current.domains));
    if (url.startsWith("/api/v1/portal/dashboards/") && url.endsWith("/guest-token/") && current) {
      const key = url.split("/")[5];
      return json(200, {
        status: "ok",
        token: `token-${key}-${fetchMock.mock.calls.length}`,
        embedded_id: `uuid-${key}`,
        superset_url: "http://127.0.0.1:8088",
        expires_in: 300,
        branch_restricted: current.branch_restricted,
      });
    }
    if (url.startsWith("/api/v1/portal/dashboards/") && current) return json(200, dashboardsFor(current));
    if (url.startsWith("/api/v1/portal/assistant/") && current) return json(200, assistantInfoFor(current));
    if (url === "/api/v1/portal/reports/" && current) return json(200, reportsFor(current));
    if (url.startsWith("/api/v1/portal/reports/") && current) {
      const key = url.split("/")[5]!.split("?")[0]!;
      return json(200, reportPreview(key));
    }
    if (url.startsWith("/api/v1/portal/admin/status/")) return json(200, ADMIN_STATUS);
    if (url === "/api/v1/portal/manage/dashboards/" && current)
      return json(200, {
        status: "ok",
        dashboards: adminDashboards().filter((d) => current!.author_domains.includes(d.domain)),
        author_domains: current.author_domains,
      });
    if (url.startsWith("/api/v1/portal/admin/users/")) return json(200, ADMIN_USERS);
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Shorthand: start with this user signed in (or signed out / server down). */
export function mockMe(user: UserScope | "anonymous" | "down") {
  return mockBackend({ user });
}

/** Render the real route table at an in-app path (e.g. "/hr"). */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { basename: BASENAME, initialEntries: [`${BASENAME}${path}`] });
  const result = render(
    <SessionProvider>
      <RouterProvider router={router} />
    </SessionProvider>,
  );
  return { ...result, router };
}
