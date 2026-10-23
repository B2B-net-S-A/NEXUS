/**
 * „Ludzie w NEXUSIE”: wniosek urlopowy (umowa o pracę), zgłoszenie przerwy
 * z B2B z kolizją od koordynatorki (etap 2, D5) i granice dostępu roli „Pracownik”.
 *
 * `@stack`. Zespół z `backend/scripts/seed_hr_demo.py` (krok „Zasiej zespół HR”
 * w `e2e.yml`). Scenariusz musi być powtarzalny na tej samej bazie (lokalny
 * stos, ponowienie w CI): dzień wniosku wybiera podgląd serwera — pierwszy
 * wolny dzień roboczy za co najmniej trzy tygodnie licząc od dziś w Warszawie —
 * a wnioski z testu (znacznik w notatce) są anulowane przed i po biegu.
 * Czerwony `@stack` wyłącza w CI krok harnessów `/preview/*`, więc asercje
 * czekają na stan końcowy ekranu, nie na czas.
 */
import { test, expect, expectStatus, uniqueSuffix } from "./helpers/api";
import {
  HR_ACCOUNTS,
  type BrowserSession,
  cancelLeaveWithMarker,
  displayDay,
  hrApi,
  loginInBrowser,
  pickFreeLeaveDay,
} from "./helpers/hr";

const MARKER = "E2E urlop @stack";
const REPORT_MARKER = "E2E przerwa @stack";

test.describe("Ludzie w NEXUSIE — urlopy i dostęp @stack", () => {
  test("pracownik na UoP składa wniosek w „Mój czas”, przełożona akceptuje, pracownik widzi zatwierdzenie", async ({
    browser,
  }) => {
    // Dwie osobne sesje przeglądarki i dwa logowania — więcej niż domyślne 30 s.
    test.slow();
    const employeeApi = await hrApi(HR_ACCOUNTS.uopEmployee);
    const sessions: BrowserSession[] = [];
    try {
      await cancelLeaveWithMarker(employeeApi, MARKER);
      const day = await pickFreeLeaveDay(employeeApi, 21);
      const term = displayDay(day);
      const note = `${MARKER} ${uniqueSuffix()}`;

      // Pracownik: „Mój czas → Urlop” → „Złóż wniosek”.
      const employee = await loginInBrowser(browser, HR_ACCOUNTS.uopEmployee, "/my-time?tab=leave");
      sessions.push(employee);
      // Pierwszy render po logowaniu (sesja, konfiguracja modułów) — z zapasem.
      await expect(employee.page.getByRole("heading", { name: "Mój czas" })).toBeVisible({
        timeout: 30_000,
      });
      await expect(employee.page).toHaveURL(/\/my-time/);
      await employee.page.getByRole("button", { name: "Złóż wniosek" }).click();

      const dialog = employee.page.getByRole("dialog", { name: "Wniosek o nieobecność" });
      await expect(dialog).toBeVisible();
      await dialog.locator("#leave-start").fill(day);
      await dialog.locator("#leave-end").fill(day);
      await dialog.locator("#leave-note").fill(note);
      // Podgląd serwera liczy dzień roboczy; dopóki go nie ma, wysyłka jest zablokowana.
      await expect(dialog.getByText("1 dzień roboczych")).toBeVisible();
      const send = dialog.getByRole("button", { name: "Wyślij do akceptacji" });
      await expect(send).toBeEnabled();
      await send.click();
      await expect(dialog).toBeHidden();

      const myRows = employee.page.getByRole("row").filter({ hasText: term });
      await expect(myRows.filter({ hasText: "Czeka na akceptację" })).toHaveCount(1);

      // Przełożona: „Ludzie → Akceptacje” → „Akceptuj” przy tym wniosku.
      const manager = await loginInBrowser(browser, HR_ACCOUNTS.manager, "/people/approvals");
      sessions.push(manager);
      await expect(manager.page.getByRole("heading", { name: "Akceptacje" })).toBeVisible({
        timeout: 30_000,
      });
      await expect(manager.page).toHaveURL(/\/people\/approvals/);
      // Skrzynka (makieta 19.10.2026): lista spraw po lewej, decyzja w szczegółach
      // po prawej. Notatka jest tylko w szczegółach — wiersz listy ma termin.
      // Przełożona ma też Zgody, więc w „Wszystko” wnioski i zgody są jedną listą
      // „Do decyzji” (#2556); dawną nazwę ma lista po filtrze „Nieobecności”.
      const leaveChip = manager.page.getByRole("button", { name: /^Nieobecności/ });
      await leaveChip.click();
      await expect(leaveChip).toHaveAttribute("aria-pressed", "true");
      const queue = manager.page.getByRole("list", {
        name: "Wnioski do decyzji (umowa o pracę)",
      });
      const pendingItem = queue.getByRole("listitem").filter({ hasText: term });
      await expect(pendingItem).toHaveCount(1);
      await pendingItem.getByRole("button").click();
      const detail = manager.page.getByRole("region", { name: /^Szczegóły:/ });
      await expect(detail).toContainText(note);
      await detail.getByRole("button", { name: "Akceptuj" }).click();
      await expect(manager.page.getByText("Wniosek zaakceptowany")).toBeVisible();
      await expect(pendingItem).toHaveCount(0);

      // Pracownik po odświeżeniu widzi zatwierdzony wniosek.
      await employee.page.reload();
      await expect(myRows.filter({ hasText: "Zatwierdzony" })).toHaveCount(1);
      await expect(myRows.filter({ hasText: "Czeka na akceptację" })).toHaveCount(0);
    } finally {
      for (const session of sessions) await session.context.close();
      // Zatwierdzony urlop w przyszłości osoba może anulować sama — kolejny bieg
      // zaczyna od czystego kalendarza.
      await cancelLeaveWithMarker(employeeApi, MARKER);
      await employeeApi.dispose();
    }
  });

  test("osoba na B2B zgłasza przerwę bez akceptacji, koordynatorka zgłasza kolizję", async ({
    browser,
  }) => {
    test.slow();
    const contractorApi = await hrApi(HR_ACCOUNTS.employee);
    const sessions: BrowserSession[] = [];
    try {
      await cancelLeaveWithMarker(contractorApi, REPORT_MARKER);
      const day = await pickFreeLeaveDay(contractorApi, 28);
      const term = displayDay(day);
      const note = `${REPORT_MARKER} ${uniqueSuffix()}`;

      // Osoba na B2B: „Mój czas → Przerwy” → „Zgłoś przerwę” (zgłoszenie, nie wniosek).
      const contractor = await loginInBrowser(browser, HR_ACCOUNTS.employee, "/my-time?tab=leave");
      sessions.push(contractor);
      await expect(contractor.page.getByRole("heading", { name: "Mój czas" })).toBeVisible({
        timeout: 30_000,
      });
      await contractor.page.getByRole("button", { name: "Zgłoś przerwę" }).click();
      const dialog = contractor.page.getByRole("dialog", {
        name: "Zgłoś przerwę w świadczeniu usług",
      });
      await expect(dialog).toBeVisible();
      await dialog.locator("#leave-start").fill(day);
      await dialog.locator("#leave-end").fill(day);
      await dialog.locator("#leave-note").fill(note);
      await expect(dialog.getByText("Co się stanie po zgłoszeniu")).toBeVisible();
      const send = dialog.getByRole("button", { name: "Zgłoś przerwę" });
      await expect(send).toBeEnabled();
      await send.click();
      await expect(dialog).toBeHidden();
      const myRows = contractor.page.getByRole("row").filter({ hasText: term });
      await expect(myRows.filter({ hasText: "Zgłoszone" })).toHaveCount(1);

      // Koordynatorka: „Akceptacje” → zgłoszenie do wiadomości, bez „Akceptuj”.
      const manager = await loginInBrowser(browser, HR_ACCOUNTS.manager, "/people/approvals");
      sessions.push(manager);
      await expect(manager.page.getByRole("heading", { name: "Akceptacje" })).toBeVisible({
        timeout: 30_000,
      });
      const reported = manager.page.getByRole("list", {
        name: "Zgłoszone przerwy i nieobecności (B2B, zlecenie) — do wiadomości",
      });
      const item = reported.getByRole("listitem").filter({ hasText: term });
      await expect(item.first()).toBeVisible();
      await item.first().getByRole("button").click();
      const detail = manager.page.getByRole("region", { name: /^Szczegóły:/ });
      await expect(detail).toContainText(note);
      await expect(detail.getByRole("button", { name: "Akceptuj" })).toHaveCount(0);
      await detail.getByRole("button", { name: "Zgłoś kolizję" }).click();
      const conflict = manager.page.getByRole("dialog", { name: "Zgłoś kolizję z terminem" });
      await conflict.locator("#leave-conflict-note").fill(`Wdrożenie u klienta ${uniqueSuffix()}`);
      await conflict.getByRole("button", { name: "Zgłoś kolizję" }).click();
      // Komunikat po zapisie; wiersz zgłoszenia od razu dostaje też dopisek
      // „kolizja zgłoszona · …” (odświeżenie po mutacji), więc szukamy pełnego zdania.
      await expect(
        manager.page.getByText("Kolizja zgłoszona — osoba dostała powiadomienie"),
      ).toBeVisible();

      // Osoba widzi kolizję przy swoim zgłoszeniu; termin dalej jest zgłoszony.
      await contractor.page.reload();
      await expect(myRows.filter({ hasText: "kolizja" })).toHaveCount(1);
      await expect(myRows.filter({ hasText: "Zgłoszone" })).toHaveCount(1);
    } finally {
      for (const session of sessions) await session.context.close();
      await cancelLeaveWithMarker(contractorApi, REPORT_MARKER);
      await contractorApi.dispose();
    }
  });

  test("rola „Pracownik” ląduje w „Mój czas” i nie widzi Płac ani importu z Compassa", async ({
    browser,
  }) => {
    test.slow();
    const staffApi = await hrApi(HR_ACCOUNTS.staff);
    const staff = await loginInBrowser(browser, HR_ACCOUNTS.staff);
    try {
      const { page } = staff;
      // Po logowaniu formularzem ekran logowania nawiguje dwa razy (cel po
      // zalogowaniu, potem sonda sesji → `/`, które middleware odsyła do
      // „Mój czas”). Najpierw stan końcowy ekranu, dopiero potem adres.
      await expect(page.getByRole("heading", { name: "Mój czas" })).toBeVisible({
        timeout: 30_000,
      });
      await expect(page).toHaveURL(/\/my-time(?:\?|$)/);
      // Strona startowa i pulpit prowadzą pracownika z powrotem do „Mój czas”.
      await page.goto("/");
      await expect(page).toHaveURL(/\/my-time(?:\?|$)/);

      // Serwer odmawia Płac; ekran mówi o braku uprawnień zamiast pustej listy.
      await expectStatus(await staffApi.get("/api/hr/payroll/months"), 403, "pracownik → Płace");
      await page.goto("/people/payroll");
      await expect(page.getByRole("status").filter({ hasText: "Brak uprawnień" })).toBeVisible();
      await expect(page.getByText("Płace prowadzi dział Płac.", { exact: false })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Razem" })).toHaveCount(0);

      await expectStatus(
        await staffApi.get("/api/hr/admin/import/batches"),
        403,
        "pracownik → import z Compassa"
      );
      await page.goto("/settings/hr-import");
      await expect(page.getByRole("status").filter({ hasText: "Brak uprawnień" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Import z Compassa" })).toHaveCount(0);
      await expect(page.locator('input[type="file"]')).toHaveCount(0);
    } finally {
      await staff.context.close();
      await staffApi.dispose();
    }
  });
});
