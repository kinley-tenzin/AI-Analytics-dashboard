/** Response shapes of the existing Django endpoints (backend/kpi/views.py, backend/access/auth_api.py). */

export type Domain = "hr" | "accounts";

/** The signed-in user's scope, decided by Django (access/scope.py Scope.as_dict). */
export interface UserScope {
  username: string;
  roles: string[];
  domains: Domain[];
  branch_restricted: boolean;
  /** Modules whose dashboards the user may build (Superset) and publish (ADR-044). */
  author_domains: Domain[];
}

/** GET /api/v1/auth/session/, POST /api/v1/auth/login/ and /logout/. */
export interface SessionResponse {
  status: "ok";
  authenticated: boolean;
  user: UserScope | null;
}

/** One KPI result from the registry (kpi/service.py KpiResult.to_dict). */
export type Unit = "count" | "days" | "amount" | "label";

export interface KpiColumn {
  name: string;
  label: string;
  unit: Unit;
}

export interface Freshness {
  source_instance: string;
  data_as_of: string | null;
  published_at: string | null;
  source_mode: string;
  domain?: Domain;
}

export interface KpiResult {
  function: string;
  kpi_ids: string[];
  title: string;
  domain: Domain;
  dataset: string;
  as_of: string | null;
  period: { start: string; end: string } | null;
  group_by: string[];
  filters: Record<string, string>;
  branch_restricted: boolean;
  columns: KpiColumn[];
  rows: Record<string, string | number | null>[];
  freshness: Freshness[];
  notes: string[];
  hours_since_publication: number | null;
  stale: boolean;
  synthetic: boolean;
}

/** GET /api/v1/portal/overview/ (portal/overview.py). */
export type OverviewTile = { status: "ok"; result: KpiResult } | { status: string; message: string };

export interface DataSummary {
  as_of: string[];
  freshness: Freshness[];
  hours_since_publication: number | null;
  stale: boolean;
  synthetic: boolean;
  branch_restricted: boolean;
}

export interface OverviewResponse {
  status: "ok";
  domains: Domain[];
  tiles: Record<string, OverviewTile>;
  summary: DataSummary | null;
}

/** GET /api/v1/portal/dashboards/ (portal/dashboards.py). */
export interface PortalDashboard {
  key: string;
  title: string;
  description: string;
  domain: Domain;
  kind: "official" | "custom";
  /** Native Superset editor; only for the module's manager and the administrator (ADR-044). */
  editor_url?: string;
}

export interface DashboardsResponse {
  status: "ok";
  dashboards: PortalDashboard[];
  can_author: boolean;
  author_domains: Domain[];
  superset_url: string;
}

/** POST /api/v1/portal/dashboards/<key>/guest-token/ */
export interface GuestTokenResponse {
  status: "ok";
  token: string;
  embedded_id: string;
  superset_url: string;
  expires_in: number;
  branch_restricted: boolean;
}

/** POST /api/v1/ask/ (assistant/pipeline.py Answer.to_dict). */
export type AnswerStatus =
  | "answered"
  | "clarification_needed"
  | "unsupported"
  | "forbidden"
  | "invalid_filter"
  | "no_data"
  | "invalid_request"
  | "error";

export interface AskResponse {
  status: AnswerStatus | string;
  answer: string;
  interpreter: string;
  llm_used?: boolean;
  phrasing?: string;
  function: string | null;
  parameters: Record<string, unknown>;
  result: KpiResult | null;
  options: string[];
  details: Record<string, unknown>;
  notes: string[];
}

/** GET /api/v1/portal/assistant/ (portal/assistant_info.py). */
export interface AssistantInfo {
  status: "ok";
  provider: { provider: string; model: string | null; llm: boolean; note?: string };
  max_question_length: number;
  suggestions: { domain: Domain; kpi: string; question: string }[];
}

/** Reports page (portal/reports.py). */
export interface ReportInfo {
  key: string;
  title: string;
  description: string;
  domain: Domain;
  kpi_ids: string[];
  time: "snapshot" | "period";
}

export interface ReportsResponse {
  status: "ok";
  reports: ReportInfo[];
}

export interface ReportPreview {
  status: "ok";
  report: ReportInfo;
  result: KpiResult;
}

/** Administration page (portal/admin_api.py). */
export interface ModuleStatus {
  domain: Domain;
  sources?: Freshness[];
  hours_since_publication?: number | null;
  stale?: boolean;
  synthetic?: boolean;
  error?: string;
}

export interface AdminStatus {
  status: "ok";
  warehouse: { reachable: boolean; consumer_data: string };
  modules: ModuleStatus[];
  superset: { reachable: boolean; service_account: boolean; public_url: string };
  assistant: { provider: string; model: string | null; llm: boolean; note?: string };
  counts: { users: number; active_users: number; dashboards: number; visible_dashboards: number };
}

export interface AdminDashboard {
  key: string;
  title: string;
  description: string;
  domain: Domain;
  kind: "official" | "custom";
  superset_ref: string;
  visible: boolean;
  position: number;
  editor_url: string;
}

export interface AdminUser {
  username: string;
  active: boolean;
  administrator: boolean;
  roles: string[];
  modules: Domain[];
  branches: string[];
  last_login: string | null;
}

export interface AdminUsersResponse {
  status: "ok";
  users: AdminUser[];
  roles: { role: string; modules: Domain[] }[];
  manage_url: string;
}
