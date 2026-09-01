/**
 * Power Calling + LinkedIn Performance — dwie sekcje, które WSKAZUJĄ LUDZI
 * PALCEM. Testy pilnują reguł, których złamanie jest defektem, nie kwestią
 * układu:
 *
 * 1. **Trzeci stan Power Callingu jest osobny i neutralny.** Wiersz bez
 *    mianownika dni roboczych (urlop, brak danych z COMPASSA) nie może stanąć
 *    obok „poniżej progu" ani dostać czerwonego znacznika.
 * 2. **`meets_target === null` to „nie wiemy", nie „nie spełnia".** Renderuje
 *    się „—”.
 * 3. **Mianownik jest widoczny.** Obok „2,6 / dzień" stoi „(13 wer. / 5 dni)”.
 * 4. **Procentów nie przycinamy do 100** — mimo że backend przycina własne
 *    `progress_pct`, UI liczy realizację sam i pokazuje 133%.
 * 5. **Brak mianownika jest NAZWANY.** `workdays_source: "unavailable"` mówi,
 *    że dane idą z COMPASSA i ich nie ma — zamiast kolumny samych „—”.
 * 6. **Zerowy mianownik ≠ zero.** LinkedIn: 0 wysłanych wiadomości daje „—”,
 *    a nie „0.0%”, mimo że backend przysyła w tym polu `0.0`.
 * 7. **Kafle są sumą wierszy pod nimi**, nie kopią `totals` z odpowiedzi.
 * 8. **Awaria ≠ pustka.** 403 i 500 renderują się jako awaria.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { InsightsLinkedIn } from "@/components/insights/sections/InsightsLinkedIn";
import { InsightsPowerCalling } from "@/components/insights/sections/InsightsPowerCalling";

const POWER_CALLING_URL = "/api/reports/power-calling";
const LINKEDIN_URL = "/api/linkedin-metrics/summary";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function respond(url: string, value: unknown) {
  mocks.get.mockImplementation((requested: string) => {
    if (requested !== url) {
      return Promise.reject(
        new Error(`Nieoczekiwany URL w teście: ${requested}`),
      );
    }
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

// ── Fixtures ───────────────────────────────────────────────────────────

const BELOW = {
  user_id: 1,
  name: "Anna Below",
  role: "recruiter",
  primary_category: null,
  verifications_week: 13,
  per_day: 2.6,
  workdays: 5,
  workdays_source: "compass" as const,
  meets_target: false,
  progress_pct: 87,
  weekly_target: 15,
  reason: null,
};

const MET = {
  ...BELOW,
  user_id: 2,
  name: "Bartek Met",
  verifications_week: 20,
  per_day: 4,
  meets_target: true,
  // Backend przycina to pole do 100 — UI ma je zignorować i policzyć 133%.
  progress_pct: 100,
};

/**
 * Wiersz z `meets_target: null` wstawiony do `below_target`. Kontrakt backendu
 * na to nie pozwala, ale to jest dokładnie ta pomyłka, przed którą chronimy:
 * „nie wiemy" nie może wydrukować się jako „nie spełnia".
 */
const NULL_VERDICT = {
  ...BELOW,
  user_id: 3,
  name: "Cezary Niewiadomo",
  per_day: null,
  workdays: null,
  meets_target: null,
  progress_pct: null,
};

const ON_LEAVE = {
  ...BELOW,
  user_id: 4,
  name: "Dorota Urlop",
  verifications_week: 0,
  per_day: null,
  workdays: 0,
  meets_target: null,
  progress_pct: null,
  reason: "zero_workdays",
};

const NO_WORKDAY_DATA = {
  ...BELOW,
  user_id: 5,
  name: "Ewa Brakdanych",
  verifications_week: 7,
  per_day: null,
  workdays: null,
  workdays_source: "unavailable" as const,
  meets_target: null,
  progress_pct: null,
  reason: "no_workday_data",
};

const POWER_CALLING = {
  week_label: "Tydz. 33/2026",
  iso_week: 33,
  iso_year: 2026,
  date_from: "2026-08-10",
  date_to: "2026-08-16",
  target_per_day: 3,
  weekly_target: 15,
  workdays: null,
  workdays_source: "compass" as const,
  requirement_text:
    "Wymóg: min. 3 weryfikacji na dzień roboczy (15/tydz. przy pełnym tygodniu).",
  entries: [BELOW, MET, NULL_VERDICT, ON_LEAVE, NO_WORKDAY_DATA],
  below_target: [BELOW, NULL_VERDICT],
  met_target: [MET],
  not_assessable: [ON_LEAVE, NO_WORKDAY_DATA],
  meets_target_count: 1,
  not_assessable_count: 2,
  total_count: 5,
};

const LINKEDIN = {
  period: "month",
  date_from: "2026-08-01",
  date_to: "2026-08-31",
  per_user: [
    {
      user_id: 1,
      name: "Anna Sourcer",
      role: "sourcer",
      cv_added: 30,
      messages_sent: 200,
      responses_received: 25,
      response_rate: 12.5,
      cv_response_rate: 83.3,
      days_reported: 20,
    },
    {
      // Zero wysłanych wiadomości. Backend liczy tu `_safe_pct(0, 0) == 0.0`,
      // czyli „0% odpowiedzi" — werdykt zamiast braku danych.
      user_id: 2,
      name: "Bartek Jednodniowy",
      role: "tac",
      cv_added: 6,
      messages_sent: 0,
      responses_received: 0,
      response_rate: 0.0,
      cv_response_rate: 0.0,
      days_reported: 1,
    },
  ],
  // Celowo NIEZGODNE z sumą wierszy — kafle mają liczyć z `per_user`.
  totals: {
    cv_added: 999,
    messages_sent: 999,
    responses_received: 999,
    response_rate: 99.9,
    cv_response_rate: 99.9,
    active_users: 2,
  },
};

beforeEach(() => {
  mocks.get.mockReset();
});

// ── Power Calling ──────────────────────────────────────────────────────

describe("InsightsPowerCalling", () => {
  it("pokazuje mianownik obok stawki dziennej", async () => {
    respond(POWER_CALLING_URL, POWER_CALLING);
    renderSection(<InsightsPowerCalling />);

    const row = (await screen.findByText("Anna Below")).closest("tr");
    expect(row).not.toBeNull();
    // Separator dziesiętny zależy od ICU — istotne jest, że rachunek jest widoczny.
    expect(
      within(row as HTMLElement).getByText(/2[.,]6 \/ dzień/),
    ).toBeTruthy();
    expect(
      within(row as HTMLElement).getByText(/13 wer\. \/ 5 dni/),
    ).toBeTruthy();
  });

  it("NIE przycina realizacji progu do 100%", async () => {
    respond(POWER_CALLING_URL, POWER_CALLING);
    renderSection(<InsightsPowerCalling />);

    const row = (await screen.findByText("Bartek Met")).closest("tr");
    // 4 weryfikacje/dzień przy progu 3 = 133%, mimo `progress_pct: 100`.
    expect(within(row as HTMLElement).getByText("133%")).toBeTruthy();
  });

  it("renderuje `meets_target: null` jako „—”, nie jako „poniżej progu”", async () => {
    respond(POWER_CALLING_URL, POWER_CALLING);
    renderSection(<InsightsPowerCalling />);

    const row = (await screen.findByText("Cezary Niewiadomo")).closest("tr");
    expect(within(row as HTMLElement).queryByText("Poniżej progu")).toBeNull();
    expect(within(row as HTMLElement).queryByText("Spełnia próg")).toBeNull();
    expect(within(row as HTMLElement).getAllByText("—").length).toBeGreaterThan(
      0,
    );
  });

  it("nieocenianych trzyma osobno, neutralnie i z powodem po polsku", async () => {
    respond(POWER_CALLING_URL, POWER_CALLING);
    renderSection(<InsightsPowerCalling />);

    expect(await screen.findByText("Nieoceniani w tym tygodniu")).toBeTruthy();

    // Urlop: zero dni roboczych. Nie wolno tego renderować jako słabego wyniku.
    const leave = (await screen.findByText("Dorota Urlop")).closest("li");
    expect(leave).not.toBeNull();
    expect((leave as HTMLElement).textContent).toMatch(/urlop/i);
    expect(
      within(leave as HTMLElement).queryByText("Poniżej progu"),
    ).toBeNull();
    // Żadnej czerwieni — wiersz jest w liście neutralnej, nie w tabeli werdyktów.
    expect((leave as HTMLElement).closest("table")).toBeNull();

    const missing = (await screen.findByText("Ewa Brakdanych")).closest("li");
    expect((missing as HTMLElement).textContent).toMatch(
      /Brak danych o nieobecnościach/i,
    );
    // Liczba bezwzględna zostaje — jest prawdziwa, brakuje tylko mianownika.
    expect((missing as HTMLElement).textContent).toMatch(/7 wer\./);
  });

  it("nazywa brak mianownika, gdy COMPASS nie dowiózł danych", async () => {
    respond(POWER_CALLING_URL, {
      ...POWER_CALLING,
      workdays_source: "unavailable",
      below_target: [],
      met_target: [],
      not_assessable: [ON_LEAVE, NO_WORKDAY_DATA],
      meets_target_count: null,
    });
    renderSection(<InsightsPowerCalling />);

    expect(await screen.findByText(/COMPASSA/)).toBeTruthy();
  });

  it("pusty tydzień to komunikat o zerze weryfikacji, nie awaria", async () => {
    respond(POWER_CALLING_URL, {
      ...POWER_CALLING,
      entries: [],
      below_target: [],
      met_target: [],
      not_assessable: [],
      meets_target_count: 0,
      not_assessable_count: 0,
      total_count: 0,
    });
    renderSection(<InsightsPowerCalling />);

    expect(await screen.findByText(/nie odnotował weryfikacji/i)).toBeTruthy();
    expect(screen.queryByText(/Nie udało się pobrać/)).toBeNull();
  });

  it("403 i 500 renderują się jako awaria, nie jako brak danych", async () => {
    respond(POWER_CALLING_URL, httpError(403));
    const forbidden = renderSection(<InsightsPowerCalling />);
    expect(await screen.findByText(/Twoja rola nie ma dostępu/)).toBeTruthy();
    expect(screen.queryByText(/nie odnotował weryfikacji/i)).toBeNull();
    forbidden.unmount();

    respond(POWER_CALLING_URL, httpError(500));
    renderSection(<InsightsPowerCalling />);
    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeTruthy();
  });
});

// ── LinkedIn Performance ───────────────────────────────────────────────

describe("InsightsLinkedIn", () => {
  it("zerowy mianownik daje „—”, a nie 0.0% z backendu", async () => {
    respond(LINKEDIN_URL, LINKEDIN);
    renderSection(<InsightsLinkedIn />);

    const row = (await screen.findByText("Bartek Jednodniowy")).closest("tr");
    expect(within(row as HTMLElement).getByText("—")).toBeTruthy();
    // `response_rate: 0.0` z odpowiedzi nie może pojawić się nigdzie na ekranie.
    expect(screen.queryByText("0.0%")).toBeNull();
  });

  it("kafle są sumą wierszy, nie kopią `totals`", async () => {
    respond(LINKEDIN_URL, LINKEDIN);
    renderSection(<InsightsLinkedIn />);

    // 30 + 6 = 36 CV, a nie 999 z `totals`.
    expect(await screen.findByText("36")).toBeTruthy();
    expect(screen.queryByText("999")).toBeNull();
    // 25 odpowiedzi / 200 wiadomości = 12.5%. Kafel zawężamy do jego własnego
    // pudełka, bo ta sama liczba stoi też w wierszu Anny — i to jest cel:
    // kafel MA być sumą tego, co widać pod nim.
    const rateTile = screen
      .getByText(/25 odp\. \/ 200 wiad\./)
      .closest("div.rounded-xl");
    expect(rateTile).not.toBeNull();
    expect(within(rateTile as HTMLElement).getByText("12.5%")).toBeTruthy();
    expect(screen.queryByText("99.9%")).toBeNull();
  });

  it("pokazuje dni raportowane obok ilorazów i nie nazywa ich % celu", async () => {
    respond(LINKEDIN_URL, LINKEDIN);
    renderSection(<InsightsLinkedIn />);

    const row = (await screen.findByText("Anna Sourcer")).closest("tr");
    // 30 CV / 20 dni = 1,5 — mianownik stoi w tym samym wierszu.
    expect(within(row as HTMLElement).getByText(/^1[.,]5$/)).toBeTruthy();
    expect(within(row as HTMLElement).getByText("20")).toBeTruthy();

    expect(screen.getByText("CV/dzień")).toBeTruthy();
    expect(screen.queryByText(/% (celu|targetu)/i)).toBeNull();
    expect(screen.getByText(/DNI ZARAPORTOWANYCH/)).toBeTruthy();
  });

  it("mówi wprost, że okno jest bieżące i nie słucha wyboru okresu", async () => {
    respond(LINKEDIN_URL, LINKEDIN);
    renderSection(<InsightsLinkedIn />);

    expect(
      await screen.findByText(/nie reaguje na przesunięcie wybrane u góry/i),
    ).toBeTruthy();
  });

  it("pustka tłumaczy, że raport jest RĘCZNY", async () => {
    respond(LINKEDIN_URL, { ...LINKEDIN, per_user: [] });
    renderSection(<InsightsLinkedIn />);

    expect(
      await screen.findByText(/nie zaraportował aktywności/i),
    ).toBeTruthy();
    expect(screen.getByText(/ręcznego raportu/i)).toBeTruthy();
  });

  it("500 renderuje się jako awaria, nie jako brak aktywności", async () => {
    respond(LINKEDIN_URL, httpError(500));
    renderSection(<InsightsLinkedIn />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeTruthy();
    expect(screen.queryByText(/nie zaraportował aktywności/i)).toBeNull();
  });
});
