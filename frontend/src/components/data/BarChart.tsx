import { BarChart3, Table2 } from "lucide-react";
import { useId, useState } from "react";

export interface Bar {
  label: string;
  value: number;
  /** Already-formatted value shown at the bar tip and in the table. */
  display: string;
}

interface BarChartProps {
  title: string;
  /** Column headings for the table view. */
  labelHeading: string;
  valueHeading: string;
  bars: Bar[];
  /** Plain-text summary for screen readers (the chart itself is aria-hidden). */
  summary: string;
}

/**
 * Horizontal bar chart for ONE series (single hue, so no legend), with the value at each bar tip,
 * a hover/focus highlight and a table view. Negative values (e.g. unapplied credit) extend left
 * of the zero line. Built with HTML so labels never overflow and it works with the strict CSP.
 */
export function BarChart({ title, labelHeading, valueHeading, bars, summary }: BarChartProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [active, setActive] = useState<number | null>(null);
  const titleId = useId();

  const min = Math.min(0, ...bars.map((b) => b.value));
  const max = Math.max(0, ...bars.map((b) => b.value));
  const span = max - min || 1;
  const zero = (-min / span) * 100; // position of the zero line, in % of the track

  return (
    <figure className="chart" aria-labelledby={titleId}>
      <figcaption className="chart__header">
        <span id={titleId} className="chart__title">
          {title}
        </span>
        <div className="segmented" role="group" aria-label={`${title}: view`}>
          <button
            type="button"
            className="segmented__btn"
            aria-pressed={view === "chart"}
            onClick={() => setView("chart")}
          >
            <BarChart3 size={14} aria-hidden="true" /> Chart
          </button>
          <button
            type="button"
            className="segmented__btn"
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
          >
            <Table2 size={14} aria-hidden="true" /> Table
          </button>
        </div>
      </figcaption>

      {view === "chart" ? (
        <>
          <p className="visually-hidden">{summary}</p>
          <ul className="bars" aria-hidden="true" onMouseLeave={() => setActive(null)}>
            {bars.map((bar, i) => {
              const width = (Math.abs(bar.value) / span) * 100;
              const left = bar.value >= 0 ? zero : zero - width;
              return (
                <li
                  key={bar.label}
                  className={["bars__row", active === i ? "bars__row--active" : ""].join(" ")}
                  onMouseEnter={() => setActive(i)}
                >
                  <span className="bars__label" title={bar.label}>
                    {bar.label}
                  </span>
                  <span className="bars__track">
                    {min < 0 && <span className="bars__zero" style={{ left: `${zero}%` }} />}
                    <span
                      className={["bars__bar", bar.value < 0 ? "bars__bar--negative" : ""].join(" ")}
                      style={{ left: `${left}%`, width: `${Math.max(width, bar.value === 0 ? 0 : 0.8)}%` }}
                    />
                  </span>
                  <span className="bars__value">{bar.display}</span>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="visually-hidden">{title}</caption>
            <thead>
              <tr>
                <th scope="col">{labelHeading}</th>
                <th scope="col" className="num">
                  {valueHeading}
                </th>
              </tr>
            </thead>
            <tbody>
              {bars.map((bar) => (
                <tr key={bar.label}>
                  <th scope="row">{bar.label}</th>
                  <td className="num">{bar.display}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}
