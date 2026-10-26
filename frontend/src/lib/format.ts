/**
 * Presentation-only formatting of values that the backend has already calculated. No business
 * rule lives here: amounts, counts and dates are displayed exactly as the KPI functions return them.
 */
import type { KpiColumn, KpiResult, Unit } from "../api/types";

const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const money = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatValue(value: unknown, unit: Unit, currency?: string | null): string {
  if (value === null || value === undefined || value === "") return "–";
  if (unit === "label") return String(value);
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (unit === "amount") return `${currency ? `${currency} ` : ""}${money.format(n)}`;
  if (unit === "days") return decimal.format(n);
  return integer.format(n);
}

/**
 * Ageing buckets carry a sort prefix in the warehouse ("1 1-30 days overdue", "6 Unapplied
 * credit"); hide it. Only for the `ageing` column: other labels are shown exactly as stored.
 */
export function ageingLabel(label: string): string {
  return label.replace(/^\d+\s+/, "");
}

/** Display text of one label cell of a KPI result. */
export function cellLabel(column: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  return column === "ageing" ? ageingLabel(String(value)) : String(value);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function formatPeriod(period: { start: string; end: string } | null): string {
  if (!period) return "";
  return `${formatDate(period.start)} – ${formatDate(period.end)}`;
}

export function formatAge(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "never";
  if (hours < 1) return "less than an hour ago";
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function measureColumns(result: KpiResult): KpiColumn[] {
  return result.columns.filter((c) => c.unit !== "label");
}

export function labelColumns(result: KpiResult): KpiColumn[] {
  return result.columns.filter((c) => c.unit === "label");
}
