/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app is served by Django under /app/ (same origin as the /api/ endpoints, so the Django
// session cookie and CSRF protection apply). In development, `npm run dev` serves the app on
// 127.0.0.1:5173 and forwards API and login requests to the Django backend.
const backend = process.env.DRUKSMART_BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": backend,
      "/accounts": backend,
      "/static": backend,
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    // Longer than Testing Library's 5 s async wait (src/test/setup.ts), so a failing query
    // reports its own error instead of a bare test timeout.
    testTimeout: 15000,
  },
});
