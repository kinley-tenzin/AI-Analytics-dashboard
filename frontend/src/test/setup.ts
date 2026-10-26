import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// findBy*/waitFor wait up to 5 s instead of 1 s: on a busy laptop (the whole Docker stack running)
// a first render occasionally took longer than 1 s and failed a correct test (seen once in Task 10.3).
configure({ asyncUtilTimeout: 5000 });

// No test talks to a real Superset: by default the Embedded SDK resolves to a dashboard handle that
// does nothing (AnalyticsPages.test.tsx replaces it with its own recording mock).
vi.mock("@superset-ui/embedded-sdk", () => ({
  embedDashboard: vi.fn(async () => ({ unmount: () => undefined, getScrollSize: async () => ({ width: 0, height: 0 }) })),
}));

afterEach(() => {
  cleanup();
  document.cookie.split(";").forEach((c) => {
    const name = c.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
});
