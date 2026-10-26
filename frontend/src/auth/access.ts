import type { Domain, UserScope } from "../api/types";

/**
 * What a page needs. This only decides what the INTERFACE shows: every API call is authorised
 * again by Django (and every embedded dashboard by its guest token), so hiding a link is never
 * the security boundary.
 */
export type Requirement =
  | { kind: "authenticated" }
  | { kind: "any-domain" }
  | { kind: "domain"; domain: Domain }
  | { kind: "admin" }
  | { kind: "author" };

export const ADMIN_ROLE = "Administrator";

export function isAdmin(user: UserScope): boolean {
  return user.roles.includes(ADMIN_ROLE);
}

export function canAccess(user: UserScope, requirement: Requirement): boolean {
  switch (requirement.kind) {
    case "authenticated":
      return true;
    case "any-domain":
      return user.domains.length > 0;
    case "domain":
      return user.domains.includes(requirement.domain);
    case "admin":
      return isAdmin(user);
    case "author":
      return user.author_domains.length > 0;
  }
}

/** May build (in Superset) and publish dashboards for this module (ADR-044). */
export function canAuthor(user: UserScope, domain: Domain): boolean {
  return user.author_domains.includes(domain);
}

/** Human-readable role for the header ("DrukSmart HR Manager" -> "HR Manager"). */
export function roleLabel(user: UserScope): string {
  if (user.roles.length === 0) return "No role assigned";
  return user.roles.map((r) => r.replace(/^DrukSmart\s+/, "")).join(", ");
}

/**
 * A safe in-app path to return to after signing in: only same-app relative paths, never another
 * site ("//evil.example") and never the login page itself.
 */
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return "/";
  if (raw === "/login" || raw.startsWith("/login?") || raw.startsWith("/login/")) return "/";
  return raw;
}
