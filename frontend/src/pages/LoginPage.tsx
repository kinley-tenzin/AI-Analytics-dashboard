import { Eye, EyeOff, LogIn } from "lucide-react";
import { useId, useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { safeNextPath } from "../auth/access";
import { useSession } from "../auth/session";
import { BrandMark } from "../components/layout/BrandMark";
import { usePageTitle } from "../components/layout/PageHeader";
import { Button } from "../components/ui/Button";
import { ErrorState, LoadingState } from "../components/ui/States";

function messageFor(error: ApiError): string {
  switch (error.code) {
    case "invalid_credentials":
    case "invalid_request":
    case "throttled":
      return error.message; // the backend's user-facing text (generic for wrong credentials)
    case "network":
      return "The DrukSmart server could not be reached. Check your connection and try again.";
    case "http_403":
      return "Your sign-in page has expired. Reload the page and try again.";
    default:
      return "Signing in failed because of a server error. Try again; if it continues, contact the administrator.";
  }
}

export function LoginPage() {
  usePageTitle("Sign in");
  const { session, reload, signIn } = useSession();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNextPath(params.get("next"));

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();

  if (session.status === "authenticated" && !submitting) return <Navigate to={next} replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      navigate(next, { replace: true });
    } catch (err) {
      setPassword("");
      setError(messageFor(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err))));
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <section className="login__brand" aria-label="About DrukSmart Analytics">
        <BrandMark inverted />
        <div className="login__hero">
          <h1 className="login__headline">Analytics and AI Dashboard</h1>
          <p className="login__tagline">HR and Accounts insights from ERP systems, with an AI assistant.</p>
        </div>
      </section>
      <section className="login__panel">
        <div className="login__card">
          <h2 className="login__title">Sign in</h2>
          {session.status === "loading" && <LoadingState message="Checking your session…" />}
          {session.status === "error" && (
            <ErrorState title="Cannot reach the server" message={session.error.message} onRetry={reload} />
          )}
          {(session.status === "anonymous" || submitting) && (
            <>
              <p className="login__text">Use DrukSmart Analytics account.</p>
              {session.status === "anonymous" && session.expired && !error && (
                <p className="form-alert form-alert--info" role="status">
                  Your session has ended. Sign in again to continue.
                </p>
              )}
              {error && (
                <p id={errorId} className="form-alert form-alert--error" role="alert">
                  {error}
                </p>
              )}
              <form className="form" onSubmit={onSubmit} noValidate aria-describedby={error ? errorId : undefined}>
                <div className="field">
                  <label htmlFor="username" className="field__label">
                    Username
                  </label>
                  <input
                    id="username"
                    name="username"
                    className="field__input"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    autoFocus
                    required
                    maxLength={150}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    disabled={submitting}
                    aria-invalid={error ? true : undefined}
                  />
                </div>
                <div className="field">
                  <label htmlFor="password" className="field__label">
                    Password
                  </label>
                  <div className="field__with-action">
                    <input
                      id="password"
                      name="password"
                      className="field__input"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={submitting}
                      aria-invalid={error ? true : undefined}
                    />
                    <button
                      type="button"
                      className="icon-btn field__action"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      aria-pressed={showPassword}
                      disabled={submitting}
                    >
                      {showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
                    </button>
                  </div>
                </div>
                <Button type="submit" className="btn--block" disabled={submitting} icon={<LogIn size={18} aria-hidden="true" />}>
                  {submitting ? "Signing in…" : "Sign in"}
                </Button>
              </form>
              <p className="login__note">
                Accounts are created by the DrukSmart administrator. Repeated failed attempts lock the account for 15
                minutes.
              </p>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
