import { AlertTriangle, Construction, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "./Badge";
import { Button } from "./Button";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span className="spinner" role="status" aria-live="polite">
      <span className="spinner__circle" aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  );
}

export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="state state--loading">
      <Spinner label={message} />
      <p className="state__message" aria-hidden="true">
        {message}
      </p>
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  message?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ title, message, icon, action }: EmptyStateProps) {
  return (
    <div className="state">
      <div className="state__icon" aria-hidden="true">
        {icon ?? <Inbox size={28} />}
      </div>
      <h2 className="state__title">{title}</h2>
      {message && <p className="state__message">{message}</p>}
      {action && <div className="state__action">{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  message: ReactNode;
  onRetry?: () => void;
}

export function ErrorState({ title = "Something went wrong", message, onRetry }: ErrorStateProps) {
  return (
    <div className="state state--error" role="alert">
      <div className="state__icon" aria-hidden="true">
        <AlertTriangle size={28} />
      </div>
      <h2 className="state__title">{title}</h2>
      <p className="state__message">{message}</p>
      {onRetry && (
        <div className="state__action">
          <Button variant="secondary" icon={<RefreshCw size={16} aria-hidden="true" />} onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
    </div>
  );
}

interface PendingIntegrationProps {
  /** Milestone task that delivers the feature, e.g. "10.5". */
  task: string;
  title: string;
  children: ReactNode;
}

/**
 * An explicit, labelled placeholder for a feature that is NOT implemented yet. It never shows
 * sample numbers, so nothing on screen can be mistaken for real warehouse data.
 */
export function PendingIntegration({ task, title, children }: PendingIntegrationProps) {
  return (
    <section className="pending" aria-label={`${title} (not implemented yet)`}>
      <div className="pending__icon" aria-hidden="true">
        <Construction size={22} />
      </div>
      <div>
        <div className="pending__heading">
          <h2 className="pending__title">{title}</h2>
          <Badge tone="warning">Not implemented yet · Task {task}</Badge>
        </div>
        <div className="pending__body">{children}</div>
      </div>
    </section>
  );
}
