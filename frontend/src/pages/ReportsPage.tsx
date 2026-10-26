import { Download, Eye, FileText, LayoutDashboard } from "lucide-react";
import { useId, useState } from "react";

import { ApiError } from "../api/client";
import { fetchReports, previewReport, reportCsvUrl } from "../api/endpoints";
import type { ReportParams } from "../api/endpoints";
import type { ReportInfo, ReportPreview } from "../api/types";
import { canAccess } from "../auth/access";
import { useCurrentUser } from "../auth/session";
import { ResultChart, ResultTable } from "../components/data/ResultView";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonAnchor, ButtonLink } from "../components/ui/Button";
import { EmptyState, ErrorState, LoadingState, Spinner } from "../components/ui/States";
import { formatAge, formatDate, formatPeriod } from "../lib/format";
import { useApi } from "../lib/useApi";
import { PAGES } from "../navigation";

function ReportCard({ report }: { report: ReportInfo }) {
  const id = useId();
  const [params, setParams] = useState<ReportParams>({});
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set(name: keyof ReportParams, value: string) {
    setParams((p) => ({ ...p, [name]: value }));
    setPreview(null);
    setError(null);
  }

  async function onPreview() {
    setLoading(true);
    setError(null);
    try {
      setPreview(await previewReport(report.key, params));
    } catch (err) {
      setPreview(null);
      setError(err instanceof ApiError ? err.message : "The report could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  const result = preview?.result;
  return (
    <section className="card report" aria-labelledby={`${id}-title`}>
      <div className="report__head">
        <div>
          <h3 id={`${id}-title`} className="report__title">
            {report.title}
          </h3>
          <p className="report__description">{report.description}</p>
        </div>
        <Badge tone="neutral">{report.kpi_ids.join(", ")}</Badge>
      </div>
      <div className="report__controls">
        {report.time === "snapshot" ? (
          <div className="field field--inline">
            <label className="field__label" htmlFor={`${id}-asof`}>
              As of
            </label>
            <input id={`${id}-asof`} type="date" className="field__input" value={params.as_of ?? ""} onChange={(e) => set("as_of", e.target.value)} />
            <span className="field__hint">Empty = latest data</span>
          </div>
        ) : (
          <>
            <div className="field field--inline">
              <label className="field__label" htmlFor={`${id}-from`}>
                From
              </label>
              <input id={`${id}-from`} type="date" className="field__input" value={params.period_start ?? ""} onChange={(e) => set("period_start", e.target.value)} />
            </div>
            <div className="field field--inline">
              <label className="field__label" htmlFor={`${id}-to`}>
                To
              </label>
              <input id={`${id}-to`} type="date" className="field__input" value={params.period_end ?? ""} onChange={(e) => set("period_end", e.target.value)} />
              <span className="field__hint">Empty = month of the latest data</span>
            </div>
          </>
        )}
        <div className="report__actions">
          <Button variant="secondary" size="sm" onClick={onPreview} disabled={loading} icon={<Eye size={16} aria-hidden="true" />}>
            Preview
          </Button>
          <ButtonAnchor variant="primary" size="sm" href={reportCsvUrl(report.key, params)} download icon={<Download size={16} aria-hidden="true" />}>
            Download CSV
          </ButtonAnchor>
        </div>
      </div>
      {loading && (
        <p className="report__status" role="status">
          <Spinner label="Loading the report" /> Loading…
        </p>
      )}
      {error && (
        <p className="form-alert form-alert--error" role="alert">
          {error}
        </p>
      )}
      {result && (
        <div className="report__preview">
          <div className="answer__meta">
            <Badge tone="neutral">{result.as_of ? `As of ${formatDate(result.as_of)}` : formatPeriod(result.period)}</Badge>
            {result.branch_restricted && <Badge tone="info">Limited to your branch</Badge>}
            <Badge tone={result.stale ? "warning" : "success"}>Refreshed {formatAge(result.hours_since_publication)}</Badge>
            {result.synthetic && <Badge tone="danger">Synthetic demonstration data</Badge>}
          </div>
          {result.rows.length === 0 ? (
            <p className="report__status">No rows for these settings.</p>
          ) : (
            <>
              <ResultChart result={result} />
              <ResultTable result={result} caption={report.title} />
            </>
          )}
        </div>
      )}
    </section>
  );
}

export function ReportsPage() {
  const user = useCurrentUser();
  const list = useApi((signal) => fetchReports(signal), user.username);
  const groups = [
    { domain: "hr", title: "Human resources" },
    { domain: "accounts", title: "Accounts" },
  ] as const;

  return (
    <>
      <PageHeader title={PAGES.reports.label} description={PAGES.reports.description} />
      {list.status === "loading" && <LoadingState message="Loading reports…" />}
      {list.status === "error" && <ErrorState message={list.error.message} onRetry={list.reload} />}
      {list.status === "ready" && list.data.reports.length === 0 && (
        <EmptyState icon={<FileText size={28} />} title="No reports are available to your role" />
      )}
      {list.status === "ready" && (
        <div className="stack stack--lg">
          <div className="banner banner--info" role="note">
            <LayoutDashboard size={18} aria-hidden="true" />
            <p>
              These reports use the approved KPI definitions and your role and branch. For any chart of a dashboard,
              use its <strong>⋮ → Download</strong> menu (CSV, Excel or image) in HR or Accounts Analytics.
            </p>
          </div>
          {groups.map((g) => {
            const reports = list.data.reports.filter((r) => r.domain === g.domain);
            if (reports.length === 0) return null;
            const page = g.domain === "hr" ? PAGES.hr : PAGES.accounts;
            return (
              <section key={g.domain} className="overview-section" aria-label={g.title}>
                <div className="overview-section__head">
                  <h2 className="overview-section__title">{g.title}</h2>
                  {canAccess(user, page.requires) && (
                    <ButtonLink to={page.path} size="sm">
                      Open {page.label}
                    </ButtonLink>
                  )}
                </div>
                <div className="report-grid">
                  {reports.map((r) => (
                    <ReportCard key={r.key} report={r} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
