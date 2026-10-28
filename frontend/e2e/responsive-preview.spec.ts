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
  "/preview/candidate-profile?tab=screening",
  "/preview/candidate-profile?employed=1",
  "/preview/candidate-profile?tab=activity",
  "/preview/candidate-profile?tab=cv",
  "/preview/candidate-profile?tab=documents",
  "/preview/candidate-profile?tab=documents&role=recruiter",
  "/preview/career-share",
  "/preview/sales",
  "/preview/sales?view=list",
  "/preview/champion-profile",
  "/preview/chat-notifications",
  "/preview/topbar-topics",
  "/preview/client-orders",
  "/preview/client-orders?order=5015",
  "/preview/client-playbook",
  "/preview/client-profile-tabs",
  "/preview/client-profile-tabs?tab=zasady",
  "/preview/client-profile-tabs?tab=projekty",
  "/preview/client-profile-tabs?tab=importy-md&import=3302",
  "/preview/client-profile-tabs?tab=zespol",
  "/preview/client-profile-tabs?tab=kontakty",
  "/preview/client-profile-tabs?tab=umowy-ramowe&framework=7001",
  "/preview/client-profile-tabs?tab=analityka",
  "/preview/clients-list",
  "/preview/clients-list?category=inactive&page=1",
  "/preview/clients-list?view=contacts",
  "/preview/contact-queue",
  "/preview/contract-candidate-contact",
  "/preview/contracts-consolidation",
  "/preview/cpro-queue",
  "/preview/candidate-followup",
  "/preview/cv-generator",
  "/preview/cv-generator-client-rules",
  "/preview/cv-qc",
  "/preview/cv-editor",
  "/preview/interview-notifications",
  "/preview/job-ad",
  "/preview/job-ad?tab=jjit",
  "/preview/job-ad?state=published",
  "/preview/custom-dashboard",
  "/preview/cv-search",
  "/preview/daily",
  "/preview/dl-alerts",
  "/preview/ezdrowie-contract-structure",
  "/preview/finance-order-changes",
  "/preview/finance-order-pdfs",
  "/preview/finance-results",
  "/preview/finance-results?view=archive",
  "/preview/finance-results?view=md",
  "/preview/insights",
  "/preview/insights?as=hor&view=zespol",
  "/preview/insights?as=admin&view=firma",
  "/preview/insights?as=hor&view=raporty",
  "/preview/inactive-clients-cleanup",
  "/preview/contract-docs-sharepoint",
  "/preview/insights-seniority",
  "/preview/jarvis",
  "/preview/kariera",
  "/preview/kpi-targets",
  "/preview/kpi-topbar",
  "/preview/kpi-who-counts",
  "/preview/jobs-list-v3",
  "/preview/job-board-screening",
  "/preview/job-board-screening?state=closed",
  "/preview/screening-form",
  "/preview/screening-form?state=filled",
  "/preview/screening-form?state=note",
  "/preview/screening-form?state=readonly",
  "/preview/screening-form?state=history",
  "/preview/dl-review",
  "/preview/dl-review?state=queue",
  "/preview/dl-review?state=returned",
  "/preview/dl-review?layout=panel",
  // Pas „Do wysłania do klienta” (13.10.2026): kolejka, pusta kolejka i przegląd po kolei.
  "/preview/dl-send",
  "/preview/dl-send?state=empty",
  "/preview/dl-send?state=sequence",
  "/preview/champion-workspace",
  "/preview/champion-workspace?ptab=tech",
  "/preview/champion-workspace?ptab=client",
  "/preview/champion-workspace?ptab=team",
  "/preview/champion-workspace?as=recruiter",
  "/preview/job-team-panel",
  "/preview/job-team-panel?as=hor",
  "/preview/job-team-panel?as=recruiter",
  "/preview/login",
  "/preview/my-people",
  "/preview/new-job",
  "/preview/new-job?state=request",
  "/preview/new-job?state=gaps",
  "/preview/new-job?state=automatic",
  // Jeden ekran (10.10.2026): pusty formularz na całą szerokość, braki po próbie
  // utworzenia, propozycje przy polach i odczyt pliku Profilu Championa.
  "/preview/new-job?state=manual",
  "/preview/new-job?state=attempted",
  "/preview/new-job?state=offers",
  "/preview/new-job?state=champion",
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
  "/preview/notification-settings",
  "/preview/notification-settings?tab=moje",
  "/preview/notification-settings?tab=maile",
  "/preview/notification-settings?as=recruiter",
  // Ustawienia → „Klucze API” (14.10.2026): lista kont, klucz pokazany raz, formularz, pusto.
  "/preview/api-keys",
  "/preview/api-keys?state=revealed",
  "/preview/api-keys?state=create",
  "/preview/api-keys?state=empty",
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
  // „Ludzie w NEXUSIE” (17.10.2026): harnessy 14 makiet raportu, każdy stan.
  "/preview/hr-dashboard",
  "/preview/hr-dashboard?as=manager",
  "/preview/hr-dashboard?as=reception",
  "/preview/hr-my-time",
  "/preview/hr-my-time?state=request&tab=leave",
  "/preview/hr-my-time?tab=month",
  "/preview/hr-my-time?tab=bonuses",
  "/preview/hr-calendar",
  "/preview/hr-calendar?as=manager",
  "/preview/hr-approvals",
  "/preview/hr-approvals?state=hr",
  "/preview/hr-approvals?state=covering",
  "/preview/hr-person",
  "/preview/hr-person?as=manager",
  "/preview/hr-person?as=colleague",
  "/preview/hr-payroll",
  "/preview/hr-payroll?state=team",
  "/preview/hr-payroll?state=months",
  "/preview/hr-offboarding",
  "/preview/hr-offboarding?state=draft",
  "/preview/hr-offboarding?state=form",
  "/preview/hr-onboarding",
  "/preview/hr-onboarding?state=case",
  "/preview/hr-onboarding?state=draft",
  "/preview/hr-onboarding?state=contract",
  "/preview/hr-onboarding?state=paths",
  "/preview/hr-care",
  "/preview/hr-care?state=techcard",
  "/preview/hr-care?state=list",
  "/preview/hr-care?state=conversation",
  "/preview/hr-care?state=list&contract=4504",
  "/preview/hr-care?state=list&tab=consultants",
  "/preview/hr-care?state=list&tab=clients",
  "/preview/hr-care?state=cadence&tab=consultants",
  "/preview/hr-care?state=team",
  "/preview/hr-client-tech",
  "/preview/hr-cases",
  "/preview/hr-cases?state=detail",
  "/preview/hr-cases?state=board-care",
  "/preview/hr-cases?state=todo-list",
  "/preview/hr-cases?state=panel-care",
  "/preview/hr-cases?state=who",
  "/preview/hr-equipment",
  "/preview/hr-equipment?tab=items&view=modele",
  "/preview/hr-equipment?tab=tasks",
  "/preview/hr-equipment?tab=protocols",
  "/preview/hr-equipment?tab=prices",
  "/preview/hr-equipment?tab=import",
  "/preview/hr-equipment?tab=intune",
  "/preview/hr-equipment-issue",
  "/preview/hr-equipment-issue?state=model",
  "/preview/hr-equipment-issue?state=person",
  "/preview/hr-equipment-issue?state=return",
  "/preview/hr-structure",
  "/preview/hr-team",
  "/preview/hr-client-people",
  "/preview/hr-client-people?state=drzewo",
  "/preview/hr-client-people?state=popyt",
  "/preview/hr-announcements",
  "/preview/hr-announcements?state=report&announcement=4102",
  "/preview/hr-announcements?state=new&announcement=new",
  "/preview/hr-announcements?state=off",
  "/preview/hr-settlements",
  "/preview/hr-settlements?state=mandate",
  "/preview/hr-settlements?state=queue",
  "/preview/hr-settlements?state=mismatch&settlement=5003",
  "/preview/hr-settlements?state=billing",
  "/preview/hr-documents",
  "/preview/hr-documents?state=payroll",
  "/preview/hr-documents?state=empty",
  "/preview/hr-documents?state=retention",
  "/preview/hr-agreements",
  "/preview/hr-agreements?state=new",
  "/preview/hr-agreements?state=issues",
  "/preview/hr-agreements?state=payroll",
  "/preview/hr-agreements?state=templates",
  "/preview/client-invoicing",
  "/preview/client-invoicing?state=finance",
  "/preview/client-invoicing?state=to-invoice",
  "/preview/client-invoicing?state=credits",
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
  // Tablica: nagłówek kolumny „Nowi” — 0,54 (28.09.2026), 0,46 (02.10), 0,30 po
  // kompaktowym nagłówku z „Kandydatami do dodania” w środku (14.10.2026, K-D1).
  { path: "/preview/job-detail", selector: "h3:text-is('Nowi')", maxTop: 0.4, shell: true },
  // Lista rekrutacji: pierwszy wiersz tabeli (0,42).
  { path: "/preview/jobs-list-v3", selector: "tbody tr", maxTop: 0.5, shell: false },
  // Kandydaci: pierwszy wiersz listy (0,59 — panel słów kluczowych jest duży z założenia).
  { path: "/preview/candidates-list", selector: "[data-testid^='candidate-row-']", maxTop: 0.65, shell: false },
  // Profil (04.10.2026): karta osoby i „Podsumowanie” po lewej, zakładki po
  // prawej, od góry (0,18 przy 1280 × 720; do 04.10.2026 0,76). Od 13.10.2026
  // (E1) nad zakładkami stoi pasek osoby: imię, pigułki, kontakt i akcje
  // w trzech rzędach (ok. 170 px), więc zakładki schodzą o tyle niżej.
  // Próg z zapasem na łamanie pigułek na runnerze CI; pomiaru lokalnego
  // brak (za mało miejsca na dysku na `next dev`).
  { path: "/preview/candidate-profile", selector: "[role='tablist']", maxTop: 0.5, shell: false },
  // Zamówienia klienta (wersja B): pierwszy kafelek zamówienia. Od #1959 każde
  // zamówienie MD i kosztowe jest osobnym kafelkiem z numerem i okresem w
  // nagłówku — to on jest pierwszą treścią listy, a `tbody tr` (pierwsza osoba)
  // leży pod nim.
  { path: "/preview/client-orders", selector: "[data-orders-table] [data-order-tile]", maxTop: 0.6, shell: false },
  // Odświeżone listy (02.10.2026). Progi zmierzone 03.10.2026 przy 1280 × 720
  // z ramką + zapas; nagłówek harnessu („Harness — …”) zajmuje ok. 0,1 okna,
  // którego w aplikacji nie ma.
  { path: "/preview/contracts-consolidation", selector: "tbody tr", maxTop: 0.55, shell: false },
  { path: "/preview/order-mail", selector: "[data-testid='order-mail-detail']", maxTop: 0.45, shell: false },
  { path: "/preview/clients-list", selector: "tbody tr", maxTop: 0.55, shell: false },
  { path: "/preview/clients-list?view=contacts", selector: "tbody tr", maxTop: 0.5, shell: false },
  // Profil klienta: pierwszy wiersz tabeli konsultantów (0,61).
  { path: "/preview/client-profile-tabs", selector: "tbody tr", maxTop: 0.68, shell: false },
  // Finanse → Wyniki: pierwszy wiersz tabeli pod kaflami i paskiem importu (0,71).
  { path: "/preview/finance-results", selector: "tbody tr", maxTop: 0.77, shell: false },
  // Finanse → Import MD: pierwszy wiersz importu pod paskiem wgrywania (0,77).
  { path: "/preview/finance-results?view=md", selector: "tbody tr", maxTop: 0.83, shell: false },
  { path: "/preview/finance-order-changes", selector: "[role='button']", maxTop: 0.58, shell: false },
  // Nowa rekrutacja (10.10.2026): formularz stoi na stronie od wejścia, więc
  // pasek klienta i źródeł nad nim ma zostać jednym rzędem. Zmierzone
  // 11.10.2026 z ramką: pasek sekcji na 0,41 / 0,39 / 0,34 okna (pusty
  // formularz) i 0,50 / 0,47 / 0,42 z paskiem „wypełniono N pól” (propozycje).
  // Próg ma zapas na runner CI, który łamie tekst ok. 50 px niżej niż Mac.
  { path: "/preview/new-job?state=manual", selector: "nav[aria-label='Sekcje formularza']", maxTop: 0.5, shell: false },
  { path: "/preview/new-job?state=offers", selector: "nav[aria-label='Sekcje formularza']", maxTop: 0.6, shell: false },
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
 * Podgląd w panelu osoby (D1–D2, 09.10.2026). Do tej daty CV stało w prawej
 * połowie panelu 1200 px: strona miała 533 px (67%), a na laptopie widać było
 * z niej ok. 250 px wysokości. Teraz podgląd stoi po lewej na całą wysokość
 * okna, a panel zakrywa też menu boczne.
 *
 * Progi z pomiaru 09.10.2026 przy 1280 × 720 (strona 703 px w harnessie
 * formularza, strefa 819 px w replice powłoki) z zapasem na pasek przewijania
 * runnera. Element, który znowu zwęzi podgląd, ma przegrać ten test.
 */
test.describe("panel osoby — duży podgląd po lewej na laptopie", () => {
  test("/preview/screening-form: strona CV ma co najmniej 660 px szerokości", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/screening-form?state=nowi");
    const cvPage = page.locator("[data-testid='candidate-preview-pane'] .page").first();
    await expect(cvPage).toBeVisible();
    await page.waitForLoadState("networkidle");
    const zone = await page.locator("[data-testid='person-panel-side']").boundingBox();
    const form = await page.locator("[data-testid='harness-panel-column']").boundingBox();
    // Podgląd po lewej, formularz po prawej.
    expect((zone?.x ?? 9999) + (zone?.width ?? 0)).toBeLessThanOrEqual((form?.x ?? 0) + 1);
    await expect
      .poll(async () => (await cvPage.boundingBox())?.width ?? 0, { timeout: 10_000 })
      .toBeGreaterThanOrEqual(660);
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);
  });

  // 12.10.2026: „Historia osoby” to przycisk obok źródeł CV, nie czwarte źródło —
  // CV zostaje zamontowane pod spodem, więc po powrocie strona ma tę samą
  // szerokość i nie ładuje się od nowa.
  test("/preview/screening-form: „Historia osoby” w podglądzie nie odmontowuje CV", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/screening-form?state=nowi");
    const pane = page.getByTestId("candidate-preview-pane");
    const cvPage = pane.locator(".page").first();
    await expect(cvPage).toBeVisible();
    const pagesBefore = await pane.locator(".page").count();
    const widthBefore = (await cvPage.boundingBox())?.width ?? 0;
    const toggle = pane.getByRole("button", { name: "Historia osoby (8)" });
    await toggle.click();
    const reader = pane.getByRole("region", { name: "Historia osoby" });
    await expect(reader).toBeVisible();
    await expect(reader.getByRole("group", { name: "Rodzaj notatek" }).getByRole("button", { name: /Rozmowy/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(reader.getByRole("article", { name: "Rekrutacja: Analityk systemowy" })).toBeVisible();
    await expect(cvPage).toBeHidden();
    expect(await pane.locator(".page").count(), "strony CV zamontowane pod historią").toBe(pagesBefore);
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);

    await pane.getByRole("button", { name: "CV oryginalne" }).click();
    await expect(reader).toBeHidden();
    await expect(cvPage).toBeVisible();
    const widthAfter = (await cvPage.boundingBox())?.width ?? 0;
    expect(Math.abs(widthAfter - widthBefore), "szerokość strony CV po powrocie").toBeLessThanOrEqual(1);
  });

  // 12.10.2026: przed telefonem rekruter widzi, co już wiemy (stawka, dostępność,
  // tryb) i czym skończyła się ostatnia rekrutacja; „Pokaż” otwiera notatki obok.
  test("/preview/screening-form: profil przed telefonem mówi, co już wiemy, i otwiera historię", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/screening-form?state=nowi");
    const profile = page.getByTestId("before-call-profile");
    // 14.10.2026: blok „Co już wiemy” startuje zwinięty do dwóch linii, żeby
    // formularz ze stawką był widoczny bez przewijania przy 1280 × 720.
    await expect(page.getByRole("spinbutton", { name: /Kwota|Stawka/ }).first()).toBeInViewport();
    await profile.getByRole("button", { name: /Co już wiemy/ }).click();
    const conditions = profile.getByTestId("before-call-conditions");
    await expect(conditions).toContainText("150 zł/h");
    await expect(conditions).toContainText("ostatnio podana 03.2025");
    await expect(conditions).toContainText("Do 2 dni w biurze");
    const earlier = profile.getByRole("region", { name: "Wcześniej u nas" });
    await expect(earlier).toContainText("Analityk systemowy");
    await expect(earlier).toContainText("Odrzucony");
    await earlier.getByRole("button", { name: "Pokaż" }).click();
    await expect(
      page.getByTestId("candidate-preview-pane").getByRole("region", { name: "Historia osoby" }),
    ).toBeVisible();
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);
  });

  test("/preview/job-detail: panel na całą szerokość zakrywa menu boczne", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/job-detail");
    await page.getByRole("link", { name: "Anna Przykładowa" }).first().click();
    const panel = page.locator("aside[data-person-panel][data-size='split']");
    await expect(panel).toBeVisible();
    const zone = await page.locator("[data-testid='person-panel-side']").boundingBox();
    expect(zone?.width ?? 0, "strefa podglądu przy 1280 px").toBeGreaterThanOrEqual(780);
    // Punkt nad menu (x = 100 px) należy do panelu, nie do menu.
    const covered = await page.evaluate(() => {
      const aside = document.querySelector("aside[data-person-panel]");
      const at = document.elementFromPoint(100, 300);
      return Boolean(aside && at && aside.contains(at));
    });
    expect(covered, "panel osoby jest nad menu bocznym").toBe(true);
    // „Zwiń” oddaje menu i Tablicę.
    await panel.getByRole("button", { name: "Zwiń", exact: true }).click();
    await expect(page.locator("aside[data-person-panel][data-size='dock']")).toBeVisible();
    await expect(page.getByTestId("harness-sidebar")).toHaveCSS("z-index", "40");
  });

  // 09.10.2026 (zgłoszenie rekruterów): poza „Screeningiem” do głowy panelu
  // wracały „Warunki” i ramka „Następny etap”, pasek zakładek zjeżdżał na dół,
  // a na treść zakładki zostawało ok. 70 px. Pomiar po zmianie przy 1280 × 720:
  // pasek na tej samej wysokości w każdej zakładce, 389 px na treść. Od tego
  // samego dnia każda zakładka ma podgląd po lewej (do tej pory Umowa,
  // Dopasowanie i Notatki miały panel 760 px), więc pasek nie przesuwa się też
  // w bok.
  test("/preview/job-detail: pasek zakładek stoi w miejscu przy zmianie zakładki", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/job-detail");
    await page.getByRole("link", { name: "Anna Przykładowa" }).first().click();
    const panel = page.locator("aside[data-person-panel]");
    const tabs = panel.getByRole("tablist", { name: "Narzędzia osoby" });
    await expect(tabs).toBeVisible();
    const tops: Record<string, number> = {};
    const lefts: Record<string, number> = {};
    for (const name of ["Screening", "Rozmowy", "Umowa", "Dopasowanie", "Notatki"]) {
      const tab = tabs.getByRole("tab", { name });
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
      await expect(panel).toHaveAttribute("data-size", "split");
      // Jeden widoczny podgląd po lewej — także przy umowie, dopasowaniu i notatkach.
      await expect(panel.locator("[data-person-side-content]:not([hidden])")).toHaveCount(1);
      const bar = await tabs.boundingBox();
      const scroll = await panel.locator("[data-person-scroll]").boundingBox();
      tops[name] = Math.round(bar?.y ?? -1);
      lefts[name] = Math.round(bar?.x ?? -1);
      const room = (scroll?.y ?? 0) + (scroll?.height ?? 0) - ((bar?.y ?? 0) + (bar?.height ?? 0));
      expect(room, `miejsce na treść zakładki „${name}”`).toBeGreaterThanOrEqual(280);
    }
    const values = Object.values(tops);
    expect(Math.max(...values) - Math.min(...values), `górna krawędź paska: ${JSON.stringify(tops)}`).toBeLessThanOrEqual(1);
    const xs = Object.values(lefts);
    expect(Math.max(...xs) - Math.min(...xs), `lewa krawędź paska: ${JSON.stringify(lefts)}`).toBeLessThanOrEqual(1);
    // Fakty i „Następny etap” stoją pod paskiem, w jednej zwiniętej linii.
    await expect(panel.getByRole("button", { name: /Warunki i następny etap/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  // 13.10.2026 (zgłoszenie rekrutera, D1–D4): CV i wymagania da się zwinąć.
  // Na laptopie pasek krytycznych wymagań stoi nad CV, zwinięte CV oddaje
  // miejsce wymaganiom i panelowi po połowie, układ wraca po przeładowaniu,
  // a pasek zakładek panelu dalej stoi w miejscu.
  test("/preview/job-detail: zwinięte CV dzieli ekran po połowie i zostaje zapamiętane", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/job-detail");
    await page.getByRole("link", { name: "Anna Przykładowa" }).first().click();
    const panel = page.locator("aside[data-person-panel][data-size='split']");
    const pane = page.locator("[data-person-side-content]:not([hidden]) [data-testid='candidate-preview-pane']");
    const column = page.getByTestId("person-panel-column");
    await expect(pane.getByTestId("requirements-strip")).toBeVisible();
    expect(Math.round((await column.boundingBox())?.width ?? 0), "kolumna panelu przed zwinięciem").toBe(460);

    await pane.getByRole("button", { name: "Zwiń CV", exact: true }).click();
    await expect(pane.getByRole("button", { name: "Rozwiń CV", exact: true })).toBeVisible();
    await expect(pane.getByRole("region", { name: "Wymagania", exact: true })).toBeVisible();
    await expect(pane.getByRole("region", { name: "Po ludzku", exact: true })).toBeVisible();
    const half = (1280 - 44) / 2;
    await expect
      .poll(async () => (await column.boundingBox())?.width ?? 0, { message: "kolumna panelu po zwinięciu CV" })
      .toBeGreaterThan(half - 2);
    expect((await column.boundingBox())?.width ?? 0).toBeLessThan(half + 2);
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);

    // Zmiana zakładki nie zmienia układu: pasek zakładek stoi w miejscu.
    const tabs = panel.getByRole("tablist", { name: "Narzędzia osoby" });
    const lefts = new Set<number>();
    for (const name of ["Screening", "Rozmowy", "Umowa", "Notatki", "CV"]) {
      const tab = tabs.getByRole("tab", { name });
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
      await expect(panel.locator("[data-person-side-content]:not([hidden])")).toHaveCount(1);
      lefts.add(Math.round((await tabs.boundingBox())?.x ?? -1));
    }
    expect([...lefts], "lewa krawędź paska zakładek").toHaveLength(1);

    // Układ jest pamiętany dla osoby — po przeładowaniu CV dalej zwinięte.
    await page.reload();
    await page.getByRole("link", { name: "Anna Przykładowa" }).first().click();
    await expect(pane.getByRole("button", { name: "Rozwiń CV", exact: true })).toBeVisible();
    await pane.getByRole("button", { name: "Rozwiń CV", exact: true }).click();
    await expect.poll(async () => Math.round((await column.boundingBox())?.width ?? 0)).toBe(460);
    await expect(pane.getByTestId("requirements-strip")).toBeVisible();
  });

  test("/preview/job-detail: zwinięte wymagania dają CV całą strefę na monitorze ok. 1730 px", async ({ page }) => {
    await page.setViewportSize({ width: 1730, height: 815 });
    await page.goto("/preview/job-detail");
    await page.getByRole("link", { name: "Anna Przykładowa" }).first().click();
    const pane = page.locator("[data-person-side-content]:not([hidden]) [data-testid='candidate-preview-pane']");
    await expect(pane).toHaveAttribute("data-dual", "true");
    const cv = pane.getByRole("region", { name: "CV", exact: true });
    await expect(cv).toBeVisible();
    // Dwa podglądy naraz: wymagania obok CV, bez paska.
    await expect(pane.getByTestId("requirements-strip")).toHaveCount(0);
    const before = (await cv.boundingBox())?.width ?? 0;

    await pane.getByRole("button", { name: "Zwiń wymagania", exact: true }).click();
    await expect(pane.getByTestId("requirements-strip")).toBeVisible();
    await expect.poll(async () => (await cv.boundingBox())?.width ?? 0).toBeGreaterThan(before + 400);
    expect(Math.round((await page.getByTestId("person-panel-column").boundingBox())?.width ?? 0)).toBe(520);

    await pane.getByRole("button", { name: "Wszystkie wymagania", exact: true }).click();
    await expect(pane.getByRole("region", { name: "Wymagania", exact: true })).toBeVisible();
    await expect(pane.getByTestId("requirements-strip")).toHaveCount(0);
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);
  });

  // 12.10.2026: panel pokazywał wyłącznie notatki bieżącej rekrutacji, więc
  // osoba z historią wyglądała jak nieznana (1 417 z 3 433 otwartych kart).
  // Zakładka ma „Wcześniej u nas”, a licznik notatek nie może zrzucić jej do
  // drugiego rzędu w kolumnie 460 px (plakietka `count` to robiła).
  test("/preview/job-detail: „Notatki i historia” pokazuje wcześniejsze notatki osoby", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/job-detail");
    await page.getByRole("link", { name: "Anna Przykładowa" }).first().click();
    const panel = page.locator("aside[data-person-panel]");
    const tabs = panel.getByRole("tablist", { name: "Narzędzia osoby" });
    const notesTab = tabs.getByRole("tab", { name: /Notatki/ });
    await expect(notesTab).toContainText("8");
    await notesTab.click();
    const earlier = panel.getByRole("region", { name: "Wcześniej u nas" });
    await expect(earlier.getByText("8 notatek · 2 rekrutacje · od 2023")).toBeVisible();
    await expect(earlier.getByRole("article", { name: "Rekrutacja: Analityk systemowy" }).getByText("Odrzucony")).toBeVisible();
    await expect(panel.getByRole("region", { name: "Historia w rekrutacji" }).getByText(/Dodany do rekrutacji/)).toBeVisible();
    const tabTops = await tabs
      .getByRole("tab")
      .evaluateAll((els) => [...new Set(els.map((el) => Math.round(el.getBoundingClientRect().top)))]);
    expect(tabTops, "zakładki panelu w jednym rzędzie").toHaveLength(1);
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);

    // Wąski dok: podpis zwiniętej sekcji mówi o historii, „Cała historia” wraca do zakładki.
    await panel.getByRole("button", { name: "Zwiń", exact: true }).click();
    await expect(panel).toHaveAttribute("data-size", "dock");
    const section = panel.getByRole("button", { name: /^Notatki/ });
    await expect(section).toContainText("0 tu · 8 wcześniej");
    await section.click();
    await panel.getByRole("button", { name: "Cała historia (8)" }).click();
    await expect(panel).toHaveAttribute("data-size", "split");
    await expect(notesTab).toHaveAttribute("aria-selected", "true");
  });

  // 09.10.2026 (zgłoszenie z laptopa 1280 × 650): w wąskim doku cała głowa
  // (warunki, „Następny etap”, przyciski etapów) stała w miejscu, a na sekcje
  // zostawały 92 px; przy otwartej sprawie zmiany stawki przyciski i pole
  // notatki wypadały poza okno. Teraz w miejscu stoi tylko pasek osoby i pole
  // notatki, reszta przewija się razem — pomiar po zmianie: 393 px.
  test("/preview/job-detail: wąski dok osoby przewija się w całości", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 650 });
    await page.goto("/preview/job-detail");
    const panel = page.locator("aside[data-person-panel]");
    // Druga osoba ma otwartą sprawę zmiany stawki — najwyższy blok akcji.
    for (const name of ["Karol Wzorcowy", "Bartek Testowy"]) {
      await page.getByRole("link", { name }).first().click();
      await expect(panel).toHaveAttribute("data-size", "dock");
      await expect(panel.getByText(name).first()).toBeVisible();
      const scroll = panel.locator("[data-person-scroll]");
      await expect(scroll).toHaveCount(1);
      await expect(scroll.getByTestId("dock-facts")).toBeVisible();
      await expect(scroll.getByTestId("dock-sections")).toBeAttached();
      const area = await scroll.boundingBox();
      expect(area?.height ?? 0, `przewijany obszar doku: ${name}`).toBeGreaterThanOrEqual(350);
      const note = await panel.locator('[data-help="jobs.person.note"]').boundingBox();
      expect((note?.y ?? 0) + (note?.height ?? 0), `pole notatki w oknie: ${name}`).toBeLessThanOrEqual(650);
      expect(await pageOverflowPx(page), `poziomy scroll strony: ${name}`).toBeLessThanOrEqual(1);
    }
  });

  // 12.10.2026 (zgłoszenie rekruterów): pole notatki miało jedną linię 230 px
  // i nie dało się go powiększyć. Rośnie z tekstem do 10 linii, a „Powiększ”
  // otwiera je na cały panel pod paskiem osoby — wszystko w oknie 1280 × 650.
  test("/preview/job-detail: pole notatki rośnie, a duże okno pisania mieści się w oknie laptopa", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 650 });
    await page.goto("/preview/job-detail");
    await page.getByRole("link", { name: "Karol Wzorcowy" }).first().click();
    const panel = page.locator("aside[data-person-panel]");
    await expect(panel).toHaveAttribute("data-size", "dock");
    const composer = panel.locator('[data-help="jobs.person.note"]');
    const field = panel.getByRole("textbox", { name: "Dodaj notatkę" });
    const bottom = async () => {
      const box = await composer.boundingBox();
      return (box?.y ?? 0) + (box?.height ?? 0);
    };

    await field.click();
    await field.fill(Array.from({ length: 14 }, (_, i) => `linia ${i + 1}`).join("\n"));
    const grown = await field.boundingBox();
    expect(grown?.width ?? 0, "pole na szerokość panelu").toBeGreaterThanOrEqual(340);
    expect(grown?.height ?? 0, "pole rośnie z tekstem").toBeGreaterThanOrEqual(190);
    expect(grown?.height ?? 0, "sufit 10 linii").toBeLessThanOrEqual(240);
    expect(await bottom(), "kompozytor z długim tekstem w oknie").toBeLessThanOrEqual(650);

    await panel.getByRole("button", { name: "Powiększ pole notatki" }).click();
    await expect(panel.getByTestId("dock-body")).toBeHidden();
    await expect(panel.getByTestId("dock-person-bar")).toBeVisible();
    expect((await field.boundingBox())?.height ?? 0, "duże okno pisania").toBeGreaterThanOrEqual(300);
    expect(await bottom(), "duże okno w oknie").toBeLessThanOrEqual(650);

    // Lista „@” staje przy linii kursora — w całości w panelu, nie pod górnym paskiem.
    await field.press("Control+End");
    await field.pressSequentially("\n@");
    const list = panel.getByRole("listbox", { name: "Osoby do oznaczenia" });
    await expect(list).toBeVisible();
    const listBox = await list.boundingBox();
    const panelBox = await panel.boundingBox();
    expect(listBox?.y ?? 0, "lista pod górną krawędzią panelu").toBeGreaterThanOrEqual(panelBox?.y ?? 0);
    expect((listBox?.y ?? 0) + (listBox?.height ?? 0), "lista w oknie").toBeLessThanOrEqual(650);

    // Esc zamyka najwyższą warstwę: listę, potem duże okno. Panel i tekst zostają.
    await page.keyboard.press("Escape");
    await expect(list).toBeHidden();
    await page.keyboard.press("Escape");
    await expect(panel.getByTestId("dock-body")).toBeVisible();
    await expect(panel).toHaveAttribute("data-size", "dock");
    await expect(field).toHaveValue(/linia 14/);
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);

    // „Powiększ”, potem „Rozwiń”, potem Esc: nasłuch Tablicy rejestruje się po
    // „Rozwiń” na nowo i działa jako DRUGI — jedno naciśnięcie zamykało wtedy
    // i duże okno, i rozwinięcie (przegląd kodu 12.10.2026; jsdom tego nie pokaże).
    await panel.getByRole("button", { name: "Powiększ pole notatki" }).click();
    await panel.getByRole("button", { name: "Rozwiń", exact: true }).click();
    await expect(panel).toHaveAttribute("data-size", "split");
    await page.keyboard.press("Escape");
    await expect(panel.getByTestId("dock-body")).toBeVisible();
    await expect(panel).toHaveAttribute("data-size", "split");
  });
});

/**
 * Duży monitor (zgłoszenie 02.10.2026): listy kończyły się na 1400 px przy
 * pustych bokach ekranu. Tabela ma wypełniać okno bez limitu szerokości, a dane
 * spod głównej wartości dostają własne kolumny od 1700 px szerokości tabeli
 * (`lib/wide-table.ts`); na laptopie zostaje układ zwarty.
 *
 * Lista rekrutacji ma od #1985 jeden układ dla każdej szerokości (bez kolumn
 * szerokiej tabeli) — `wideHeader: null`, sprawdzamy samo wypełnienie okna.
 * Na listach stoi też szyna „Otwarte karty” (od 1920 px rozwinięta, 240 px),
 * więc „wypełnia” znaczy: od szyny albo lewego marginesu do prawego marginesu.
 */
const WIDE_TABLES: ReadonlyArray<{
  path: string;
  wideHeader: string | null;
  dismissDialog: boolean;
}> = [
  { path: "/preview/jobs-list-v3", wideHeader: null, dismissDialog: false },
  { path: "/preview/contracts-consolidation", wideHeader: "Rekrutacja", dismissDialog: true },
];

/** Margines strony + odstęp szyna–tabela; z zapasem na przyszłe zmiany odstępów. */
const WIDE_TABLE_EDGE_PX = 60;

test.describe("duży monitor — tabela listy wypełnia ekran", () => {
  for (const { path, wideHeader, dismissDialog } of WIDE_TABLES) {
    const title = wideHeader
      ? "szerokie kolumny przy 3440 px, zwarty układ przy 1280 px"
      : "tabela od szyny do prawej krawędzi przy 3440 px, bez przelewu przy 1280 px";
    test(`${path}: ${title}`, async ({ page }) => {
      const header = wideHeader
        ? page.locator("thead th", { hasText: new RegExp(`^${wideHeader}$`, "i") }).first()
        : null;
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
          // Bez limitu szerokości: tabela zajmuje okno poza marginesami strony
          // i szyną „Otwarte karty”, jeśli ta stoi po lewej.
          const rail = page.locator("aside[aria-label^='Otwarte']").first();
          const railBox = (await rail.isVisible()) ? await rail.boundingBox() : null;
          const leftEdge = railBox ? railBox.x + railBox.width : 0;
          expect(box?.x ?? width, "tabela zaczyna się przy lewej krawędzi albo szynie").toBeLessThan(
            leftEdge + WIDE_TABLE_EDGE_PX,
          );
          expect((box?.x ?? 0) + (box?.width ?? 0), "tabela sięga prawej krawędzi okna").toBeGreaterThan(
            width - WIDE_TABLE_EDGE_PX,
          );
          if (header) await expect(header).toBeVisible();
        } else if (header) {
          await expect(header).toBeHidden();
        }
        expect(await pageOverflowPx(page), `poziomy scroll przy ${width} px`).toBeLessThanOrEqual(1);
      }
    });
  }
});

/**
 * 12.10.2026 (zgłoszenie z pulpitu): każda zmiana filtra w kafelku „Requesty
 * i obłożenie” przewijała stronę na górę — pomiar na produkcji: 1834 → 0 px
 * w tym harnessie, 1000 → 24 px na `/dashboard`. Filtry zapisywał
 * `router.replace(…, { scroll: false })`, a router Next 15 na ZBUDOWANEJ
 * aplikacji gubi `scroll: false`, gdy zmieniają się same parametry adresu
 * (ścieżka „aliased prefetch” pod głównym `loading.tsx`). Serwer deweloperski
 * tej ścieżki nie ma, więc test łapie regresję dopiero na zbudowanym stosie.
 */
test.describe("pulpit — filtr „Requesty i obłożenie” nie przewija strony", () => {
  test("/preview/custom-dashboard: po zmianie filtra pasek filtrów stoi w miejscu", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/custom-dashboard?as=hor");
    const tile = page.getByTestId("dashboard-tile-request_board");
    // `exact`: aktywny filtr dostaje przycisk „Wyczyść filtr: Priorytet” (#2385),
    // którego nazwa też zawiera nazwę pola.
    const priority = tile.getByLabel("Priorytet", { exact: true });
    await expect(priority).toBeVisible();
    const unscrolled = await priority.boundingBox();
    expect(unscrolled?.y ?? 0, "kafelek stoi poniżej pierwszego ekranu").toBeGreaterThan(720);
    await priority.scrollIntoViewIfNeeded();
    const before = await priority.boundingBox();

    await priority.selectOption("p1");
    await expect(page).toHaveURL(/rb_prio=p1/);
    await expect(priority).toHaveValue("p1");
    // Wartość pola idzie przez adres — szybkie pisanie nie może gubić liter.
    const position = tile.getByLabel("Stanowisko", { exact: true });
    await position.pressSequentially("Java Developer", { delay: 30 });
    await expect(position).toHaveValue("Java Developer");
    await expect(page).toHaveURL(/rb_q=Java\+Developer/);

    // Przewinięcie routera przychodzi z klatką po zmianie adresu.
    await page.waitForTimeout(300);
    const after = await priority.boundingBox();
    expect(
      Math.abs((after?.y ?? -1) - (before?.y ?? 0)),
      `pasek filtrów w oknie: przed ${before?.y}, po ${after?.y}`,
    ).toBeLessThanOrEqual(1);
  });
});

test.describe("górny pasek — licznik celów", () => {
  test("/preview/kpi-topbar: licznik celów nie zgniata wyszukiwarki w oknach laptopów", async ({ page }) => {
    // 13.10.2026: trzy podpisane segmenty przy 1280 px z przypiętym menu
    // i długimi okruszkami zostawiały wyszukiwarce 109 px. Licznik ma chować
    // całe segmenty, a wyszukiwarka trzymać 220 px. Tego samego dnia przed
    // licznikiem stanął przycisk Ligi Mistrzów, który się nie ściska, a trzy
    // przełączniki wyglądu zastąpiło jedno menu „Wygląd”.
    for (const size of WINDOWS_LAPTOP_WINDOWS) {
      await page.setViewportSize(size);
      await page.goto("/preview/kpi-topbar");
      const strips = page.getByTestId("shell-strip");
      await expect(strips).toHaveCount(4);
      for (const strip of await strips.all()) {
        const label = `${await strip.getAttribute("aria-label")} @ ${size.width}`;
        const search = await strip.getByTestId("topbar-search").boundingBox();
        expect(search?.width ?? 0, `wyszukiwarka: ${label}`).toBeGreaterThanOrEqual(220);
        const bar = strip.getByTestId("topbar-replica");
        const overflow = await bar.evaluate((el) => el.scrollWidth - el.clientWidth);
        expect(overflow, `pasek bez przelewu: ${label}`).toBe(0);
        // 28.10.2026: stałe okruszki (178 px) wychodziły z 93-pikselowego pudełka
        // pod wyszukiwarkę. Widoczne okruszki kończą się przed nią, a nazwa
        // na końcu ścieżki zostaje (ustępują całe okruszki od początku) —
        // o ile ścieżka ma jakiekolwiek miejsce: najciaśniejszy pasek przy
        // 1280 px zostawia jej 0 px.
        const crumbs = await strip.getByRole("navigation", { name: "Ścieżka" }).evaluate((nav) => {
          const top = nav.getBoundingClientRect().top;
          const items = [...nav.querySelectorAll<HTMLElement>("[data-crumb]")];
          const visible = items.filter((item) => {
            const box = item.getBoundingClientRect();
            return box.width > 0 && Math.abs(box.top - top) < 4;
          });
          return {
            right: Math.max(nav.getBoundingClientRect().left, ...visible.map((i) => i.getBoundingClientRect().right)),
            nameShownOrNoRoom:
              nav.getBoundingClientRect().width < 1 || visible.includes(items[items.length - 1]),
          };
        });
        expect(crumbs.right, `okruszki przed wyszukiwarką: ${label}`).toBeLessThanOrEqual((search?.x ?? 0) + 0.5);
        expect(crumbs.nameShownOrNoRoom, `nazwa na końcu ścieżki widoczna: ${label}`).toBe(true);
        // Co najmniej jeden cały segment zostaje w pierwszym (widocznym) wierszu.
        const visible = await strip
          .getByRole("button", { name: /^(Twoje cele|Cele zespołu|Cel portfela)/ })
          .evaluate((button) => {
            const top = button.getBoundingClientRect().top;
            return [...button.querySelectorAll("[data-kpi-segment]")].filter(
              (segment) => Math.abs(segment.getBoundingClientRect().top - top) < 4,
            ).length;
          });
        expect(visible, `widoczne segmenty: ${label}`).toBeGreaterThanOrEqual(1);
        // W grupie akcji ściska się tylko licznik: przycisk-ikona zostaje 36 px
        // (bez tej reguły „Moi ludzie” kurczył się do 22 px).
        const neighbour = await strip.getByRole("button", { name: "Moi ludzie (atrapa)" }).boundingBox();
        expect(Math.round(neighbour?.width ?? 0), `sąsiedni przycisk: ${label}`).toBe(36);
        const appearance = await strip.getByRole("button", { name: "Wygląd" }).boundingBox();
        expect(Math.round(appearance?.width ?? 0), `menu „Wygląd”: ${label}`).toBe(36);
        // Przycisk Ligi stoi w każdym pasku, cały: nie ściska się i nie ucina tekstu.
        const league = strip.locator("[data-league-button]");
        await expect(league, `przycisk ligi: ${label}`).toBeVisible();
        const leagueClipped = await league.evaluate((el) => el.scrollWidth - el.clientWidth);
        expect(leagueClipped, `przycisk ligi nieprzycięty: ${label}`).toBeLessThanOrEqual(0);
        // Tekst segmentu nie łamie się, a ukryty wiersz nie wystaje do widocznego.
        const glitches = await strip
          .getByRole("button", { name: /^(Twoje cele|Cele zespołu|Cel portfela)/ })
          .evaluate((button) => {
            const box = button.getBoundingClientRect();
            return [...button.querySelectorAll<HTMLElement>("[data-kpi-segment]")].filter((segment) => {
              if (getComputedStyle(segment).display === "none") return false;
              const value = segment.lastElementChild?.getBoundingClientRect();
              const caption = segment.firstElementChild?.getBoundingClientRect();
              const hiddenRow = Math.abs(segment.getBoundingClientRect().top - box.top) >= 4;
              const wrapped = (value?.height ?? 0) > 18;
              const leaks = hiddenRow && (caption?.top ?? box.bottom) < box.bottom - 1;
              return wrapped || leaks;
            }).length;
          });
        expect(glitches, `zawinięte albo wystające segmenty: ${label}`).toBe(0);
      }
    }
  });
});

/**
 * Ten sam błąd routera co wyżej dotyczył każdej zakładki i filtra zapisanego
 * w adresie przez `router.replace(…, { scroll: false })`. Od 12.10.2026 takie
 * zapisy idą przez `useUrlWriter` (natywna historia). Profil kandydata jest
 * reprezentantem: harness stoi pod własną ścieżką, więc zapis idzie tą samą
 * drogą co na produkcji. Czerwony wynik daje tylko zbudowany stos.
 */
test.describe("zakładka zapisana w adresie nie przewija strony", () => {
  test("/preview/candidate-profile: po zmianie zakładki profil zostaje w miejscu", async ({ page }) => {
    // Niskie okno i dwie wysokie zakładki (CV z pięcioma stanowiskami,
    // Notatki z czternastoma wpisami): obie są wyższe od okna, więc krótsza
    // treść nie cofnie przewinięcia sama. Do 13.10.2026 tę rolę grała lewa
    // kolumna profilu — po E1 jest krótka („Do propozycji”).
    await page.setViewportSize({ width: 1280, height: 600 });
    await page.goto("/preview/candidate-profile?tab=cv");
    const tabs = page.getByRole("tablist", { name: "Sekcje profilu kandydata" });
    const cv = tabs.getByRole("tab", { name: /^CV/ });
    const notes = tabs.getByRole("tab", { name: /^Notatki/ });
    await expect(cv).toHaveAttribute("aria-selected", "true");
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollHeight))
      .toBeGreaterThan(700);

    // Lekko przewinięty profil: pasek zakładek nadal widać, początku strony już nie.
    await page.evaluate(() => window.scrollTo(0, 60));
    expect(await page.evaluate(() => window.scrollY), "profil daje się przewinąć").toBe(60);

    for (const [tab, address] of [
      [notes, /tab=activity/],
      [cv, /tab=cv/],
    ] as const) {
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
      await expect(page).toHaveURL(address);
      // Przewinięcie routera przychodzi z klatką po zmianie adresu.
      await page.waitForTimeout(300);
      expect(await page.evaluate(() => window.scrollY), `przewinięcie po ${address}`).toBe(60);
    }
  });
});

/**
 * Lista rekrutacji pamięta ostatni widok osoby (13.10.2026). Powroty, które
 * zależą od prawdziwego routera i historii przeglądarki — jsdom ich nie
 * pokaże: goły adres (menu „Rekrutacje”), „Wstecz” do linku z zakresem
 * równym domyślnemu roli i „Rekrutacje” kliknięte na otwartej liście.
 * Harness ma własny klucz pamięci i zasiane cztery zakresy, więc każdy krok
 * pokazuje wiersze bez sieci.
 */
test.describe("lista rekrutacji — ostatnie filtry wracają po wyjściu", () => {
  const LIST = "/preview/jobs-list-v3";
  const scope = (page: Page, name: RegExp) =>
    page.getByRole("group", { name: "Zakres rekrutacji" }).getByRole("button", { name });
  /** Nawigacja routera aplikacji — to samo, co robi link w menu bocznym. */
  const routerPush = (page: Page, href: string) =>
    page.evaluate((to) => {
      (window as unknown as { next: { router: { push: (url: string) => void } } }).next.router.push(to);
    }, href);

  test("goły adres otwiera ostatni widok, a link z zakresem wygrywa także po „Wstecz”", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(LIST);
    await expect(scope(page, /Moje/)).toHaveAttribute("aria-pressed", "true");
    await scope(page, /Otwarte/).click();
    await expect(page).toHaveURL(/open=1/);

    await routerPush(page, "/login");
    await expect(page).toHaveURL(/\/login/);
    await routerPush(page, LIST);
    await expect(scope(page, /Otwarte/)).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/open=1/);
    await expect(page.locator("tbody tr").first()).toBeVisible();

    // Link z zakresem domyślnym roli pokazuje „Moje” i trzyma zakres w adresie,
    // więc „Wstecz” z innej strony wraca do „Moich”, nie do zapamiętanych „Otwartych”.
    await routerPush(page, `${LIST}?mine=1`);
    await expect(scope(page, /Moje/)).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/mine=1/);
    await routerPush(page, "/login");
    await expect(page).toHaveURL(/\/login/);
    await page.goBack();
    await expect(scope(page, /Moje/)).toHaveAttribute("aria-pressed", "true");
  });

  test("„Rekrutacje” kliknięte na otwartej liście nie gubi filtrów", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(LIST);
    await scope(page, /Wszystkie/).click();
    await expect(page).toHaveURL(/mine=0/);

    // Lista otwarta z gołego adresu: router widzi ten sam adres, komponent zostaje.
    // Nowy wpis historii = router skończył tę nawigację, zanim pójdzie następna.
    const entries = await page.evaluate(() => window.history.length);
    await routerPush(page, LIST);
    await expect.poll(() => page.evaluate(() => window.history.length)).toBe(entries + 1);
    await expect(scope(page, /Wszystkie/)).toHaveAttribute("aria-pressed", "true");
    await routerPush(page, "/login");
    await expect(page).toHaveURL(/\/login/);
    await page.goBack();
    await expect(scope(page, /Wszystkie/)).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("tbody tr").first()).toBeVisible();
  });
});

/**
 * Tablica: upuszczenie karty z dołu długiej kolumny (zgłoszenie 16.10.2026).
 * 29 osób w „Screeningu”, jedna w „Zweryfikowanym”: po przewinięciu tablicy
 * w dół karty nie dało się upuścić na „Zweryfikowany” obok — kolumny miały
 * wysokość okna tablicy, więc krótka kończyła się wyżej niż karta, a pod
 * kursorem nie było pola upuszczenia. Rekruterka musiała przewinąć do góry.
 *
 * Każda kolumna (i jej pole upuszczenia) ma sięgać do dołu najdłuższej.
 * Sprawdzamy to prawdziwym przeciąganiem: karta z dołu „Screeningu” przesunięta
 * w bok podświetla „Zweryfikowany”; Escape przerywa ruch bez zapisu.
 */
test.describe("Tablica — upuszczenie z dołu długiej kolumny", () => {
  test("/preview/pipeline-v4?screening=many: ostatnia karta „Screeningu” trafia w „Zweryfikowany”", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/preview/pipeline-v4?screening=many");
    const board = page.getByTestId("pipeline-board");
    const screening = board.getByRole("group", { name: /^Screening,/ });
    const verified = board.getByRole("group", { name: /^Zweryfikowany,/ });
    const lastCard = screening.locator("[data-rfd-draggable-id]").last();
    await expect(lastCard).toBeAttached();
    await page.waitForLoadState("networkidle");
    await board.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    await expect(lastCard).toBeInViewport();

    const cardBox = await lastCard.boundingBox();
    const verifiedBox = await verified.boundingBox();
    const verifiedDrop = verified.locator("[data-rfd-droppable-id]");
    const dropBox = await verifiedDrop.boundingBox();
    expect(cardBox && verifiedBox && dropBox, "karta i kolumny na ekranie").toBeTruthy();
    if (!cardBox || !verifiedBox || !dropBox) return;
    expect(
      dropBox.y + dropBox.height,
      "dół pola upuszczenia „Zweryfikowanego” vs dół ostatniej karty „Screeningu”",
    ).toBeGreaterThanOrEqual(cardBox.y + cardBox.height - 1);

    // Chwyt za środek karty (bez przycisków), ruch w bok na środek kolumny.
    const startX = cardBox.x + cardBox.width / 2;
    const startY = cardBox.y + 12;
    const targetX = verifiedBox.x + verifiedBox.width / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 10, startY, { steps: 2 });
    await page.mouse.move(targetX, startY, { steps: 12 });
    await expect(verifiedDrop, "„Zweryfikowany” podświetlony pod kartą").toHaveClass(/bg-primary\/10/);
    await page.keyboard.press("Escape");
    await page.mouse.up();
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);
  });
});
