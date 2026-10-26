import { apiRequest } from "./client";
import type {
  AdminDashboard,
  AdminStatus,
  AdminUsersResponse,
  AskResponse,
  AssistantInfo,
  DashboardsResponse,
  Domain,
  GuestTokenResponse,
  OverviewResponse,
  ReportPreview,
  ReportsResponse,
  SessionResponse,
  UserScope,
} from "./types";

/** The signed-in user, or null when signed out (a normal 200 answer, not an error). */
export async function fetchSession(signal?: AbortSignal): Promise<UserScope | null> {
  const data = await apiRequest<SessionResponse>("/api/v1/auth/session/", { signal });
  return data.authenticated ? data.user : null;
}

export async function signIn(username: string, password: string): Promise<UserScope> {
  const data = await apiRequest<SessionResponse>("/api/v1/auth/login/", {
    method: "POST",
    body: { username, password },
  });
  if (!data.user) throw new Error("Sign-in answer without a user");
  return data.user;
}

export async function signOut(): Promise<void> {
  await apiRequest<SessionResponse>("/api/v1/auth/logout/", { method: "POST" });
}

export async function fetchOverview(signal?: AbortSignal): Promise<OverviewResponse> {
  return apiRequest<OverviewResponse>("/api/v1/portal/overview/", { signal });
}

export async function fetchDashboards(signal?: AbortSignal): Promise<DashboardsResponse> {
  return apiRequest<DashboardsResponse>("/api/v1/portal/dashboards/", { signal });
}

/** A short-lived Superset guest token for ONE dashboard, minted by Django for this user. */
export async function fetchGuestToken(key: string): Promise<GuestTokenResponse> {
  return apiRequest<GuestTokenResponse>(`/api/v1/portal/dashboards/${encodeURIComponent(key)}/guest-token/`, {
    method: "POST",
  });
}

export async function fetchAssistantInfo(signal?: AbortSignal): Promise<AssistantInfo> {
  return apiRequest<AssistantInfo>("/api/v1/portal/assistant/", { signal });
}

/** Ask the bounded assistant; it answers only through approved KPI functions. */
export async function askQuestion(question: string): Promise<AskResponse> {
  return apiRequest<AskResponse>("/api/v1/ask/", { method: "POST", body: { question } });
}

// ---- Reports (portal/reports.py)
export type ReportParams = Partial<Record<"as_of" | "period_start" | "period_end", string>>;

function query(params: ReportParams): string {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
  return q.toString() ? `?${q}` : "";
}

export async function fetchReports(signal?: AbortSignal): Promise<ReportsResponse> {
  return apiRequest<ReportsResponse>("/api/v1/portal/reports/", { signal });
}

export async function previewReport(key: string, params: ReportParams): Promise<ReportPreview> {
  return apiRequest<ReportPreview>(`/api/v1/portal/reports/${encodeURIComponent(key)}/${query(params)}`);
}

/** Same-origin download link; the browser sends the session cookie. */
export function reportCsvUrl(key: string, params: ReportParams): string {
  return `/api/v1/portal/reports/${encodeURIComponent(key)}.csv${query(params)}`;
}

// ---- Administration (portal/admin_api.py; administrator only)
export async function fetchAdminStatus(signal?: AbortSignal): Promise<AdminStatus> {
  return apiRequest<AdminStatus>("/api/v1/portal/admin/status/", { signal });
}

// ---- Dashboard management (portal/admin_api.py; module managers + administrator, ADR-044)
export async function fetchManagedDashboards(
  signal?: AbortSignal,
): Promise<{ dashboards: AdminDashboard[]; author_domains: Domain[] }> {
  return apiRequest("/api/v1/portal/manage/dashboards/", { signal });
}

export async function updateDashboard(key: string, changes: Partial<Pick<AdminDashboard, "visible" | "title" | "description" | "position">>) {
  return (await apiRequest<{ dashboard: AdminDashboard }>(`/api/v1/portal/manage/dashboards/${encodeURIComponent(key)}/`, {
    method: "PATCH",
    body: changes,
  })).dashboard;
}

export async function registerDashboard(body: { superset_ref: string; domain: string; title?: string; description?: string }) {
  return (await apiRequest<{ dashboard: AdminDashboard }>("/api/v1/portal/manage/dashboards/", { method: "POST", body })).dashboard;
}

export async function removeDashboard(key: string): Promise<void> {
  await apiRequest(`/api/v1/portal/manage/dashboards/${encodeURIComponent(key)}/`, { method: "DELETE" });
}

export async function fetchAdminUsers(signal?: AbortSignal): Promise<AdminUsersResponse> {
  return apiRequest<AdminUsersResponse>("/api/v1/portal/admin/users/", { signal });
}
