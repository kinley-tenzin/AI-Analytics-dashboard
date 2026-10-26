import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { overviewFor } from "../test/fixtures";
import { json, mockBackend, renderApp, USERS } from "../test/render";

function tile(label: string) {
  return screen.getByText(label, { selector: ".stat__label" }).closest(".stat") as HTMLElement;
}

describe("Overview", () => {
  it("shows the HR and Accounts indicators returned by the backend", async () => {
    mockBackend({ user: USERS.executive! });
    renderApp("/");

    await screen.findByRole("heading", { name: /Human resources/ });
    expect(within(tile("Active employees")).getByText("16")).toBeInTheDocument();
    expect(within(tile("Departments with active staff")).getByText("3")).toBeInTheDocument();
    expect(within(tile("Employees on approved leave")).getByText("4")).toBeInTheDocument();
    expect(tile("Employees on approved leave")).toHaveTextContent("6 requests · 11.5 days · 1 Oct 2026 – 31 Oct 2026");
    expect(within(tile("Outstanding receivables")).getByText("BTN 166,700.00")).toBeInTheDocument();
    expect(within(tile("Overdue receivables")).getByText("BTN 149,700.00")).toBeInTheDocument();
    expect(within(tile("Overdue payables")).getByText("BTN 31,700.00")).toBeInTheDocument();
  });

  it("never adds amounts in different currencies together", async () => {
    mockBackend({ user: USERS.accounts! });
    renderApp("/");

    const payables = await screen.findByText("Outstanding payables", { selector: ".stat__label" });
    const card = payables.closest(".stat") as HTMLElement;
    expect(within(card).getByText("BTN 37,700.00")).toBeInTheDocument();
    expect(within(card).getByText("INR 1,200.50")).toBeInTheDocument();
  });

  it("shows only the modules of the user's role", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/");

    await screen.findByRole("heading", { name: /Human resources/ });
    expect(screen.queryByRole("heading", { name: /^Accounts$/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Outstanding receivables")).not.toBeInTheDocument();
  });

  it("charts departments largest first and offers a table view", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/");

    const chart = await screen.findByRole("figure", { name: /Active employees by department/ });
    const labels = [...chart.querySelectorAll(".bars__label")].map((e) => e.textContent);
    expect(labels).toEqual(["Sales", "Finance & Accounts", "Operations"]);
    await userEvent.click(within(chart).getByRole("button", { name: /Table/ }));
    const rows = within(within(chart).getByRole("table")).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Sales5");
  });

  it("shows ageing buckets without their sort prefix, including negative credit", async () => {
    mockBackend({ user: USERS.accounts! });
    renderApp("/");

    const chart = await screen.findByRole("figure", { name: /Receivables by ageing/ });
    expect(within(chart).getByText("1-30 days overdue")).toBeInTheDocument();
    expect(within(chart).getByText("Unapplied credit")).toBeInTheDocument();
    expect(within(chart).getByText("BTN -5,000.00")).toBeInTheDocument();
  });

  it("shows the reporting date and refresh age", async () => {
    mockBackend({ user: USERS.executive! });
    renderApp("/");

    expect(await screen.findByText(/Data as of 25 Oct 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Refreshed 4 h ago/)).toBeInTheDocument();
  });

  it("warns about stale and synthetic data", async () => {
    const base = overviewFor(["hr"]);
    mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/overview/": () =>
          json(200, { ...base, summary: { ...base.summary!, stale: true, synthetic: true, hours_since_publication: 70 } }),
      },
    });
    renderApp("/");

    expect(await screen.findByText(/FICTIONAL synthetic demonstration dataset/)).toBeInTheDocument();
    expect(screen.getByText("Synthetic demonstration data")).toBeInTheDocument();
    expect(screen.getByText("Data may be out of date")).toBeInTheDocument();
  });

  it("explains a tile without data instead of showing a number", async () => {
    const base = overviewFor(["hr"]);
    mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/overview/": () =>
          json(200, { ...base, tiles: { ...base.tiles, leave: { status: "no_data", message: "No approved leave in the period." } } }),
      },
    });
    renderApp("/");

    const leave = (await screen.findByText("Employees on approved leave", { selector: ".stat__label" })).closest(".stat") as HTMLElement;
    expect(leave).toHaveTextContent("No data");
    expect(leave).toHaveTextContent("No approved leave in the period.");
  });

  it("offers a retry when the warehouse is unavailable", async () => {
    let fail = true;
    mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/overview/": () =>
          fail
            ? json(503, { status: "error", message: "The warehouse is not reachable right now. Try again later." })
            : json(200, overviewFor(["hr"])),
      },
    });
    renderApp("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("The warehouse is not reachable right now");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findByText("Active employees", { selector: ".stat__label" })).toBeInTheDocument();
  });
});
