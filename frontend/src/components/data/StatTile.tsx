import type { ReactNode } from "react";

interface StatTileProps {
  label: string;
  /** One value, or several lines (e.g. one amount per currency, never added together). */
  values: string[];
  detail?: ReactNode;
  icon?: ReactNode;
}

export function StatTile({ label, values, detail, icon }: StatTileProps) {
  return (
    <div className="stat">
      <div className="stat__top">
        <span className="stat__label">{label}</span>
        {icon && (
          <span className="stat__icon" aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
      {values.length === 0 ? (
        <p className="stat__value stat__value--empty">No data</p>
      ) : (
        values.map((v) => (
          <p key={v} className={["stat__value", values.length > 1 ? "stat__value--multi" : ""].join(" ")}>
            {v}
          </p>
        ))
      )}
      {detail && <p className="stat__detail">{detail}</p>}
    </div>
  );
}
