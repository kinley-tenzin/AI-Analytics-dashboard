import { ArrowRight, CalendarCheck, Clock3, Landmark, UserX, Users } from "lucide-react";

import { fetchOverview } from "../api/endpoints";
import type { KpiResult, OverviewTile } from "../api/types";
import { useCurrentUser } from "../auth/session";
import { BarChart } from "../components/data/BarChart";
import { DataStatus, StaleBanner } from "../components/data/DataStatus";
import { StatTile } from "../components/data/StatTile";
import { PageHeader } from "../components/layout/PageHeader";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/States";
import { ageingLabel, formatDate, formatPeriod, formatValue } from "../lib/format";
import { useApi } from "../lib/useApi";
import { PAGES } from "../navigation";

function ok(tile: OverviewTile | undefined): KpiResult | null {
  return tile && tile.status === "ok" && "result" in tile ? tile.result : null;
}

function problem(tile: OverviewTile | undefined): string | undefined {
  return tile && "message" in tile ? tile.message : undefined;
}

/** One line per currency: amounts in different currencies are never added together. */
function amounts(result: KpiResult | null, measure: string, where: (row: KpiResult["rows"][number]) => boolean = () => true) {
  if (!result) return [];
  return result.rows.filter(where).map((r) => formatValue(r[measure], "amount", String(r.currency ?? "")));
}

function HrSection({ tiles }: { tiles: Record<string, OverviewTile> }) {
  const headcount = ok(tiles.headcount);
  const byDepartment = ok(tiles.headcount_by_department);
  const leave = ok(tiles.leave);
  const total = headcount?.rows[0]?.active_headcount;
  const departments = byDepartment ? [...byDepartment.rows].sort((a, b) => Number(b.active_headcount) - Number(a.active_headcount)) : [];
  const leaveRow = leave?.rows[0];

  return (
    <section className="overview-section" aria-labelledby="ov-hr">
      <div className="overview-section__head">
        <h2 id="ov-hr" className="overview-section__title">
          <Users size={20} aria-hidden="true" /> Human resources
        </h2>
        <ButtonLink to={PAGES.hr.path} size="sm" icon={<ArrowRight size={16} aria-hidden="true" />}>
          HR analytics
        </ButtonLink>
      </div>
      <div className="stat-grid">
        <StatTile
          label="Active employees"
          values={total === undefined ? [] : [formatValue(total, "count")]}
          detail={headcount ? `As of ${formatDate(headcount.as_of)}` : problem(tiles.headcount)}
          icon={<Users size={18} />}
        />
        <StatTile
          label="Departments with active staff"
          values={byDepartment ? [formatValue(departments.filter((r) => Number(r.active_headcount) > 0).length, "count")] : []}
          detail={byDepartment ? `Largest: ${departments[0]?.department ?? "–"}` : problem(tiles.headcount_by_department)}
          icon={<Landmark size={18} />}
        />
        <StatTile
          label="Employees on approved leave"
          values={leaveRow ? [formatValue(leaveRow.employees_on_leave, "count")] : []}
          detail={
            leaveRow && leave
              ? `${formatValue(leaveRow.approved_requests, "count")} requests · ${formatValue(leaveRow.approved_leave_days, "days")} days · ${formatPeriod(leave.period)}`
              : problem(tiles.leave)
          }
          icon={<CalendarCheck size={18} />}
        />
      </div>
      {byDepartment && departments.length > 0 && (
        <div className="card chart-card">
          <BarChart
            title={`Active employees by department · ${formatDate(byDepartment.as_of)}`}
            labelHeading="Department"
            valueHeading="Active employees"
            bars={departments.map((r) => ({
              label: String(r.department),
              value: Number(r.active_headcount),
              display: formatValue(r.active_headcount, "count"),
            }))}
            summary={`Active employees by department: ${departments.map((r) => `${r.department} ${r.active_headcount}`).join(", ")}.`}
          />
        </div>
      )}
    </section>
  );
}

function AgeingChart({ result, ledger, title }: { result: KpiResult; ledger: string; title: string }) {
  const rows = result.rows.filter((r) => r.ledger === ledger);
  const currencies = new Set(rows.map((r) => r.currency));
  if (rows.length === 0) return null;
  const bars = rows.map((r) => ({
    label: `${ageingLabel(String(r.ageing))}${currencies.size > 1 ? ` (${r.currency})` : ""}`,
    value: Number(r.outstanding_amount),
    display: formatValue(r.outstanding_amount, "amount", String(r.currency)),
  }));
  return (
    <div className="card chart-card">
      <BarChart
        title={`${title} · ${formatDate(result.as_of)}`}
        labelHeading="Ageing"
        valueHeading="Outstanding balance"
        bars={bars}
        summary={`${title}: ${bars.map((b) => `${b.label} ${b.display}`).join(", ")}.`}
      />
    </div>
  );
}

function AccountsSection({ tiles }: { tiles: Record<string, OverviewTile> }) {
  const receivables = ok(tiles.receivables);
  const payables = ok(tiles.payables);
  const overdue = ok(tiles.overdue);
  const ageing = ok(tiles.ageing);
  const docs = (r: KpiResult | null) =>
    r ? `${formatValue(r.rows.reduce((n, row) => n + Number(row.open_documents ?? 0), 0), "count")} open documents` : undefined;

  return (
    <section className="overview-section" aria-labelledby="ov-acc">
      <div className="overview-section__head">
        <h2 id="ov-acc" className="overview-section__title">
          <Landmark size={20} aria-hidden="true" /> Accounts
        </h2>
        <ButtonLink to={PAGES.accounts.path} size="sm" icon={<ArrowRight size={16} aria-hidden="true" />}>
          Accounts analytics
        </ButtonLink>
      </div>
      <div className="stat-grid stat-grid--4">
        <StatTile label="Outstanding receivables" values={amounts(receivables, "outstanding_amount")} detail={docs(receivables) ?? problem(tiles.receivables)} />
        <StatTile label="Outstanding payables" values={amounts(payables, "outstanding_amount")} detail={docs(payables) ?? problem(tiles.payables)} />
        <StatTile
          label="Overdue receivables"
          values={amounts(overdue, "overdue_amount", (r) => r.ledger === "receivable")}
          detail={overdue ? "Past due date, still open" : problem(tiles.overdue)}
          icon={<Clock3 size={18} />}
        />
        <StatTile
          label="Overdue payables"
          values={amounts(overdue, "overdue_amount", (r) => r.ledger === "payable")}
          detail={overdue ? "Past due date, still open" : problem(tiles.overdue)}
          icon={<Clock3 size={18} />}
        />
      </div>
      {ageing && (
        <div className="chart-grid">
          <AgeingChart result={ageing} ledger="receivable" title="Receivables by ageing" />
          <AgeingChart result={ageing} ledger="payable" title="Payables by ageing" />
        </div>
      )}
    </section>
  );
}

export function OverviewPage() {
  const user = useCurrentUser();
  const overview = useApi((signal) => fetchOverview(signal), user.username);

  if (user.domains.length === 0) {
    return (
      <>
        <PageHeader title="Overview" />
        <EmptyState
          icon={<UserX size={28} />}
          title="No analytics modules are assigned to you"
          message="Your account is active but has no HR or Accounts role. Ask the DrukSmart administrator to assign one."
        />
      </>
    );
  }

  const summary = overview.status === "ready" ? overview.data.summary : null;
  return (
    <>
      <PageHeader title="Overview" description={PAGES.overview.description} meta={summary && <DataStatus summary={summary} />} />
      {overview.status === "loading" && <LoadingState message="Loading your indicators…" />}
      {overview.status === "error" && (
        <ErrorState title="The indicators could not be loaded" message={overview.error.message} onRetry={overview.reload} />
      )}
      {overview.status === "ready" && (
        <div className="stack stack--lg">
          {summary && <StaleBanner summary={summary} />}
          {overview.data.domains.includes("hr") && <HrSection tiles={overview.data.tiles} />}
          {overview.data.domains.includes("accounts") && <AccountsSection tiles={overview.data.tiles} />}
          <p className="footnote">
            Figures come from the approved KPI definitions over the validated warehouse
            {summary?.branch_restricted ? ", limited to your branch" : ""}. Amounts are in each organisation's company
            currency and are never converted or added across currencies.
          </p>
        </div>
      )}
    </>
  );
}
