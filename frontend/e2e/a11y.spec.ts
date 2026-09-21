/**
 * Dostępność kluczowych ekranów (QA-11, zakres minimalny planu poprawy).
 *
 * `@stack`. Blokują wyłącznie naruszenia o wadze `critical` — pełny zestaw
 * reguł axe dałby dziś dziesiątki znalezisk bez priorytetu i test, który
 * wszyscy nauczyliby się ignorować. Naruszenia `serious` trafiają do
 * załącznika raportu, żeby dało się je triażować bez blokowania merge'a.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page, TestInfo } from "@playwright/test";
import { test, expect } from "./helpers/api";
import { createClient, createJob } from "./helpers/entities";

async function expectNoCriticalViolations(page: Page, testInfo: TestInfo, label: string) {
  const results = await new AxeBuilder({ page }).analyze();
  const critical = results.violations.filter((violation) => violation.impact === "critical");
  const serious = results.violations.filter((violation) => violation.impact === "serious");
  await testInfo.attach(`axe-${label}.json`, {
    body: JSON.stringify({ critical, serious }, null, 2),
    contentType: "application/json",
  });
  expect(
    critical.map((violation) => `${violation.id}: ${violation.help} (${violation.nodes.length})`),
    `krytyczne naruszenia dostępności na ekranie ${label}`
  ).toEqual([]);
}

test.describe("Dostępność @stack", () => {
  test("ekran logowania", async ({ browser }, testInfo) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();
    const baseURL = process.env.E2E_BASE_URL || "https://nexus.dynaminds.pl";
    await page.goto(`${baseURL}/login`);
    await expect(page.locator("#login-email")).toBeVisible();
    await expectNoCriticalViolations(page, testInfo, "login");
    await context.close();
  });

  test("lista kandydatów", async ({ page }, testInfo) => {
    await page.goto("/candidates");
    await expect(page.getByRole("heading", { name: "Kandydaci", level: 1 })).toBeVisible();
    await expectNoCriticalViolations(page, testInfo, "candidates");
  });

  test("tablica rekrutacji", async ({ admin, page }, testInfo) => {
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id);
    await page.goto(`/jobs/${job.id}?tab=board`);
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    await expectNoCriticalViolations(page, testInfo, "job-board");
  });

  test("tabela rekrutacji (widok domyślny)", async ({ admin, page }, testInfo) => {
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id);
    await page.goto(`/jobs/${job.id}`);
    await expect(page.getByRole("navigation", { name: "Etapy rekrutacji" })).toBeVisible();
    await expectNoCriticalViolations(page, testInfo, "job-table");
  });
});
