import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { adminDashboards } from "../test/fixtures";
import { json, mockBackend, renderApp, USERS } from "../test/render";

function reportCard(title: string) {
  return screen.getByRole("heading", { name: title }).closest("section") as HTMLElement;
}

describe("Reports", () => {
  it("lists only the reports of the user's modules", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/reports");

    expect(await screen.findByRole("heading", { name: "Active headcount by department" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ageing of open balances" })).not.toBeInTheDocument();
  });

  it("builds the CSV download link from the chosen date", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/reports");

    const card = reportCard(await screen.findByRole("heading", { name: "Active headcount by department" }).then((h) => h.textContent!));
    const link = within(card).getByRole("link", { name: /Download CSV/ });
    expect(link).toHaveAttribute("href", "/api/v1/portal/reports/headcount-by-department.csv");
    expect(link).toHaveAttribute("download");
    await userEvent.type(within(card).getByLabelText("As of"), "2026-10-24");
    expect(link).toHaveAttribute("href", "/api/v1/portal/reports/headcount-by-department.csv?as_of=2026-10-24");
  });

  it("offers a period for period reports", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/reports");

    const card = reportCard((await screen.findByRole("heading", { name: "Approved leave by leave type" })).textContent!);
    expect(within(card).getByLabelText("From")).toBeInTheDocument();
    expect(within(card).getByLabelText("To")).toBeInTheDocument();
    expect(within(card).queryByLabelText("As of")).not.toBeInTheDocument();
  });

  it("previews a report as a chart and table", async () => {
    const fetchMock = mockBackend({ user: USERS.accounts! });
    renderApp("/reports");

    const card = reportCard((await screen.findByRole("heading", { name: "Ageing of open balances" })).textContent!);
    await userEvent.type(within(card).getByLabelText("As of"), "2026-10-25");
    await userEvent.click(within(card).getByRole("button", { name: /Preview/ }));

    expect(await within(card).findByRole("table")).toHaveTextContent("1-30 days overdue");
    expect(within(card).getByText("As of 25 Oct 2026")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).startsWith("/api/v1/portal/reports/ageing/"));
    expect(String(call![0])).toBe("/api/v1/portal/reports/ageing/?as_of=2026-10-25");
  });

  it("shows the backend's message for an invalid date", async () => {
    mockBackend({
      user: USERS.accounts!,
      routes: {
        "/api/v1/portal/reports/ageing/": () =>
          json(400, { status: "invalid_filter", message: "as_of must be a date in YYYY-MM-DD format" }),
      },
    });
    renderApp("/reports");

    const card = reportCard((await screen.findByRole("heading", { name: "Ageing of open balances" })).textContent!);
    await userEvent.click(within(card).getByRole("button", { name: /Preview/ }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("as_of must be a date");
  });
});

describe("Administration", () => {
  it("shows platform status with stale modules flagged", async () => {
    mockBackend({ user: USERS.admin! });
    renderApp("/admin");

    expect(await screen.findByText("Embedding service account works")).toBeInTheDocument();
    expect(screen.getByText("live ERP data")).toBeInTheDocument();
    expect(screen.getByText("Deterministic rules interpreter (no language model)")).toBeInTheDocument();
    const accounts = screen.getByRole("heading", { name: "Accounts data" }).closest("section") as HTMLElement;
    expect(within(accounts).getByText("(problem)")).toBeInTheDocument(); // 40 h > stale limit
  });

  it("lists users with roles, modules and branches and links to user management", async () => {
    mockBackend({ user: USERS.admin! });
    renderApp("/admin");

    const table = await screen.findByRole("table", { name: "Users, roles and modules" });
    expect(within(table).getByText("Branch Manager")).toBeInTheDocument();
    expect(within(table).getByText("odoo:odoo-sandbox:1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Django admin/ })).toHaveAttribute("href", "/admin/auth/user/");
  });
});

describe("Manage dashboards (ADR-044)", () => {
  it("toggles a dashboard's visibility through the API", async () => {
    let dashboards = adminDashboards();
    const fetchMock = mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/manage/dashboards/hr-leave-planner/": () => {
          dashboards = dashboards.map((d) => (d.key === "hr-leave-planner" ? { ...d, visible: true } : d));
          return json(200, { status: "ok", dashboard: dashboards[1] });
        },
        "/api/v1/portal/manage/dashboards/": () => json(200, { status: "ok", dashboards, author_domains: ["hr"] }),
      },
    });
    renderApp("/manage");

    const toggle = await screen.findByRole("button", { name: /^Show Leave planner to HR users/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);

    expect(await screen.findByRole("status")).toHaveTextContent("Leave planner is now visible.");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Show Leave planner to HR users/ })).toHaveAttribute("aria-pressed", "true"));
    const patch = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH") as [string, RequestInit];
    expect(JSON.parse(String(patch[1].body))).toEqual({ visible: true });
  });

  it("only customer dashboards can be removed", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/manage");

    const table = (await screen.findByRole("table", { name: "Dashboards shown in the website" })) as HTMLElement;
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]!).queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
    expect(within(rows[2]!).getByRole("button", { name: /Remove/ })).toBeInTheDocument();
  });

  it("publishes a manager's dashboard and shows the backend's refusal", async () => {
    const fetchMock = mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/manage/dashboards/": (init) =>
          init?.method === "POST"
            ? json(400, { status: "invalid_dashboard", message: "The dashboard uses data outside the hr module: kpi_receivables_payables." })
            : json(200, { status: "ok", dashboards: adminDashboards(), author_domains: ["hr"] }),
      },
    });
    renderApp("/manage");

    await userEvent.type(await screen.findByLabelText("Superset dashboard number or slug"), "creator-mixed");
    await userEvent.click(screen.getByRole("button", { name: /Publish dashboard/ }));

    expect(await screen.findByText(/uses data outside the hr module/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "POST") as [string, RequestInit];
    expect(JSON.parse(String(post[1].body))).toEqual({ superset_ref: "creator-mixed", domain: "hr" });
  });

  it("offers the HR Manager only the HR page", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/manage");

    const select = await screen.findByLabelText("Module page");
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["HR"]);
    expect(screen.getByRole("table", { name: "Dashboards shown in the website" })).not.toHaveTextContent("Accounts");
  });

  it("is not available to the executive", async () => {
    mockBackend({ user: USERS.executive! });
    renderApp("/manage");

    expect(await screen.findByRole("heading", { name: "You do not have access to this page" })).toBeInTheDocument();
  });

  it("links the administration page to dashboard management", async () => {
    mockBackend({ user: USERS.admin! });
    renderApp("/admin");

    const main = await screen.findByRole("main");
    expect(await within(main).findByRole("link", { name: /Manage dashboards/ })).toHaveAttribute("href", "/app/manage");
  });
});
