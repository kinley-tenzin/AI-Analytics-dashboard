import { useRouteError } from "react-router";

import { BrandMark } from "../components/layout/BrandMark";
import { ErrorState } from "../components/ui/States";

/** Last-resort screen for an unexpected error while rendering a page. */
export function RouteErrorPage() {
  const error = useRouteError();
  if (import.meta.env.DEV) console.error(error);
  return (
    <div className="fullpage">
      <BrandMark />
      <div className="fullpage__body">
        <ErrorState
          title="This page could not be displayed"
          message="An unexpected error occurred in the application. Reload the page; if it happens again, report it to the administrator."
          onRetry={() => window.location.reload()}
        />
      </div>
    </div>
  );
}
