import { ArrowRight, CheckCircle2, ExternalLink, RefreshCw, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import { fetchAdminStatus, fetchAdminUsers } from "../api/endpoints";
import type { AdminStatus } from "../api/types";
import { useCurrentUser } from "../auth/session";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonAnchor, ButtonLink } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorState, LoadingState } from "../components/ui/States";
import { formatAge, formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";
import { PAGES } from "../navigation";

const MODULE = { hr: "HR", accounts: "Accounts" } as const;

function Health({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className={`health ${ok ? "health--ok" : "health--bad"}`}>
      {ok ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />}
      <span>{children}</span>
      <span className="visually-hidden">{ok ? "(working)" : "(problem)"}</span>
    </span>
  );
}

function StatusSection({ status }: { status: AdminStatus }) {
  return (
    <div className="status-grid">
      <Card title="Warehouse" as="h3">
        <Health ok={status.warehouse.reachable}>{status.warehouse.reachable ? "Reachable" : "Not reachable"}</Health>
        <p className="status-line">
          Consumers read{" "}
          {status.warehouse.consumer_data === "synthetic" ? (
            <Badge tone="danger">SYNTHETIC demonstration data</Badge>
          ) : (
            <Badge tone="success">live ERP data</Badge>
          )}
        </p>
      </Card>
      {status.modules.map((m) => (
        <Card key={m.domain} title={`${MODULE[m.domain]} data`} as="h3">
          {m.error ? (
            <Health ok={false}>{m.error}</Health>
          ) : (
            <>
              <Health ok={!m.stale}>Published {formatAge(m.hours_since_publication)}</Health>
              <ul className="status-sources">
                {(m.sources ?? []).map((s) => (
                  <li key={s.source_instance}>
                    {s.source_instance}: data as of {formatDate(s.data_as_of)} ({s.source_mode})
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      ))}
      <Card title="Dashboards (Superset)" as="h3">
        <Health ok={status.superset.reachable}>{status.superset.reachable ? "Superset reachable" : "Superset not reachable"}</Health>
        <Health ok={status.superset.service_account}>
          {status.superset.service_account ? "Embedding service account works" : "Embedding service account failed"}
        </Health>
      </Card>
      <Card title="Ask AI" as="h3">
        <p className="status-line">
          {status.assistant.llm
            ? `Language model: ${status.assistant.provider} (${status.assistant.model})`
            : "Deterministic rules interpreter (no language model)"}
        </p>
        <p className="status-line status-line--muted">
          {status.counts.active_users} active users · {status.counts.visible_dashboards} of {status.counts.dashboards} dashboards visible
        </p>
      </Card>
    </div>
  );
}

function UsersSection() {
  const users = useApi((signal) => fetchAdminUsers(signal));
  if (users.status === "loading") return <LoadingState message="Loading users…" />;
  if (users.status === "error") return <ErrorState message={users.error.message} onRetry={users.reload} />;
  const { data } = users;
  return (
    <div className="stack">
      <div className="table-wrap">
        <table className="data-table">
          <caption className="visually-hidden">Users, roles and modules</caption>
          <thead>
            <tr>
              <th scope="col">User</th>
              <th scope="col">Role</th>
              <th scope="col">Modules</th>
              <th scope="col">Branches</th>
              <th scope="col">Last sign-in</th>
            </tr>
          </thead>
          <tbody>
            {data.users.map((u) => (
              <tr key={u.username}>
                <th scope="row">
                  {u.username} {!u.active && <Badge tone="warning">inactive</Badge>}
                </th>
                <td>{u.administrator ? "Administrator" : u.roles.map((r) => r.replace(/^DrukSmart /, "")).join(", ") || "–"}</td>
                <td>{u.modules.map((m) => MODULE[m]).join(", ") || "–"}</td>
                <td>{u.branches.join(", ") || (u.roles.includes("DrukSmart Branch Manager") ? "none (sees nothing)" : "all")}</td>
                <td>{u.last_login ? formatDate(u.last_login) : "never"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="admin-roles">
        <h3 className="card__title">Modules per role</h3>
        <ul>
          {data.roles.map((r) => (
            <li key={r.role}>
              <strong>{r.role.replace(/^DrukSmart /, "")}</strong>: {r.modules.map((m) => MODULE[m]).join(" + ")}
            </li>
          ))}
        </ul>
        <p className="card__subtitle">
          The HR and Accounts Managers also have a Superset account with the same role (for building dashboards). Keep both
          in step when you change a person's role.
        </p>
      </div>
      <ButtonAnchor href={data.manage_url} icon={<ExternalLink size={16} aria-hidden="true" />}>
        Add or edit users, roles and branches (Django admin)
      </ButtonAnchor>
    </div>
  );
}

export function AdminPage() {
  const user = useCurrentUser();
  const status = useApi((signal) => fetchAdminStatus(signal), user.username);
  return (
    <>
      <PageHeader
        title={PAGES.admin.label}
        description={PAGES.admin.description}
        actions={
          <Button variant="secondary" size="sm" onClick={status.reload} icon={<RefreshCw size={16} aria-hidden="true" />}>
            Refresh status
          </Button>
        }
      />
      <div className="stack stack--lg">
        <section aria-labelledby="adm-status" className="overview-section">
          <h2 id="adm-status" className="overview-section__title">Platform status</h2>
          {status.status === "loading" && <LoadingState message="Checking services…" />}
          {status.status === "error" && <ErrorState message={status.error.message} onRetry={status.reload} />}
          {status.status === "ready" && <StatusSection status={status.data} />}
        </section>
        <section aria-labelledby="adm-dash" className="overview-section">
          <h2 id="adm-dash" className="overview-section__title">Dashboard visibility</h2>
          <Card>
            <p className="status-line">
              The HR and Accounts Managers publish, show and hide the dashboards of their own module page; the
              administrator can do this for both modules.
            </p>
            <ButtonLink to={PAGES.manage.path} size="sm" icon={<ArrowRight size={16} aria-hidden="true" />}>
              {PAGES.manage.label}
            </ButtonLink>
          </Card>
        </section>
        <section aria-labelledby="adm-users" className="overview-section">
          <h2 id="adm-users" className="overview-section__title">Users and roles</h2>
          <UsersSection />
        </section>
      </div>
    </>
  );
}
