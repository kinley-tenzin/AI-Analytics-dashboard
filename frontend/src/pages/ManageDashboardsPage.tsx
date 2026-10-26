import { ExternalLink, Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import { fetchDashboards, fetchManagedDashboards, registerDashboard, removeDashboard, updateDashboard } from "../api/endpoints";
import type { AdminDashboard, Domain } from "../api/types";
import { useCurrentUser } from "../auth/session";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonAnchor } from "../components/ui/Button";
import { ErrorState, LoadingState } from "../components/ui/States";
import { useApi } from "../lib/useApi";
import { PAGES } from "../navigation";

const MODULE: Record<Domain, string> = { hr: "HR", accounts: "Accounts" };

function PublishForm({ modules, onDone }: { modules: Domain[]; onDone: (d: AdminDashboard) => void }) {
  const id = useId();
  const [ref, setRef] = useState("");
  const [domain, setDomain] = useState<Domain>(modules[0] ?? "hr");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await registerDashboard({ superset_ref: ref.trim(), domain, title: title.trim() || undefined });
      setRef("");
      setTitle("");
      onDone(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Publishing failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="register" onSubmit={submit} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="card__title">
        Publish a dashboard you built in Superset
      </h2>
      <p className="card__subtitle">
        Enter the dashboard's number or slug from its Superset address (…/superset/dashboard/<strong>12</strong>/). The
        website checks that it only uses data of the chosen module and adds it to that page, hidden until you make it
        visible.
      </p>
      <div className="register__fields">
        <div className="field">
          <label className="field__label" htmlFor={`${id}-ref`}>
            Superset dashboard number or slug
          </label>
          <input id={`${id}-ref`} className="field__input" value={ref} onChange={(e) => setRef(e.target.value)} required maxLength={64} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor={`${id}-domain`}>
            Module page
          </label>
          <select id={`${id}-domain`} className="field__input" value={domain} onChange={(e) => setDomain(e.target.value as Domain)}>
            {modules.map((m) => (
              <option key={m} value={m}>
                {MODULE[m]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor={`${id}-title`}>
            Title in the website (optional)
          </label>
          <input id={`${id}-title`} className="field__input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} />
        </div>
      </div>
      {error && (
        <p className="form-alert form-alert--error" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" disabled={busy || !ref.trim()} icon={<Plus size={16} aria-hidden="true" />}>
        {busy ? "Checking…" : "Publish dashboard"}
      </Button>
    </form>
  );
}

/**
 * Dashboard management (ADR-044): the HR / Accounts Manager (their module) and the administrator
 * (both). Building and editing happens in Superset's own editor; here the manager decides what
 * their module's page shows. The backend limits every action to the user's modules.
 */
export function ManageDashboardsPage() {
  const user = useCurrentUser();
  const list = useApi((signal) => fetchManagedDashboards(signal), user.username);
  const meta = useApi((signal) => fetchDashboards(signal), user.username);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const supersetUrl = meta.status === "ready" ? meta.data.superset_url : null;
  const managed = list.status === "error" ? undefined : list.data;

  async function act(action: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await action();
      setMessage({ tone: "ok", text: ok });
      list.reload();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : "The change failed." });
    }
  }

  return (
    <>
      <PageHeader
        title={PAGES.manage.label}
        description={PAGES.manage.description}
        actions={
          supersetUrl ? (
            <ButtonAnchor
              href={`${supersetUrl}/dashboard/list/`}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              icon={<ExternalLink size={16} aria-hidden="true" />}
              title="Build or edit dashboards in Superset's editor. Superset asks for its own sign-in (prototype limitation)."
            >
              Build in Superset (separate sign-in)
            </ButtonAnchor>
          ) : undefined
        }
      />
      <ol className="steps" aria-label="How to add a dashboard">
        <li>
          <strong>Build</strong> a new dashboard in Superset with your module's data (the official dashboards stay
          protected).
        </li>
        <li>
          <strong>Publish</strong> it below on your module's page.
        </li>
        <li>
          <strong>Show</strong> it to your module's users with the Hidden / Visible switch.
        </li>
      </ol>
      {list.status === "loading" && !managed && <LoadingState message="Loading dashboards…" />}
      {list.status === "error" && <ErrorState message={list.error.message} onRetry={list.reload} />}
      {managed && (
        <div className="stack stack--lg">
          {message && (
            <p className={`form-alert ${message.tone === "ok" ? "form-alert--info" : "form-alert--error"}`} role={message.tone === "ok" ? "status" : "alert"}>
              {message.text}
            </p>
          )}
          <div className="table-wrap">
            <table className="data-table">
              <caption className="visually-hidden">Dashboards shown in the website</caption>
              <thead>
                <tr>
                  <th scope="col">Dashboard</th>
                  <th scope="col">Module page</th>
                  <th scope="col">Type</th>
                  <th scope="col">Shown to users</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {managed.dashboards.map((d) => (
                  <tr key={d.key}>
                    <th scope="row">
                      {d.title}
                      <span className="cell-sub">Superset: {d.superset_ref}</span>
                    </th>
                    <td>{MODULE[d.domain]}</td>
                    <td>{d.kind === "official" ? <Badge tone="brand">Official</Badge> : <Badge tone="neutral">Own dashboard</Badge>}</td>
                    <td>
                      <button
                        type="button"
                        className={`toggle ${d.visible ? "toggle--on" : ""}`}
                        aria-pressed={d.visible}
                        onClick={() => act(() => updateDashboard(d.key, { visible: !d.visible }), `${d.title} is now ${d.visible ? "hidden" : "visible"}.`)}
                      >
                        {d.visible ? <Eye size={16} aria-hidden="true" /> : <EyeOff size={16} aria-hidden="true" />}
                        {/* The visible word is part of the accessible name (WCAG 2.5.3 label in name). */}
                        <span className="visually-hidden">Show {d.title} to {MODULE[d.domain]} users: </span>
                        {d.visible ? "Visible" : "Hidden"}
                      </button>
                    </td>
                    <td className="cell-actions">
                      <ButtonAnchor href={d.editor_url} target="_blank" rel="noopener noreferrer" size="sm" variant="ghost" icon={<ExternalLink size={14} aria-hidden="true" />}>
                        Superset
                      </ButtonAnchor>
                      {d.kind === "custom" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={14} aria-hidden="true" />}
                          onClick={() => act(() => removeDashboard(d.key), `${d.title} was removed from the website (it stays in Superset).`)}
                        >
                          Remove
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card card--pad">
            <PublishForm
              modules={managed.author_domains}
              onDone={(d) => {
                setMessage({ tone: "ok", text: `${d.title} was published on the ${MODULE[d.domain]} page (hidden).` });
                list.reload();
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}
