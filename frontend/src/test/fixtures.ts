import type {
  AdminDashboard,
  AdminStatus,
  AdminUsersResponse,
  AskResponse,
  AssistantInfo,
  DashboardsResponse,
  Domain,
  KpiResult,
  OverviewResponse,
  ReportInfo,
  UserScope,
} from "../api/types";

/** Fixtures shaped exactly like the backend's KPI results (values are test data, not real KPIs). */
const FRESHNESS = [
  { source_instance: "erpnext-sandbox", data_as_of: "2026-10-25", published_at: "2026-10-25T02:00:00+00:00", source_mode: "configured" },
  { source_instance: "odoo-sandbox", data_as_of: "2026-10-25", published_at: "2026-10-25T02:00:00+00:00", source_mode: "configured" },
];

export function kpi(partial: Partial<KpiResult> & Pick<KpiResult, "function" | "domain" | "columns" | "rows">): KpiResult {
  return {
    kpi_ids: ["X"],
    title: partial.function,
    dataset: "marts.x",
    as_of: "2026-10-25",
    period: null,
    group_by: [],
    filters: {},
    branch_restricted: false,
    freshness: FRESHNESS,
    notes: [],
    hours_since_publication: 4,
    stale: false,
    synthetic: false,
    ...partial,
  };
}

const HR_TILES = {
  headcount: kpi({
    function: "hr.active_headcount",
    domain: "hr",
    columns: [{ name: "active_headcount", label: "Active headcount", unit: "count" }],
    rows: [{ active_headcount: 16 }],
  }),
  headcount_by_department: kpi({
    function: "hr.active_headcount",
    domain: "hr",
    columns: [
      { name: "department", label: "Department", unit: "label" },
      { name: "active_headcount", label: "Active headcount", unit: "count" },
    ],
    rows: [
      { department: "Finance & Accounts", active_headcount: 3 },
      { department: "Sales", active_headcount: 5 },
      { department: "Operations", active_headcount: 2 },
    ],
  }),
  leave: kpi({
    function: "hr.approved_leave",
    domain: "hr",
    as_of: null,
    period: { start: "2026-10-01", end: "2026-10-31" },
    columns: [
      { name: "employees_on_leave", label: "Employees on approved leave", unit: "count" },
      { name: "approved_requests", label: "Approved leave requests", unit: "count" },
      { name: "approved_leave_days", label: "Approved leave days", unit: "days" },
    ],
    rows: [{ employees_on_leave: 4, approved_requests: 6, approved_leave_days: 11.5 }],
  }),
};

const AMOUNT = [
  { name: "currency", label: "Currency", unit: "label" as const },
  { name: "outstanding_amount", label: "Outstanding balance", unit: "amount" as const },
  { name: "open_documents", label: "Open documents", unit: "count" as const },
];

const ACCOUNTS_TILES = {
  receivables: kpi({
    function: "ac.outstanding_receivables",
    domain: "accounts",
    columns: AMOUNT,
    rows: [{ currency: "BTN", outstanding_amount: 166700, open_documents: 9 }],
  }),
  payables: kpi({
    function: "ac.outstanding_payables",
    domain: "accounts",
    columns: AMOUNT,
    rows: [
      { currency: "BTN", outstanding_amount: 37700, open_documents: 4 },
      { currency: "INR", outstanding_amount: 1200.5, open_documents: 1 },
    ],
  }),
  overdue: kpi({
    function: "ac.overdue_balance",
    title: "Overdue balances",
    domain: "accounts",
    columns: [
      { name: "ledger", label: "Ledger", unit: "label" },
      { name: "currency", label: "Currency", unit: "label" },
      { name: "overdue_amount", label: "Overdue balance", unit: "amount" },
    ],
    rows: [
      { ledger: "payable", currency: "BTN", overdue_amount: 31700 },
      { ledger: "receivable", currency: "BTN", overdue_amount: 149700 },
    ],
  }),
  ageing: kpi({
    function: "ac.ageing",
    domain: "accounts",
    columns: [
      { name: "ledger", label: "Ledger", unit: "label" },
      { name: "ageing", label: "Ageing bucket", unit: "label" },
      { name: "currency", label: "Currency", unit: "label" },
      { name: "outstanding_amount", label: "Outstanding balance", unit: "amount" },
    ],
    rows: [
      { ledger: "payable", ageing: "0 Not yet due", currency: "BTN", outstanding_amount: 7000 },
      { ledger: "receivable", ageing: "0 Not yet due", currency: "BTN", outstanding_amount: 22000 },
      { ledger: "receivable", ageing: "1 1-30 days overdue", currency: "BTN", outstanding_amount: 124200 },
      { ledger: "receivable", ageing: "6 Unapplied credit", currency: "BTN", outstanding_amount: -5000 },
    ],
  }),
};

export function overviewFor(domains: Domain[], overrides: Partial<OverviewResponse> = {}): OverviewResponse {
  const tiles: OverviewResponse["tiles"] = {};
  if (domains.includes("hr")) for (const [k, r] of Object.entries(HR_TILES)) tiles[k] = { status: "ok", result: r };
  if (domains.includes("accounts"))
    for (const [k, r] of Object.entries(ACCOUNTS_TILES)) tiles[k] = { status: "ok", result: r };
  return {
    status: "ok",
    domains,
    tiles,
    summary: domains.length
      ? {
          as_of: ["2026-10-25"],
          freshness: FRESHNESS,
          hours_since_publication: 4,
          stale: false,
          synthetic: false,
          branch_restricted: false,
        }
      : null,
    ...overrides,
  };
}

export function dashboardsFor(user: UserScope): DashboardsResponse {
  const author = (domain: Domain) => user.author_domains.includes(domain);
  const all = [
    { key: "hr", title: "HR Overview", description: "Headcount and leave.", domain: "hr" as const, kind: "official" as const },
    { key: "accounts", title: "Accounts Overview", description: "Balances.", domain: "accounts" as const, kind: "official" as const },
  ];
  return {
    status: "ok",
    dashboards: all
      .filter((d) => user.domains.includes(d.domain))
      .map((d) => (author(d.domain) ? { ...d, editor_url: `http://127.0.0.1:8088/superset/dashboard/druksmart-${d.key}/` } : d)),
    can_author: user.author_domains.length > 0,
    author_domains: user.author_domains,
    superset_url: "http://127.0.0.1:8088",
  };
}

export function assistantInfoFor(user: UserScope): AssistantInfo {
  const all = [
    { domain: "hr" as const, kpi: "Active employee headcount", question: "How many active employees are there?" },
    { domain: "hr" as const, kpi: "Active employee headcount", question: "How many employees work in each department?" },
    { domain: "accounts" as const, kpi: "Overdue balances", question: "How much is overdue?" },
  ];
  return {
    status: "ok",
    provider: { provider: "rules", model: null, llm: false, note: "deterministic rules (no language model)" },
    max_question_length: 500,
    suggestions: all.filter((s) => user.domains.includes(s.domain)),
  };
}

/** Answers shaped like assistant/pipeline.py Answer.to_dict (test data). */
export const ANSWERS: Record<string, AskResponse> = {
  overdue: {
    status: "answered",
    answer: "Overdue balances as of 25 October 2026: payables BTN 31,700.00; receivables BTN 149,700.00.",
    interpreter: "rules",
    llm_used: false,
    phrasing: "template",
    function: "ac.overdue_balance",
    parameters: {},
    result: ACCOUNTS_TILES.overdue,
    options: [],
    details: {},
    notes: ["Latest available snapshot date: 2026-10-25."],
  },
  departments: {
    status: "answered",
    answer: "Active employees by department as of 25 October 2026: Finance & Accounts 3, Sales 5, Operations 2 (total 10).",
    interpreter: "rules",
    llm_used: false,
    phrasing: "template",
    function: "hr.active_headcount",
    parameters: { group_by: "department" },
    result: HR_TILES.headcount_by_department,
    options: [],
    details: {},
    notes: [],
  },
  clarify: {
    status: "clarification_needed",
    answer: "Which KPI do you mean? For example:",
    interpreter: "rules",
    llm_used: false,
    phrasing: "template",
    function: null,
    parameters: {},
    result: null,
    options: ["How many active employees are there?", "How much is overdue?"],
    details: {},
    notes: [],
  },
  forbidden: {
    status: "forbidden",
    answer: "Your role does not include Accounts data.",
    interpreter: "rules",
    llm_used: false,
    phrasing: "template",
    function: "ac.overdue_balance",
    parameters: {},
    result: null,
    options: [],
    details: {},
    notes: [],
  },
};

export const REPORTS: ReportInfo[] = [
  { key: "headcount-by-department", title: "Active headcount by department", description: "HR-02.", domain: "hr", kpi_ids: ["HR-02"], time: "snapshot" },
  { key: "leave-by-type", title: "Approved leave by leave type", description: "HR-03.", domain: "hr", kpi_ids: ["HR-03"], time: "period" },
  { key: "ageing", title: "Ageing of open balances", description: "AC-04.", domain: "accounts", kpi_ids: ["AC-04"], time: "snapshot" },
];

export function reportsFor(user: UserScope) {
  return { status: "ok", reports: REPORTS.filter((r) => user.domains.includes(r.domain)) };
}

export function reportPreview(key: string) {
  const report = REPORTS.find((r) => r.key === key)!;
  const result = key === "ageing" ? ACCOUNTS_TILES.ageing : HR_TILES.headcount_by_department;
  return { status: "ok", report, result };
}

export const ADMIN_STATUS: AdminStatus = {
  status: "ok",
  warehouse: { reachable: true, consumer_data: "live" },
  modules: [
    { domain: "hr", sources: FRESHNESS, hours_since_publication: 3.5, stale: false, synthetic: false },
    { domain: "accounts", sources: FRESHNESS, hours_since_publication: 40, stale: true, synthetic: false },
  ],
  superset: { reachable: true, service_account: true, public_url: "http://127.0.0.1:8088" },
  assistant: { provider: "rules", model: null, llm: false },
  counts: { users: 6, active_users: 6, dashboards: 2, visible_dashboards: 2 },
};

export function adminDashboards(): AdminDashboard[] {
  return [
    { key: "hr", title: "HR Overview", description: "", domain: "hr", kind: "official", superset_ref: "druksmart-hr", visible: true, position: 10, editor_url: "http://127.0.0.1:8088/superset/dashboard/druksmart-hr/" },
    { key: "hr-leave-planner", title: "Leave planner", description: "", domain: "hr", kind: "custom", superset_ref: "leave-planner", visible: false, position: 100, editor_url: "http://127.0.0.1:8088/superset/dashboard/leave-planner/" },
  ];
}

export const ADMIN_USERS: AdminUsersResponse = {
  status: "ok",
  users: [
    { username: "demo_branch", active: true, administrator: false, roles: ["DrukSmart Branch Manager"], modules: ["accounts", "hr"], branches: ["odoo:odoo-sandbox:1"], last_login: "2026-10-25T08:00:00+00:00" },
    { username: "demo_hr", active: true, administrator: false, roles: ["DrukSmart HR Manager"], modules: ["hr"], branches: [], last_login: null },
  ],
  roles: [
    { role: "DrukSmart HR Manager", modules: ["hr"] },
    { role: "DrukSmart Executive", modules: ["accounts", "hr"] },
  ],
  manage_url: "/admin/auth/user/",
};
