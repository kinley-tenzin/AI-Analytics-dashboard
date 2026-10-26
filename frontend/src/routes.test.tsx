import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockMe, renderApp, USERS } from "./test/render";

function navLinks() {
  const nav = screen.getByRole("navigation", { name: "Main" });
  return within(nav)
    .getAllByRole("link")
    .map((a) => a.textContent);
}

describe("session handling", () => {
  it("sends an anonymous visitor to the sign-in page and keeps the requested page", async () => {
    mockMe("anonymous");
    const { router } = renderApp("/accounts");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/login");
    expect(router.state.location.search).toBe("?next=%2Faccounts");
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });

  it("shows a retryable error when the backend cannot be reached", async () => {
    const fetchMock = mockMe("down");
    renderApp("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be reached");
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("sends a signed-in user away from the sign-in page", async () => {
    mockMe(USERS.hr!);
    const { router } = renderApp("/login?next=/hr");

    expect(await screen.findByRole("heading", { level: 1, name: "HR Analytics" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/hr");
  });
});

describe("role-aware navigation", () => {
  it.each([
    ["hr", ["Overview", "HR Analytics", "Ask AI", "Reports", "Manage dashboards"]],
    ["accounts", ["Overview", "Accounts Analytics", "Ask AI", "Reports", "Manage dashboards"]],
    ["executive", ["Overview", "HR Analytics", "Accounts Analytics", "Ask AI", "Reports"]],
    ["admin", ["Overview", "HR Analytics", "Accounts Analytics", "Ask AI", "Reports", "Manage dashboards", "Administration"]],
    ["none", ["Overview"]],
  ])("%s user sees only their pages", async (key, expected) => {
    mockMe(USERS[key]!);
    renderApp("/");

    await screen.findByRole("heading", { level: 1, name: "Overview" });
    expect(navLinks()).toEqual(expected);
  });

  it("denies a page outside the user's role", async () => {
    mockMe(USERS.hr!);
    renderApp("/accounts");

    expect(await screen.findByRole("heading", { name: "You do not have access to this page" })).toBeInTheDocument();
  });

  it("denies administration to non-administrators", async () => {
    mockMe(USERS.executive!);
    renderApp("/admin");

    expect(await screen.findByRole("heading", { name: "You do not have access to this page" })).toBeInTheDocument();
  });

  it("explains when no module is assigned", async () => {
    mockMe(USERS.none!);
    renderApp("/");

    expect(await screen.findByText("No analytics modules are assigned to you")).toBeInTheDocument();
  });

  it("marks the branch restriction in the header", async () => {
    mockMe(USERS.branch!);
    renderApp("/");

    expect(await screen.findByText(/branch-restricted/)).toBeInTheDocument();
  });
});

describe("routing", () => {
  it.each([
    ["/", "Overview"],
    ["/hr", "HR Analytics"],
    ["/accounts", "Accounts Analytics"],
    ["/ask", "Ask AI"],
    ["/reports", "Reports"],
    ["/manage", "Manage dashboards"],
    ["/admin", "Administration"],
  ])("%s renders %s", async (path, title) => {
    mockMe(USERS.admin!);
    renderApp(path);

    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe(`${title} · DrukSmart Analytics`));
  });

  it("shows a not-found page inside the app for unknown paths", async () => {
    mockMe(USERS.hr!);
    renderApp("/no-such-page");

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("navigates with the sidebar and highlights the current page", async () => {
    mockMe(USERS.executive!);
    const { router } = renderApp("/");
    await screen.findByRole("heading", { level: 1, name: "Overview" });

    const nav = screen.getByRole("navigation", { name: "Main" });
    await userEvent.click(within(nav).getByRole("link", { name: "Accounts Analytics" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Accounts Analytics" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/accounts");
    expect(within(nav).getByRole("link", { name: "Accounts Analytics" })).toHaveAttribute("aria-current", "page");
  });

  it("has no unfinished placeholder pages left", async () => {
    for (const path of ["/", "/hr", "/accounts", "/ask", "/reports", "/manage", "/admin"]) {
      mockMe(USERS.admin!);
      const { unmount } = renderApp(path);
      await screen.findByRole("heading", { level: 1 });
      expect(screen.queryByText(/Not implemented yet/)).not.toBeInTheDocument();
      unmount();
    }
  });
});
