import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * Phase 7d.7 + Phase 12 — Playwright E2E config.
 *
 * Runs against a live Nexus instance. Default targets production
 * (https://nexus.dynaminds.pl); set E2E_BASE_URL to point elsewhere.
 *
 * Phase 12: adds a `setup` project that logs in once and persists the auth
 * state to `e2e/.auth/state.json`. All `chromium` tests reuse that state,
 * which eliminates the post-login race with the onboarding overlay that
 * caused intermittent timeouts in Phase 9/11.
 */
const AUTH_STATE = path.join(__dirname, "e2e", ".auth", "state.json");

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
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium",
      testIgnore: /candidate-ux-preview\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: AUTH_STATE,
      },
      dependencies: ["setup"],
    },
    {
      name: "preview-chromium",
      testMatch: /candidate-ux-preview\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
