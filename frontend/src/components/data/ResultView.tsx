import type { KpiResult } from "../../api/types";
import { cellLabel, formatValue, labelColumns, measureColumns } from "../../lib/format";
import { BarChart } from "./BarChart";

/** Rows of a KPI result as an accessible table (amounts keep their own currency). */
export function ResultTable({ result, caption }: { result: KpiResult; caption: string }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c.name} scope="col" className={c.unit === "label" ? undefined : "num"}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {result.columns.map((c) =>
                c.unit === "label" ? (
                  <td key={c.name}>{cellLabel(c.name, row[c.name])}</td>
                ) : (
                  <td key={c.name} className="num">
                    {formatValue(row[c.name], c.unit, row.currency === undefined ? null : String(row.currency))}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A bar chart when the result is a breakdown (several rows, one measure to show). Labels are the
 * result's grouping columns; currency is part of the label only when several currencies occur,
 * so amounts in different currencies are never on one unlabeled scale.
 */
export function ResultChart({ result }: { result: KpiResult }) {
  const measures = measureColumns(result);
  const currencies = new Set(result.rows.map((r) => r.currency).filter((c) => c !== undefined));
  const labels = labelColumns(result).filter((c) => c.name !== "currency" || currencies.size > 1);
  const measure = measures[0];
  if (!measure || labels.length === 0 || result.rows.length < 2) return null;
  const bars = result.rows.map((row) => ({
    label: labels.map((c) => cellLabel(c.name, row[c.name])).join(" · "),
    value: Number(row[measure.name] ?? 0),
    display: formatValue(row[measure.name], measure.unit, row.currency === undefined ? null : String(row.currency)),
  }));
  return (
    <BarChart
      title={measure.label}
      labelHeading={labels.map((c) => c.label).join(" · ")}
      valueHeading={measure.label}
      bars={bars}
      summary={`${measure.label}: ${bars.map((b) => `${b.label} ${b.display}`).join(", ")}.`}
    />
  );
}
