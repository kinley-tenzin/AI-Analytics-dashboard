import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, SESSION_EXPIRED_EVENT } from "../api/client";
import * as auth from "../api/endpoints";
import type { UserScope } from "../api/types";

/**
 * The signed-in user, as Django sees it (GET /api/v1/auth/session/). Django's HttpOnly session
 * cookie is the only credential; the app never stores tokens or passwords.
 */
export type SessionState =
  | { status: "loading" }
  | { status: "authenticated"; user: UserScope }
  /** `expired`: the session ended while the app was open (shown on the sign-in page). */
  | { status: "anonymous"; expired: boolean }
  | { status: "error"; error: ApiError };

interface SessionContextValue {
  session: SessionState;
  reload: () => void;
  /** Throws ApiError (invalid_credentials, throttled, network, ...) for the form to show. */
  signIn: (username: string, password: string) => Promise<UserScope>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(0, "unknown", String(err));
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    auth
      .fetchSession(controller.signal)
      .then((user) =>
        setSession(user ? { status: "authenticated", user } : { status: "anonymous", expired: false }),
      )
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setSession({ status: "error", error: asApiError(err) });
      });
    return () => controller.abort();
  }, [attempt]);

  // Any API call that finds the session gone (timeout, sign-out in another tab) ends it here too.
  useEffect(() => {
    const onExpired = () =>
      setSession((current) =>
        current.status === "authenticated" ? { status: "anonymous", expired: true } : current,
      );
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  const reload = useCallback(() => {
    setSession({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    const user = await auth.signIn(username, password);
    setSession({ status: "authenticated", user });
    return user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await auth.signOut();
    } finally {
      // Even if the server is unreachable, the app stops showing the user's pages.
      setSession({ status: "anonymous", expired: false });
    }
  }, []);

  const value = useMemo(
    () => ({ session, reload, signIn, signOut }),
    [session, reload, signIn, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

/** The signed-in user; only valid inside the protected layout. */
export function useCurrentUser(): UserScope {
  const { session } = useSession();
  if (session.status !== "authenticated") throw new Error("No authenticated user in this view");
  return session.user;
}
