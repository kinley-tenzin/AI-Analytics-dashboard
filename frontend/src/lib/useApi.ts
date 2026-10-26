import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";

export type Loadable<T> =
  | { status: "loading"; data?: T }
  | { status: "ready"; data: T }
  | { status: "error"; error: ApiError };

/**
 * Load data from the API when the component mounts (and on `reload`). Requests are aborted when
 * the component unmounts. A 401 also ends the session globally (see api/client.ts).
 */
export function useApi<T>(fetcher: (signal: AbortSignal) => Promise<T>, key = ""): Loadable<T> & { reload: () => void } {
  const [state, setState] = useState<Loadable<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetcher(controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", error: err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)) });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` identifies the request
  }, [key, attempt]);

  const reload = useCallback(() => {
    setState((s) => ({ status: "loading", data: s.status === "ready" ? s.data : undefined }));
    setAttempt((n) => n + 1);
  }, []);

  return { ...state, reload };
}
