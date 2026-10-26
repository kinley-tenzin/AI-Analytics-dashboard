import type { ReactNode } from "react";
import type { RouteObject } from "react-router";

import { RequireAccess, RequireSession } from "./auth/guards";
import { AppShell } from "./components/layout/AppShell";
import type { PageKey } from "./navigation";
import { PAGES } from "./navigation";
import { AdminPage } from "./pages/AdminPage";
import { AccountsAnalyticsPage, HrAnalyticsPage } from "./pages/AnalyticsPages";
import { AskAiPage } from "./pages/AskAiPage";
import { LoginPage } from "./pages/LoginPage";
import { ManageDashboardsPage } from "./pages/ManageDashboardsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReportsPage } from "./pages/ReportsPage";
import { RouteErrorPage } from "./pages/RouteErrorPage";

/** Router basename: Django serves the built app under /app/ (see vite.config.ts `base`). */
export const BASENAME = "/app";

const PAGE_ELEMENTS: Record<PageKey, ReactNode> = {
  overview: <OverviewPage />,
  hr: <HrAnalyticsPage />,
  accounts: <AccountsAnalyticsPage />,
  ask: <AskAiPage />,
  reports: <ReportsPage />,
  manage: <ManageDashboardsPage />,
  admin: <AdminPage />,
};

function pageRoute(key: PageKey): RouteObject {
  const page = PAGES[key];
  const element = <RequireAccess requires={page.requires}>{PAGE_ELEMENTS[key]}</RequireAccess>;
  return page.path === "/" ? { index: true, element } : { path: page.path.slice(1), element };
}

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage />, errorElement: <RouteErrorPage /> },
  {
    path: "/",
    element: (
      <RequireSession>
        <AppShell />
      </RequireSession>
    ),
    errorElement: <RouteErrorPage />,
    children: [...(Object.keys(PAGES) as PageKey[]).map(pageRoute), { path: "*", element: <NotFoundPage /> }],
  },
];
