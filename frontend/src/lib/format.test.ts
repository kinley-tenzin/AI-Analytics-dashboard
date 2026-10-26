import { describe, expect, it } from "vitest";

import { ageingLabel, cellLabel, formatAge, formatDate, formatValue } from "./format";

describe("format", () => {
  it("strips the warehouse sort prefix of ageing buckets only", () => {
    expect(ageingLabel("1 1-30 days overdue")).toBe("1-30 days overdue");
    expect(ageingLabel("0 Not yet due")).toBe("Not yet due");
    expect(ageingLabel("4 Over 90 days overdue")).toBe("Over 90 days overdue");
    expect(cellLabel("ageing", "6 Unapplied credit")).toBe("Unapplied credit");
    expect(cellLabel("department", "2 Sales")).toBe("2 Sales");
  });

  it("formats amounts with their currency and two decimals", () => {
    expect(formatValue(166700, "amount", "BTN")).toBe("BTN 166,700.00");
    expect(formatValue(-5000, "amount", "BTN")).toBe("BTN -5,000.00");
    expect(formatValue(null, "amount", "BTN")).toBe("–");
  });

  it("formats counts and days", () => {
    expect(formatValue(1234, "count")).toBe("1,234");
    expect(formatValue(13.5, "days")).toBe("13.5");
  });

  it("formats dates and ages", () => {
    expect(formatDate("2026-10-25")).toBe("25 Oct 2026");
    expect(formatAge(0.4)).toBe("less than an hour ago");
    expect(formatAge(13.8)).toBe("14 h ago");
    expect(formatAge(72)).toBe("3 days ago");
    expect(formatAge(null)).toBe("never");
  });
});
