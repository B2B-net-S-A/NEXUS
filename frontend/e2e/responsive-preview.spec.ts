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
  "/preview/b2b-generator",
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
  "/preview/client-orders",
  "/preview/client-orders?order=5015",
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
  "/preview/contract-docs-sharepoint",
  "/preview/insights-seniority",
  "/preview/jarvis",
  "/preview/kariera",
  "/preview/kpi-targets",
  "/preview/jobs-list-v3",
  "/preview/job-board-screening",
  "/preview/job-board-screening?state=closed",
  "/preview/job-team-panel",
  "/preview/job-team-panel?as=hor",
  "/preview/job-team-panel?as=recruiter",
  "/preview/login",
  "/preview/my-people",
  "/preview/new-job",
  "/preview/new-job?state=request",
  "/preview/new-job?state=gaps",
  "/preview/new-job?state=automatic",
  "/preview/order-consultant-picker",
  "/preview/order-ended-lines",
  "/preview/order-lifecycle",
  "/preview/order-mail",
  "/preview/order-md-scopes",
  "/preview/order-new-from-pdf",
  "/preview/order-takeover",
  "/preview/order-tile",
  "/preview/permissions",
  "/preview/permissions?tab=users",
  "/preview/permissions?modal=1",
  "/preview/pipeline-v4",
  "/preview/pipeline-v4?as=dl",
  "/preview/plain-brief",
  "/preview/plain-brief?state=closed",
  "/preview/plain-brief?state=failed",
  "/preview/procedure-help",
  "/preview/recruitment-v3",
  "/preview/request-allocation?screen=board",
  "/preview/request-allocation?screen=board&as=dl",
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

/**
 * Okna laptopów z Windows (zgłoszenie 28.09.2026). Skalowanie ekranu 125–150%
 * daje przeglądarce 1280–1536 px szerokości i 650–860 px wysokości, a UI było
 * układane na szerokich monitorach Maca (2666 × 1229): na laptopie nagłówek
 * i filtry rosły w dół i główną treść widać było dopiero na dole ekranu.
 *
 * Harnessy bez powłoki aplikacji dostają ramkę w CSS — 240 px przypiętego menu
 * (od 1280 px domyślnie przypięte) i 48 px paska górnego. Treść jest wtedy tak
 * wąska jak w aplikacji, a progi Tailwinda (`2xl` = 1536 px) liczą się od
 * szerokości okna jak w aplikacji. `/preview/job-detail` ma powłokę w sobie.
 *
 * Próg to położenie GÓRNEJ krawędzi głównej treści jako ułamek wysokości okna
 * — zmierzone 28.09.2026 + zapas. Nowy element nad listą/tablicą, który ją
 * spycha niżej, ma przegrać ten test, zanim trafi do laptopów zespołu.
 */
const WINDOWS_LAPTOP_WINDOWS = [
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1536, height: 864 },
] as const;

const PRIMARY_CONTENT = [
  // Tablica: nagłówek kolumny „Nowi” (zmierzone 0,54 przy 1280 × 720).
  { path: "/preview/job-detail?empty=1", selector: "h3:text-is('Nowi')", maxTop: 0.6, shell: true },
  // Lista rekrutacji: pierwszy wiersz tabeli (0,42).
  { path: "/preview/jobs-list-v3", selector: "tbody tr", maxTop: 0.5, shell: false },
  // Kandydaci: pierwszy wiersz listy (0,59 — panel słów kluczowych jest duży z założenia).
  { path: "/preview/candidates-list", selector: "[data-testid^='candidate-row-']", maxTop: 0.65, shell: false },
  // Profil: zakładki pod nagłówkiem i faktami — fakty SĄ treścią profilu (0,76).
  { path: "/preview/candidate-profile", selector: "[role='tablist']", maxTop: 0.8, shell: false },
  // Zamówienia klienta (wersja B): pierwszy wiersz tabeli — pigułki w jednym
  // rzędzie, filtr typu w wierszu wyszukiwania (≈0,5 przy 1280 × 720 z ramką).
  { path: "/preview/client-orders", selector: "[data-orders-table] tbody tr", maxTop: 0.6, shell: false },
] as const;

test.describe("okna laptopów z Windows — główna treść w górnej części ekranu", () => {
  for (const { path, selector, maxTop, shell } of PRIMARY_CONTENT) {
    test(`${path}: treść zaczyna się wyżej niż ${Math.round(maxTop * 100)}% okna`, async ({ page }) => {
      const tops: Record<string, number> = {};
      for (const size of WINDOWS_LAPTOP_WINDOWS) {
        await page.setViewportSize(size);
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        if (!shell) {
          await page.addStyleTag({
            content: "html{padding-left:240px;padding-top:48px;box-sizing:border-box}",
          });
        }
        const target = page.locator(selector).first();
        await expect(target).toBeVisible();
        await page.evaluate(
          () => new Promise((resolve) => requestAnimationFrame(() => resolve(null))),
        );
        const box = await target.boundingBox();
        tops[`${size.width}x${size.height}`] = box ? +(box.y / size.height).toFixed(2) : 1;
        expect(await pageOverflowPx(page), `poziomy scroll przy ${size.width} px`).toBeLessThanOrEqual(1);
      }
      const tooLow = Object.entries(tops).filter(([, ratio]) => ratio > maxTop);
      expect(tooLow, `górna krawędź treści (okno → ułamek wysokości): ${JSON.stringify(tops)}`).toEqual(
        [],
      );
    });
  }
});

/**
 * Duży monitor (zgłoszenie 02.10.2026): listy kończyły się na 1400 px przy
 * pustych bokach ekranu. Tabela ma wypełniać okno bez limitu szerokości, a dane
 * spod głównej wartości dostają własne kolumny od 1700 px szerokości tabeli
 * (`lib/wide-table.ts`); na laptopie zostaje układ zwarty.
 */
const WIDE_TABLES = [
  { path: "/preview/jobs-list-v3", wideHeader: "Klient", dismissDialog: false },
  { path: "/preview/contracts-consolidation", wideHeader: "Rekrutacja", dismissDialog: true },
] as const;

test.describe("duży monitor — tabela listy wypełnia ekran", () => {
  for (const { path, wideHeader, dismissDialog } of WIDE_TABLES) {
    test(`${path}: szerokie kolumny przy 3440 px, zwarty układ przy 1280 px`, async ({ page }) => {
      const header = page.locator("thead th", { hasText: new RegExp(`^${wideHeader}$`, "i") }).first();
      for (const [width, wide] of [
        [3440, true],
        [1280, false],
      ] as const) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        if (dismissDialog) await page.keyboard.press("Escape");
        const table = page.locator("table").first();
        await expect(table).toBeVisible();
        const box = await table.boundingBox();
        if (wide) {
          // Bez limitu szerokości: tabela zajmuje okno poza marginesami strony.
          expect(box?.width ?? 0, "tabela wypełnia duży ekran").toBeGreaterThan(width - 120);
          await expect(header).toBeVisible();
        } else {
          await expect(header).toBeHidden();
        }
        expect(await pageOverflowPx(page), `poziomy scroll przy ${width} px`).toBeLessThanOrEqual(1);
      }
    });
  }
});
