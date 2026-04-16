import { defineConfig, devices } from "@playwright/test";

/**
 * Phase 7d.7 — Playwright E2E config.
 *
 * Runs against a live Nexus instance. Default targets production
 * (https://nexus.dynaminds.pl); set E2E_BASE_URL to point elsewhere.
 *
 * CI runs in a separate workflow (e2e.yml) triggered on demand or
 * nightly — not blocking PR-level CI. See .github/workflows/e2e.yml.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "https://nexus.dynaminds.pl",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
