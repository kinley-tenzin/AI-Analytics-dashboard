/** DrukSmart Analytics word mark (inline SVG, no external assets). */
export function BrandMark({ inverted = false, compact = false }: { inverted?: boolean; compact?: boolean }) {
  return (
    <span className={["brand", inverted ? "brand--inverted" : "", compact ? "brand--compact" : ""].join(" ")}>
      <svg className="brand__logo" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <rect width="32" height="32" rx="7" className="brand__logo-bg" />
        <path
          d="M8 22V10h6.2c4 0 6.8 2.4 6.8 6s-2.8 6-6.8 6H8zm3.4-3h2.7c2.1 0 3.5-1.2 3.5-3s-1.4-3-3.5-3h-2.7v6z"
          className="brand__logo-fg"
        />
        <rect x="21.5" y="9" width="3" height="14" rx="1.5" className="brand__logo-accent" />
      </svg>
      {!compact && (
        <span className="brand__text">
          <span className="brand__name">DrukSmart</span>
          <span className="brand__product">Analytics</span>
        </span>
      )}
    </span>
  );
}
