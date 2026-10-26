import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router";

type Variant = "primary" | "secondary" | "ghost";
type Size = "md" | "sm";

interface CommonProps {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  children: ReactNode;
}

function classes(variant: Variant, size: Size, extra?: string) {
  return ["btn", `btn--${variant}`, size === "sm" ? "btn--sm" : "", extra ?? ""]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  variant = "primary",
  size = "md",
  icon,
  children,
  className,
  type = "button",
  ...rest
}: CommonProps & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type={type} className={classes(variant, size, className)} {...rest}>
      {icon}
      <span>{children}</span>
    </button>
  );
}

/** An in-app link styled as a button (uses the router, so no full page reload). */
export function ButtonLink({
  to,
  variant = "secondary",
  size = "md",
  icon,
  children,
}: CommonProps & { to: string }) {
  return (
    <Link to={to} className={classes(variant, size)}>
      {icon}
      <span>{children}</span>
    </Link>
  );
}

/** A link to a page outside the React app (Django pages, Superset). */
export function ButtonAnchor({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className,
  ...rest
}: CommonProps & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a className={classes(variant, size, className)} {...rest}>
      {icon}
      <span>{children}</span>
    </a>
  );
}
