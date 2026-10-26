import { ExternalLink, LayoutDashboard, LayoutGrid } from "lucide-react";
import { useSearchParams } from "react-router";

import { fetchDashboards } from "../api/endpoints";
import type { Domain } from "../api/types";
import { useCurrentUser } from "../auth/session";
import { EmbeddedDashboard } from "../components/dashboard/EmbeddedDashboard";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { ButtonAnchor, ButtonLink } from "../components/ui/Button";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/States";
import { useApi } from "../lib/useApi";
import { PAGES } from "../navigation";

function AnalyticsPage({ domain }: { domain: Domain }) {
  const page = domain === "hr" ? PAGES.hr : PAGES.accounts;
  const user = useCurrentUser();
  const list = useApi((signal) => fetchDashboards(signal), user.username);
  const [params, setParams] = useSearchParams();

  const dashboards = list.status === "ready" ? list.data.dashboards.filter((d) => d.domain === domain) : [];
  const selected = dashboards.find((d) => d.key === params.get("dashboard")) ?? dashboards[0];

  return (
    <>
      <PageHeader
        title={page.label}
        description={page.description}
        meta={
          user.branch_restricted ? (
            <Badge tone="info">Limited to your branch</Badge>
          ) : undefined
        }
        actions={
          selected?.editor_url ? (
            <>
              <ButtonLink to={PAGES.manage.path} size="sm" icon={<LayoutGrid size={16} aria-hidden="true" />}>
                {PAGES.manage.label}
              </ButtonLink>
              <ButtonAnchor
              href={selected.editor_url}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              icon={<ExternalLink size={16} aria-hidden="true" />}
              title="Opens Superset's dashboard editor in a new tab. Superset asks for its own sign-in (prototype limitation)."
            >
                Edit in Superset (separate sign-in)
              </ButtonAnchor>
            </>
          ) : undefined
        }
      />
      {list.status === "loading" && <LoadingState message="Loading dashboards…" />}
      {list.status === "error" && (
        <ErrorState title="Dashboards could not be loaded" message={list.error.message} onRetry={list.reload} />
      )}
      {list.status === "ready" && dashboards.length === 0 && (
        <EmptyState
          icon={<LayoutDashboard size={28} />}
          title="No dashboard is published for this module"
          message="The administrator can make dashboards visible on the Administration page."
        />
      )}
      {selected && (
        <div className="stack">
          {dashboards.length > 1 && (
            <div className="tabs" role="tablist" aria-label={`${page.label} dashboards`}>
              {dashboards.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  role="tab"
                  className="tabs__tab"
                  aria-selected={d.key === selected.key}
                  onClick={() => setParams({ dashboard: d.key }, { replace: true })}
                >
                  {d.title}
                  {d.kind === "custom" && <Badge tone="neutral">Custom</Badge>}
                </button>
              ))}
            </div>
          )}
          <EmbeddedDashboard key={selected.key} dashboardKey={selected.key} title={selected.title} />
        </div>
      )}
    </>
  );
}

export function HrAnalyticsPage() {
  return <AnalyticsPage domain="hr" />;
}

export function AccountsAnalyticsPage() {
  return <AnalyticsPage domain="accounts" />;
}
