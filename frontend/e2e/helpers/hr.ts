/**
 * Konta i dane scenariuszy „Ludzie w NEXUSIE” (`@stack`).
 *
 * Zespół zakłada `backend/scripts/seed_hr_demo.py` (w CI krok „Zasiej zespół
 * HR” w `e2e.yml`, z tym samym jednorazowym hasłem co konta ról): przełożona,
 * pracownica z kartoteką i pulą urlopową oraz osoba w roli „Pracownik” bez
 * uprawnień Kadr i Płac. Dane są fikcyjne, adresy w `example.com`.
 *
 * Sesje przeglądarki logują się formularzem `/login`, jak człowiek: strona
 * zapisuje użytkownika w magazynie sesji i odtwarza cookie `nexus_access`,
 * a ekran docelowy po logowaniu (pracownik → „Mój czas”) wybiera aplikacja.
 */
import {
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { API_URL, expectStatus, jsonOf } from "./api";

export const HR_ACCOUNTS = {
  /**
   * Osoba na B2B z koordynatorką i pulą płatnych dni — zgłasza przerwę bez
   * akceptacji (etap 2, D5).
   */
  employee: process.env.E2E_HR_EMPLOYEE_EMAIL || "anna@hr-demo.example.com",
  /** Pracownik na umowie o pracę — wniosek urlopowy z akceptacją przełożonej. */
  uopEmployee: process.env.E2E_HR_UOP_EMPLOYEE_EMAIL || "dawid@hr-demo.example.com",
  /** Przełożona (UoP) i koordynatorka (B2B) obu osób. */
  manager: process.env.E2E_HR_MANAGER_EMAIL || "marta@hr-demo.example.com",
  /** Rola „Pracownik” bez uprawnień „Kadry” i „Płace”. */
  staff: process.env.E2E_HR_STAFF_EMAIL || "celina@hr-demo.example.com",
} as const;

const BASE_URL = process.env.E2E_BASE_URL || "https://nexus.dynaminds.pl";

/**
 * Pusty stan przeglądarki. Konteksty tworzone w teście dziedziczą `use`
 * projektu `ci-chromium`, w tym `storageState` administratora z setupu —
 * kontekst API niósłby jego cookie, a przeglądarka jego zapisaną sesję.
 */
const NO_SESSION = { cookies: [], origins: [] };

function password(): string {
  const value = process.env.E2E_USER_PASSWORD || "";
  expect(value, "E2E_USER_PASSWORD jest wymagane do scenariuszy HR").not.toBe("");
  return value;
}

/** Klient API z tokenem konta (wywołania przygotowania i sprzątania). */
export async function hrApi(email: string): Promise<APIRequestContext> {
  const anonymous = await playwrightRequest.newContext({
    baseURL: API_URL,
    storageState: NO_SESSION,
  });
  const response = await anonymous.post("/api/auth/login", {
    data: { email, password: password() },
  });
  const { access_token: token } = await jsonOf<{ access_token: string }>(
    response,
    200,
    `logowanie ${email}`
  );
  await anonymous.dispose();
  return playwrightRequest.newContext({
    baseURL: API_URL,
    storageState: NO_SESSION,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
}

export interface BrowserSession {
  context: BrowserContext;
  page: Page;
}

/**
 * Osobna przeglądarka zalogowana formularzem. Czeka, aż aplikacja wyprowadzi
 * z `/login` — dokąd, sprawdza scenariusz. `next` prowadzi prosto na ekran
 * scenariusza (bez renderu pulpitu, który niczego tu nie sprawdza).
 */
export async function loginInBrowser(
  browser: Browser,
  email: string,
  next?: string
): Promise<BrowserSession> {
  // `storageState: undefined` dziedziczyłoby sesję administratora, a `/login`
  // z zapisaną sesją nie pokazuje formularza.
  const context = await browser.newContext({ baseURL: BASE_URL, storageState: NO_SESSION });
  // Przewodnik onboardingowy pamięta zamknięcie w localStorage (jak w setupie).
  await context.addInitScript(() => {
    window.localStorage.setItem("onboarding_completed", "true");
  });
  const page = await context.newPage();
  await page.goto(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
  // Formularz hasła pojawia się po odpowiedzi `/api/auth/methods` — do tego
  // czasu ekran pokazuje tylko wejście przez Microsoft. Oba oczekiwania
  // ogranicza limit testu, nie własny: na serwerze deweloperskim przejście po
  // zalogowaniu czeka na kompilację strony docelowej (pomiar 17.10: do 34 s),
  // w CI stos stoi na zbudowanym froncie i mieści się w sekundach.
  const emailField = page.locator("#login-email");
  await emailField.waitFor({ state: "visible" });
  await emailField.fill(email);
  await page.locator("#login-password").fill(password());
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  return { context, page };
}

/** Dzisiejsza data w kalendarzu firmy (Europe/Warsaw), „YYYY-MM-DD”. */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Dzień kalendarza przesunięty o `days` (arytmetyka na samej dacie, bez strefy). */
export function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + days));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
}

/** „2026-11-05” → „05.11.2026” — tak termin jednego dnia pokazują tabele urlopów. */
export function displayDay(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

interface LeavePreview {
  working_days: string[];
  blocking_reason: string | null;
  auto_approved: boolean;
  /** `report` — zgłoszenie z B2B/zlecenia, wchodzi od razu (D5). */
  flow?: "request" | "report";
}

/**
 * Pierwszy wolny dzień roboczy co najmniej `fromOffset` dni od dziś (Warszawa).
 * O tym, czy dzień jest roboczy (weekendy, święta) i czy nie nachodzi na inny
 * wniosek, rozstrzyga podgląd serwera — ten sam, który liczy okno wniosku.
 */
export async function pickFreeLeaveDay(api: APIRequestContext, fromOffset: number): Promise<string> {
  const today = warsawToday();
  for (let offset = fromOffset; offset < fromOffset + 60; offset += 1) {
    const day = addDays(today, offset);
    const preview = await jsonOf<LeavePreview>(
      await api.post("/api/hr/leave/preview", {
        data: {
          leave_type: "vacation",
          start_date: day,
          end_date: day,
          half_day: null,
          substitute_user_id: null,
        },
      }),
      200,
      "POST /api/hr/leave/preview"
    );
    if (
      preview.working_days.length === 1 &&
      preview.blocking_reason === null &&
      (!preview.auto_approved || preview.flow === "report")
    ) {
      return day;
    }
  }
  throw new Error(`Brak wolnego dnia roboczego w 60 dniach od ${addDays(today, fromOffset)}`);
}

interface MyLeaveRow {
  id: string;
  note: string | null;
  can_cancel: boolean;
}

/**
 * Anuluje wnioski z poprzednich biegów (rozpoznane po znaczniku w notatce),
 * które jeszcze można anulować. Cudzych wniosków nie dotyka.
 */
export async function cancelLeaveWithMarker(api: APIRequestContext, marker: string): Promise<number> {
  const mine = await jsonOf<{ items: MyLeaveRow[] }>(
    await api.get("/api/hr/leave/my-requests"),
    200,
    "GET /api/hr/leave/my-requests"
  );
  let cancelled = 0;
  for (const row of mine.items) {
    if (!row.can_cancel || !row.note?.includes(marker)) continue;
    await expectStatus(
      await api.post(`/api/hr/leave/requests/${row.id}/cancel`),
      200,
      "anulowanie wniosku z testu"
    );
    cancelled += 1;
  }
  return cancelled;
}
