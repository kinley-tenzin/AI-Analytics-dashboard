import { describe, expect, it } from "vitest";

import { USERS } from "../test/render";
import { canAccess, canAuthor, roleLabel, safeNextPath } from "./access";

describe("canAccess", () => {
  it("limits modules to the user's domains", () => {
    expect(canAccess(USERS.hr!, { kind: "domain", domain: "hr" })).toBe(true);
    expect(canAccess(USERS.hr!, { kind: "domain", domain: "accounts" })).toBe(false);
    expect(canAccess(USERS.accounts!, { kind: "domain", domain: "hr" })).toBe(false);
  });

  it("requires the Administrator role for administration", () => {
    expect(canAccess(USERS.admin!, { kind: "admin" })).toBe(true);
    expect(canAccess(USERS.executive!, { kind: "admin" })).toBe(false);
  });

  it("gives a user without roles no module", () => {
    expect(canAccess(USERS.none!, { kind: "any-domain" })).toBe(false);
    expect(canAccess(USERS.none!, { kind: "authenticated" })).toBe(true);
  });
});

describe("dashboard authoring (ADR-044)", () => {
  it("lets module managers and the administrator manage dashboards", () => {
    expect(canAccess(USERS.hr!, { kind: "author" })).toBe(true);
    expect(canAccess(USERS.accounts!, { kind: "author" })).toBe(true);
    expect(canAccess(USERS.admin!, { kind: "author" })).toBe(true);
    expect(canAccess(USERS.executive!, { kind: "author" })).toBe(false);
    expect(canAccess(USERS.branch!, { kind: "author" })).toBe(false);
  });

  it("limits a manager to their own module", () => {
    expect(canAuthor(USERS.hr!, "hr")).toBe(true);
    expect(canAuthor(USERS.hr!, "accounts")).toBe(false);
  });
});

describe("roleLabel", () => {
  it("drops the DrukSmart prefix", () => {
    expect(roleLabel(USERS.hr!)).toBe("HR Manager");
    expect(roleLabel(USERS.none!)).toBe("No role assigned");
  });
});

describe("safeNextPath", () => {
  it.each([
    ["/hr", "/hr"],
    ["/accounts?x=1", "/accounts?x=1"],
    [null, "/"],
    ["https://evil.example/", "/"],
    ["//evil.example/", "/"],
    ["/\\evil.example", "/"],
    ["/login", "/"],
    ["/login?next=/hr", "/"],
  ])("%s -> %s", (raw, expected) => {
    expect(safeNextPath(raw)).toBe(expected);
  });
});
