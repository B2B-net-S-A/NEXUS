import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * Playwright E2E — trzy rozdzielne cele (QA-02, plan poprawy po audycie 14.09.2026).
 *
 * - `ci-chromium`: scenariusze oznaczone `@stack`, uruchamiane w CI na
 *   efemerycznym stacku z `docker-compose.e2e.yml`. Tylko tu wolno ZAPISYWAĆ
 *   dane — każdy scenariusz zakłada własne rekordy przez API.
 * - `prod-smoke`: wcześniejsze specy UI przeciw żywej instancji (domyślnie
 *   produkcja). Wyklucza `@stack` i `@writes`, żeby nocny bieg nie tworzył
 *   rekordów biznesowych na produkcji.
 * - `preview-chromium`: publiczne harnessy `/preview/*`, bez logowania.
 *
 * `setup` loguje się raz przez UI i zapisuje stan przeglądarki (token żyje
 * w localStorage, nie w cookies). Wywołania API w scenariuszach NIE korzystają
 * z fixture `request` — ten nie niesie localStorage, więc każde wywołanie szło
 * bez tokena i dostawało 401, które spełniało dawną asercję `< 500`. Wywołania
 * API idą przez `e2e/helpers/api.ts` z nagłówkiem Bearer.
 */
const AUTH_STATE = path.join(__dirname, "e2e", ".auth", "state.json");
const BASE_URL = process.env.E2E_BASE_URL || "https://nexus.dynaminds.pl";
// Trace, wideo i zrzuty nagrywamy WYŁĄCZNIE przy lokalnym stacku (pusta baza CI).
// Przeciw produkcji niosłyby token konta E2E z localStorage i odpowiedzi API
// z danymi z bazy, a raport bywał wgrywany jako artefakt publicznego repo
// (runda 6 audytu).
const isLocalTarget = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/.test(BASE_URL);

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  // Ponowienie POKAZUJE niestabilność (raport „flaky"), nie ukrywa jej —
  // i tylko w CI, lokalnie pierwsza porażka ma być widoczna od razu.
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: BASE_URL,
    trace: isLocalTarget ? "retain-on-failure" : "off",
    screenshot: isLocalTarget ? "only-on-failure" : "off",
    video: isLocalTarget ? "retain-on-failure" : "off",
  },
  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "ci-chromium",
      grep: /@stack/,
      testIgnore: /(candidate-ux-preview|responsive-preview)\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: AUTH_STATE,
      },
      dependencies: ["setup"],
    },
    {
      name: "prod-smoke",
      grepInvert: /@stack|@writes/,
      testIgnore: /(candidate-ux-preview|responsive-preview)\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: AUTH_STATE,
      },
      dependencies: ["setup"],
    },
    {
      name: "preview-chromium",
      testMatch: /(candidate-ux-preview|responsive-preview)\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
