import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { BrandMark } from "../components/layout/BrandMark";
import { ErrorState, LoadingState } from "../components/ui/States";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import type { Requirement } from "./access";
import { canAccess } from "./access";
import { useCurrentUser, useSession } from "./session";

function FullPage({ children }: { children: ReactNode }) {
  return (
    <div className="fullpage">
      <BrandMark />
      <div className="fullpage__body">{children}</div>
    </div>
  );
}

/** Renders its children only for a signed-in user; otherwise sends them to the sign-in page. */
export function RequireSession({ children }: { children: ReactNode }) {
  const { session, reload } = useSession();
  const location = useLocation();

  switch (session.status) {
    case "loading":
      return (
        <FullPage>
          <LoadingState message="Checking your session…" />
        </FullPage>
      );
    case "anonymous": {
      const next = `${location.pathname}${location.search}`;
      const target = next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
      return <Navigate to={target} replace />;
    }
    case "error":
      return (
        <FullPage>
          <ErrorState
            title="DrukSmart Analytics is unavailable"
            message={`${session.error.message} If this continues, ask the administrator to check the backend service.`}
            onRetry={reload}
          />
        </FullPage>
      );
    case "authenticated":
      return <>{children}</>;
  }
}

/** Shows a page only when the user's scope allows it (the API checks again on every request). */
export function RequireAccess({ requires, children }: { requires: Requirement; children: ReactNode }) {
  const user = useCurrentUser();
  return canAccess(user, requires) ? <>{children}</> : <ForbiddenPage />;
}
