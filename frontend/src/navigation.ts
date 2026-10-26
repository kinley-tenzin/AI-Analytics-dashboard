import { FileText, LayoutDashboard, LayoutGrid, Landmark, MessageSquareText, Settings, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { Requirement } from "./auth/access";

export type PageKey = "overview" | "hr" | "accounts" | "ask" | "reports" | "manage" | "admin";

export interface NavItem {
  key: PageKey;
  /** Path inside the app (the router adds the /app basename). */
  path: string;
  label: string;
  description: string;
  icon: LucideIcon;
  requires: Requirement;
}

/** The single list of the app's pages: used by the sidebar, the routes and the page headers. */
export const PAGES: Record<PageKey, NavItem> = {
  overview: {
    key: "overview",
    path: "/",
    label: "Overview",
    description: "Key HR and Accounts indicators you are authorised to see.",
    icon: LayoutDashboard,
    // Every signed-in user lands here; it explains when no module is assigned.
    requires: { kind: "authenticated" },
  },
  hr: {
    key: "hr",
    path: "/hr",
    label: "HR Analytics",
    description: "Headcount, departments and leave, from the governed HR dashboard.",
    icon: Users,
    requires: { kind: "domain", domain: "hr" },
  },
  accounts: {
    key: "accounts",
    path: "/accounts",
    label: "Accounts Analytics",
    description: "Receivables, payables, overdue balances and ageing.",
    icon: Landmark,
    requires: { kind: "domain", domain: "accounts" },
  },
  ask: {
    key: "ask",
    path: "/ask",
    label: "Ask AI",
    description: "Ask HR and Accounts questions, answered only from approved KPI functions.",
    icon: MessageSquareText,
    requires: { kind: "any-domain" },
  },
  reports: {
    key: "reports",
    path: "/reports",
    label: "Reports",
    description: "Download the analytical results you are permitted to export.",
    icon: FileText,
    requires: { kind: "any-domain" },
  },
  manage: {
    key: "manage",
    path: "/manage",
    label: "Manage dashboards",
    description: "Publish, show or hide the dashboards of your module's page.",
    icon: LayoutGrid,
    requires: { kind: "author" },
  },
  admin: {
    key: "admin",
    path: "/admin",
    label: "Administration",
    description: "Platform status, users and roles.",
    icon: Settings,
    requires: { kind: "admin" },
  },
};

export const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  { title: "Analytics", items: [PAGES.overview, PAGES.hr, PAGES.accounts] },
  { title: "Assistant", items: [PAGES.ask] },
  { title: "Reporting", items: [PAGES.reports] },
  { title: "Platform", items: [PAGES.manage, PAGES.admin] },
];
