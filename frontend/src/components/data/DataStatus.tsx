import { AlertTriangle, CalendarDays, Clock, FlaskConical, MapPin } from "lucide-react";

import type { DataSummary } from "../../api/types";
import { formatAge, formatDate } from "../../lib/format";
import { Badge } from "../ui/Badge";

/**
 * Reporting date, last validated publication and the data labels every analytical view shows:
 * stale data, synthetic (fictional) data and branch restriction. Values come from the backend.
 */
export function DataStatus({ summary }: { summary: DataSummary }) {
  return (
    <>
      <Badge tone="neutral">
        <CalendarDays size={13} aria-hidden="true" /> Data as of{" "}
        {summary.as_of.length ? summary.as_of.map(formatDate).join(" / ") : "–"}
      </Badge>
      <Badge tone={summary.stale ? "warning" : "success"}>
        <Clock size={13} aria-hidden="true" /> Refreshed {formatAge(summary.hours_since_publication)}
      </Badge>
      {summary.stale && (
        <Badge tone="warning">
          <AlertTriangle size={13} aria-hidden="true" /> Data may be out of date
        </Badge>
      )}
      {summary.synthetic && (
        <Badge tone="danger">
          <FlaskConical size={13} aria-hidden="true" /> Synthetic demonstration data
        </Badge>
      )}
      {summary.branch_restricted && (
        <Badge tone="info">
          <MapPin size={13} aria-hidden="true" /> Limited to your branch
        </Badge>
      )}
    </>
  );
}

export function StaleBanner({ summary }: { summary: DataSummary }) {
  if (!summary.stale && !summary.synthetic) return null;
  return (
    <div className={`banner ${summary.synthetic ? "banner--danger" : "banner--warning"}`} role="status">
      <AlertTriangle size={18} aria-hidden="true" />
      <p>
        {summary.synthetic
          ? "These figures come from the FICTIONAL synthetic demonstration dataset, not from DrukSmart's ERPs."
          : `The last validated data publication was ${formatAge(summary.hours_since_publication)}. The daily refresh may have failed; figures may be out of date.`}
      </p>
    </div>
  );
}
