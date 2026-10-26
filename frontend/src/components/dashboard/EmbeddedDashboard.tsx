import { embedDashboard } from "@superset-ui/embedded-sdk";
import type { EmbeddedDashboard as EmbeddedHandle } from "@superset-ui/embedded-sdk";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { fetchGuestToken } from "../../api/endpoints";
import { ErrorState, LoadingState } from "../ui/States";

interface EmbeddedDashboardProps {
  /** PortalDashboard key; Django maps it to the Superset dashboard and authorises the user. */
  dashboardKey: string;
  title: string;
}

const MIN_HEIGHT = 640;

function messageFor(error: ApiError): { title: string; message: string; retry: boolean } {
  if (error.status === 403)
    return { title: "This dashboard is not available to you", message: error.message, retry: false };
  if (error.status === 404) return { title: "Dashboard not found", message: error.message, retry: false };
  return {
    title: "The dashboard could not be loaded",
    message: error.status === 503 ? "The dashboard service is not reachable right now." : error.message,
    retry: true,
  };
}

/**
 * A Superset dashboard embedded with the official Embedded SDK.
 *
 * The browser never holds Superset credentials: Django checks the user's module and branch and
 * returns a 5-minute guest token for this one dashboard (with the branch as row-level security).
 * The SDK renews the token before it expires by calling Django again, so access ends within
 * minutes of signing out or losing the role. Superset runs on its own origin inside an iframe.
 */
export function EmbeddedDashboard({ dashboardKey, title }: EmbeddedDashboardProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let cancelled = false;
    let handle: EmbeddedHandle | null = null;
    let resizeTimer: number | undefined;

    (async () => {
      try {
        const first = await fetchGuestToken(dashboardKey);
        if (cancelled) return;
        let firstToken: string | null = first.token;
        handle = await embedDashboard({
          id: first.embedded_id,
          supersetDomain: first.superset_url,
          mountPoint: mount,
          // First call uses the token fetched above; renewals ask Django again.
          fetchGuestToken: async () => {
            if (firstToken) {
              const token = firstToken;
              firstToken = null;
              return token;
            }
            return (await fetchGuestToken(dashboardKey)).token;
          },
          dashboardUiConfig: {
            hideTitle: true, // the page header shows the title
            hideChartControls: false, // keep chart menus: download, drill-down, full screen
            filters: { visible: true, expanded: true },
          },
          iframeTitle: `${title} dashboard`,
          // Superset checks that the iframe comes from an allowed origin: send the origin only.
          referrerPolicy: "strict-origin-when-cross-origin",
        });
        if (cancelled) {
          handle.unmount();
          return;
        }
        setStatus("ready");
        // Grow the iframe with the dashboard so the page, not the frame, scrolls.
        resizeTimer = window.setInterval(async () => {
          try {
            const size = await handle!.getScrollSize();
            const iframe = mount.querySelector("iframe");
            if (iframe) iframe.style.height = `${Math.max(MIN_HEIGHT, Math.ceil(size.height))}px`;
          } catch {
            /* the dashboard is still loading */
          }
        }, 1000);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err : new ApiError(0, "embed_failed", "The dashboard could not be displayed."));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      window.clearInterval(resizeTimer);
      handle?.unmount();
      mount.replaceChildren();
    };
  }, [dashboardKey, title, attempt]);

  const problem = error ? messageFor(error) : null;
  return (
    <div className="dashboard-frame" data-dashboard={dashboardKey} aria-busy={status === "loading"}>
      {status === "loading" && <LoadingState message={`Loading the ${title} dashboard…`} />}
      {status === "error" && problem && (
        <ErrorState
          title={problem.title}
          message={problem.message}
          onRetry={
            problem.retry
              ? () => {
                  setError(null);
                  setStatus("loading");
                  setAttempt((n) => n + 1);
                }
              : undefined
          }
        />
      )}
      <div ref={mountRef} className={["dashboard-frame__mount", status === "ready" ? "" : "is-hidden"].join(" ")} />
    </div>
  );
}
