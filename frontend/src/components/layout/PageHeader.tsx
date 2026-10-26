import { useEffect } from "react";
import type { ReactNode } from "react";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · DrukSmart Analytics`;
  }, [title]);
}

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** Small status line under the title (e.g. reporting date, data freshness). */
  meta?: ReactNode;
}

export function PageHeader({ title, description, actions, meta }: PageHeaderProps) {
  usePageTitle(title);
  return (
    <div className="page-header">
      <div className="page-header__text">
        <h1 className="page-header__title">{title}</h1>
        {description && <p className="page-header__description">{description}</p>}
        {meta && <div className="page-header__meta">{meta}</div>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </div>
  );
}
