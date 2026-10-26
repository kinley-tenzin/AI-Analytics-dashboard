import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { apiRequest } from "../api/client";
import { json, mockBackend, renderApp, USERS } from "../test/render";

async function fillAndSubmit(username: string, password: string) {
  await userEvent.type(await screen.findByLabelText("Username"), username);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

function loginCall(fetchMock: ReturnType<typeof mockBackend>) {
  return fetchMock.mock.calls.find(([url]) => String(url).startsWith("/api/v1/auth/login/")) as
    | [string, RequestInit]
    | undefined;
}

describe("sign-in form", () => {
  it("signs in through the JSON API with the CSRF token and opens the requested page", async () => {
    document.cookie = "csrftoken=tok123";
    const fetchMock = mockBackend({ user: "anonymous", loginAs: USERS.accounts });
    const { router } = renderApp("/accounts");

    await fillAndSubmit("demo_accounts", "correct-horse");

    expect(await screen.findByRole("heading", { level: 1, name: "Accounts Analytics" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/accounts");
    const [, init] = loginCall(fetchMock)!;
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok123");
    expect(JSON.parse(String(init.body))).toEqual({ username: "demo_accounts", password: "correct-horse" });
  });

  it("shows the backend's generic message, clears the password and stays on the page", async () => {
    mockBackend({ user: "anonymous", loginAs: USERS.hr });
    const { router } = renderApp("/");

    await fillAndSubmit("demo_hr", "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent("Username or password is incorrect.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Username")).toHaveValue("demo_hr");
    expect(screen.getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");
    expect(router.state.location.pathname).toBe("/app/login");
  });

  it("explains a lock-out after repeated failures", async () => {
    mockBackend({
      user: "anonymous",
      login: () =>
        json(429, {
          status: "throttled",
          message: "Too many failed sign-in attempts. Try again in 15 minute(s) or ask the administrator.",
          retry_after: 900,
        }),
    });
    renderApp("/");

    await fillAndSubmit("demo_hr", "whatever");

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many failed sign-in attempts");
  });

  it("validates empty fields without calling the server", async () => {
    const fetchMock = mockBackend({ user: "anonymous" });
    renderApp("/");

    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Enter your username and password.");
    expect(loginCall(fetchMock)).toBeUndefined();
  });

  it("reports an unreachable server while signing in", async () => {
    mockBackend({
      user: "anonymous",
      login: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    renderApp("/");

    await fillAndSubmit("demo_hr", "pw");

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be reached");
  });

  it("disables the form while signing in", async () => {
    let release: (r: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => (release = resolve));
    const fetchMock = mockBackend({ user: "anonymous", loginAs: USERS.hr });
    fetchMock.mockImplementationOnce(fetchMock.getMockImplementation()!); // session check
    renderApp("/");
    await screen.findByLabelText("Username");
    fetchMock.mockImplementationOnce(() => pending);

    await fillAndSubmit("demo_hr", "correct-horse");

    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    expect(screen.getByLabelText("Username")).toBeDisabled();
    await act(async () => release(json(200, { status: "ok", authenticated: true, user: USERS.hr })));
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
  });

  it("can show and hide the password", async () => {
    mockBackend({ user: "anonymous" });
    renderApp("/");
    const password = await screen.findByLabelText("Password");

    expect(password).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
  });

  it("ignores an unsafe next parameter", async () => {
    mockBackend({ user: "anonymous", loginAs: USERS.hr });
    const { router } = renderApp("/login?next=//evil.example/");

    await fillAndSubmit("demo_hr", "correct-horse");

    await screen.findByRole("heading", { level: 1, name: "Overview" });
    expect(router.state.location.pathname).toBe("/app");
  });
});

describe("sign-out and session expiry", () => {
  it("signs out through the API with the CSRF token and returns to the sign-in page", async () => {
    document.cookie = "csrftoken=tok456";
    const fetchMock = mockBackend({ user: USERS.hr! });
    const { router } = renderApp("/hr");

    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/login");
    const call = fetchMock.mock.calls.find(([url]) => String(url).startsWith("/api/v1/auth/logout/")) as [
      string,
      RequestInit,
    ];
    expect(call[1].method).toBe("POST");
    expect((call[1].headers as Record<string, string>)["X-CSRFToken"]).toBe("tok456");
  });

  it("returns to sign-in, keeping the page, when an API call finds the session ended", async () => {
    mockBackend({
      user: USERS.executive!,
      routes: { "/api/v1/kpis/": () => json(401, { status: "unauthenticated", message: "Log in first." }) },
    });
    const { router } = renderApp("/accounts");
    await screen.findByRole("heading", { level: 1, name: "Accounts Analytics" });

    await act(async () => {
      await apiRequest("/api/v1/kpis/").catch(() => undefined);
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Your session has ended");
    expect(router.state.location.pathname).toBe("/app/login");
    expect(router.state.location.search).toBe("?next=%2Faccounts");
  });

  it("does not treat a wrong password as an ended session", async () => {
    mockBackend({ user: "anonymous" });
    renderApp("/");

    await fillAndSubmit("x", "y");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("incorrect");
    await waitFor(() => expect(screen.queryByText(/session has ended/)).not.toBeInTheDocument());
  });

  it("shows the signed-in user's name and role after sign-in", async () => {
    mockBackend({ user: "anonymous", loginAs: USERS.branch });
    renderApp("/");

    await fillAndSubmit("demo_branch", "correct-horse");

    const header = await screen.findByRole("banner");
    expect(within(header).getByText("demo_branch")).toBeInTheDocument();
    expect(within(header).getByText(/Branch Manager · branch-restricted/)).toBeInTheDocument();
  });
});
