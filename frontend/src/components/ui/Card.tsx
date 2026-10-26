import type { ReactNode } from "react";

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Heading level of the title, to keep the page outline correct. */
  as?: "h2" | "h3";
}

export function Card({ title, subtitle, actions, children, className, as: Heading = "h2" }: CardProps) {
  return (
    <section className={["card", className ?? ""].filter(Boolean).join(" ")}>
      {(title || actions) && (
        <header className="card__header">
          <div>
            {title && <Heading className="card__title">{title}</Heading>}
            {subtitle && <p className="card__subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card__actions">{actions}</div>}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}
