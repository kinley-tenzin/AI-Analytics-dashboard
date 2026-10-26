import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockBackend, renderApp, USERS } from "../test/render";

// The real SDK needs a running Superset; the tests check what the page asks it to do.
const sdk = vi.hoisted(() => ({
  embedDashboard: vi.fn(),
  unmount: vi.fn(),
}));
vi.mock("@superset-ui/embedded-sdk", () => ({ embedDashboard: sdk.embedDashboard }));

beforeEach(() => {
  sdk.embedDashboard.mockReset();
  sdk.unmount.mockReset();
  sdk.embedDashboard.mockImplementation(async ({ mountPoint }: { mountPoint: HTMLElement }) => {
    const iframe = document.createElement("iframe");
    iframe.title = "embedded";
    mountPoint.appendChild(iframe);
    return { unmount: sdk.unmount, getScrollSize: async () => ({ width: 1000, height: 900 }) };
  });
});

type EmbedParams = {
  id: string;
  supersetDomain: string;
  fetchGuestToken: () => Promise<string>;
  referrerPolicy: string;
  dashboardUiConfig: { hideTitle: boolean; hideChartControls: boolean; filters: { visible: boolean } };
};

function lastEmbed(): EmbedParams {
  return sdk.embedDashboard.mock.calls.at(-1)![0] as EmbedParams;
}

describe("HR and Accounts analytics pages", () => {
  it("embeds the module's dashboard with a token minted by the backend", async () => {
    const fetchMock = mockBackend({ user: USERS.hr! });
    renderApp("/hr");

    await waitFor(() => expect(sdk.embedDashboard).toHaveBeenCalledTimes(1));
    const params = lastEmbed();
    expect(params.id).toBe("uuid-hr");
    expect(params.supersetDomain).toBe("http://127.0.0.1:8088");
    expect(params.referrerPolicy).toBe("strict-origin-when-cross-origin");
    expect(params.dashboardUiConfig).toMatchObject({ hideTitle: true, hideChartControls: false, filters: { visible: true } });
    const tokenCalls = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/guest-token/"));
    expect(tokenCalls).toHaveLength(1);
    expect((tokenCalls[0]![1] as RequestInit).method).toBe("POST");
    expect(await screen.findByTitle("embedded")).toBeInTheDocument();
  });

  it("uses the first token once and asks the backend again for renewals", async () => {
    const fetchMock = mockBackend({ user: USERS.accounts! });
    renderApp("/accounts");
    await waitFor(() => expect(sdk.embedDashboard).toHaveBeenCalled());
    const { fetchGuestToken } = lastEmbed();

    const first = await fetchGuestToken();
    const renewed = await fetchGuestToken();

    expect(first).not.toBe(renewed);
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/guest-token/"))).toHaveLength(2);
  });

  it("shows the backend's refusal instead of a dashboard", async () => {
    mockBackend({
      user: USERS.branch!,
      routes: {
        "/api/v1/portal/dashboards/hr/guest-token/": () =>
          json(403, { status: "forbidden", message: "No branch is assigned to your account." }),
      },
    });
    renderApp("/hr");

    expect(await screen.findByRole("alert")).toHaveTextContent("No branch is assigned to your account.");
    expect(screen.getByRole("heading", { name: "This dashboard is not available to you" })).toBeInTheDocument();
    expect(sdk.embedDashboard).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Try again/ })).not.toBeInTheDocument();
  });

  it("offers a retry when the dashboard service is down", async () => {
    let down = true;
    mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/dashboards/hr/guest-token/": () =>
          down
            ? json(503, { status: "bi_unavailable", message: "The dashboard service is not reachable right now." })
            : json(200, { status: "ok", token: "t", embedded_id: "uuid-hr", superset_url: "http://127.0.0.1:8088", expires_in: 300, branch_restricted: false }),
      },
    });
    renderApp("/hr");

    expect(await screen.findByRole("alert")).toHaveTextContent("not reachable");
    down = false;
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await waitFor(() => expect(sdk.embedDashboard).toHaveBeenCalledTimes(1));
  });

  it("unmounts the dashboard when leaving the page", async () => {
    mockBackend({ user: USERS.executive! });
    const { router } = renderApp("/hr");
    await waitFor(() => expect(sdk.embedDashboard).toHaveBeenCalled());
    await screen.findByTitle("embedded");

    await router.navigate("/accounts");

    await waitFor(() => expect(sdk.unmount).toHaveBeenCalled());
    await waitFor(() => expect(lastEmbed().id).toBe("uuid-accounts"));
  });

  it("gives the module's manager a clearly labelled link to the native editor", async () => {
    mockBackend({ user: USERS.hr! });
    renderApp("/hr");
    expect(await screen.findByRole("link", { name: /Manage dashboards/ })).toHaveAttribute("href", "/app/manage");

    const link = await screen.findByRole("link", { name: /Edit in Superset \(separate sign-in\)/ });
    expect(link).toHaveAttribute("href", "http://127.0.0.1:8088/superset/dashboard/druksmart-hr/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("does not show the editor link to viewers", async () => {
    mockBackend({ user: USERS.executive! });
    renderApp("/hr");
    await waitFor(() => expect(sdk.embedDashboard).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /Edit in Superset/ })).not.toBeInTheDocument();
  });

  it("offers tabs when a module has several dashboards", async () => {
    mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/dashboards/": () =>
          json(200, {
            status: "ok",
            can_author: false,
            superset_url: "http://127.0.0.1:8088",
            dashboards: [
              { key: "hr", title: "HR Overview", description: "", domain: "hr", kind: "official" },
              { key: "hr-leave", title: "Leave planner", description: "", domain: "hr", kind: "custom" },
            ],
          }),
      },
    });
    renderApp("/hr");

    const tab = await screen.findByRole("tab", { name: /Leave planner/ });
    expect(screen.getByRole("tab", { name: "HR Overview" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(tab);
    expect(tab).toHaveAttribute("aria-selected", "true");
  });

  it("explains when no dashboard is published", async () => {
    mockBackend({
      user: USERS.hr!,
      routes: {
        "/api/v1/portal/dashboards/": () =>
          json(200, { status: "ok", can_author: false, superset_url: "x", dashboards: [] }),
      },
    });
    renderApp("/hr");

    expect(await screen.findByText("No dashboard is published for this module")).toBeInTheDocument();
    expect(sdk.embedDashboard).not.toHaveBeenCalled();
  });
});
