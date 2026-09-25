import { expect, test, type Page } from "@playwright/test";

/**
 * Responsywność — strażnik przed poziomym scrollem całej strony (audyt
 * 23.09.2026, docs/responsiveness-audit-2026-09-23). Publiczne harnessy
 * renderują prawdziwe komponenty na danych fikcyjnych, bez logowania i bez API.
 *
 * Szerokość ustawiamy `setViewportSize` na zwykłym Chrome desktopowym, a nie
 * emulacją telefonu: emulacja mobilna przy przelewie POSZERZA układ i oddala
 * stronę, więc `scrollWidth > clientWidth` dawało tam zawsze 0 i test
 * przechodziłby przy zepsutym ekranie.
 *
 * Tabela przewijana w swoim kontenerze jest w porządku — liczy się wyłącznie
 * przewijanie CAŁEJ strony.
 */

const WIDTHS = [360, 390, 768, 1024, 1280] as const;

const PAGES = [
  "/preview/b2b-documents",
  "/preview/calendar-cycle",
  "/preview/calendar-cycle?as=dl",
  "/preview/candidates",
  "/preview/candidates-list",
  "/preview/candidates-list?dialog=1",
  "/preview/candidate-profile",
  "/preview/candidate-profile?tab=recruitments",
  "/preview/candidate-profile?tab=activity",
  "/preview/candidate-profile?tab=documents",
  "/preview/career-share",
  "/preview/champion-profile",
  "/preview/client-playbook",
  "/preview/contact-queue",
  "/preview/contract-candidate-contact",
  "/preview/contracts-consolidation",
  "/preview/cpro-queue",
  "/preview/candidate-followup",
  "/preview/cv-generator",
  "/preview/cv-generator-client-rules",
  "/preview/cv-qc",
  "/preview/custom-dashboard",
  "/preview/cv-search",
  "/preview/dl-alerts",
  "/preview/ezdrowie-contract-structure",
  "/preview/finance-order-changes",
  "/preview/finance-order-pdfs",
  "/preview/insights",
  "/preview/insights?as=hor&view=zespol",
  "/preview/insights?as=admin&view=firma",
  "/preview/insights?as=hor&view=raporty",
  "/preview/insights-campaign",
  "/preview/inactive-clients-cleanup",
  "/preview/insights-seniority",
  "/preview/jarvis",
  "/preview/kariera",
  "/preview/kpi-targets",
  "/preview/jobs-list-v3",
  "/preview/login",
  "/preview/my-people",
  "/preview/new-job",
  "/preview/new-job?state=request",
  "/preview/new-job?state=gaps",
  "/preview/order-consultant-picker",
  "/preview/order-ended-lines",
  "/preview/order-lifecycle",
  "/preview/order-mail",
  "/preview/order-md-scopes",
  "/preview/order-new-from-pdf",
  "/preview/order-takeover",
  "/preview/order-tile",
  "/preview/pipeline-v4",
  "/preview/pipeline-v4?as=dl",
  "/preview/procedure-help",
  "/preview/recruitment-v3",
  "/preview/talent-radar",
  "/preview/trainee",
  "/preview/trainee?state=done",
  "/preview/trainee?state=handover",
  "/preview/trainee?state=employment_only",
  "/preview/trainees",
  "/preview/trainees?view=rules",
] as const;

async function pageOverflowPx(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

test.describe("responsywność harnessów — brak poziomego scrolla strony", () => {
  for (const path of PAGES) {
    test(`${path} mieści się w ${WIDTHS.join("/")} px`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow: Record<number, number> = {};
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 900 });
        // Jedna klatka na przeliczenie układu po zmianie szerokości.
        await page.evaluate(
          () => new Promise((resolve) => requestAnimationFrame(() => resolve(null))),
        );
        overflow[width] = await pageOverflowPx(page);
      }
      const broken = Object.entries(overflow).filter(([, px]) => px > 1);
      expect(broken, `poziomy scroll strony (szerokość → px): ${JSON.stringify(overflow)}`).toEqual(
        [],
      );
    });
  }
});
