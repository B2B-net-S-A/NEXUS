/**
 * Trzy sekcje przepięte z endpointów legacy na `/api/insights/*` (decyzja D7).
 *
 * Zakładki `/insights` są otwarte dla każdej zalogowanej roli, ale te trzy
 * sekcje wołały wciąż wąskie powierzchnie i dla części ról kończyły się 403:
 *
 *   ActivityHeatmap       → /api/activities/leaderboard   (capability)
 *   InviteLinksSection    → /api/reports/invite-links      (4 role)
 *   HiringManagersSection → /api/reports/hiring-managers   (3 role)
 *
 * Reguły pod ochroną — każda raz już wyszła na produkcji:
 *
 * 1. **Awaria ≠ pustka.** 403 i 500 muszą renderować się jako awaria, nigdy
 *    jako „brak danych”. Dawna `HiringManagersSection` pisała przy błędzie
 *    „Błąd ładowania. Wymaga roli admin / head_of_recruitment.” — zdanie
 *    o uprawnieniach doklejone do KAŻDEGO błędu, także do 500.
 * 2. **`null` ≠ `0`.** Zerowy mianownik renderuje się jako „—”, nie „0%”.
 * 3. **Procentów nie przycinamy do 100.** 120% jest sygnałem, nie błędem widoku.
 * 4. **Koperta mówi, czego liczba NIE obejmuje** — pusty ranking aktywności,
 *    kumulatywny licznik aplikacji, migawkowe „Aktywni”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { InsightsHiringManagers } from "@/components/insights/sections/InsightsHiringManagers";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import { InsightsTeamActivity } from "@/components/insights/sections/InsightsTeamActivity";
import type { InsightsPeriodParams } from "@/lib/insights-api";

const PERIOD: InsightsPeriodParams = { period: "month", offset: 0 };

const WINDOW = {
  kind: "month" as const,
  start: "2026-08-01T00:00:00+02:00",
  end: "2026-09-01T00:00:00+02:00",
  timezone: "Europe/Warsaw",
};

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

/** Odpowiedzi po DOKŁADNYM URL-u — prefiksy `/insights/recruitment` się nakładają. */
function respond(map: Record<string, unknown>) {
  mocks.get.mockImplementation((url: string) => {
    if (!(url in map)) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    const value = map[url];
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

const TEAM_ACTIVITY = "/api/insights/recruitment/team-activity";
const INVITE_LINKS = "/api/insights/recruitment/invite-links";
const HIRING_MANAGERS = "/api/insights/clients/hiring-managers";

const COVERAGE_NOTE =
  "Liczone są wyłącznie czynności wykonane w NEXUSIE. " +
  "Ruch zaimportowany z Traffita nie zasila tej tabeli.";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InsightsTeamActivity", () => {
  it("czyta `/api/insights/*`, nie wąską powierzchnię legacy", async () => {
    respond({
      [TEAM_ACTIVITY]: {
        period: WINDOW,
        limit: 20,
        entries: [
          {
            rank: 1,
            user_id: 7,
            name: "Anna Kowalska",
            candidates_added: 12,
            screenings: 5,
            interviews: 3,
            placements: 1,
            calls: 9,
            total_actions: 30,
            share_pct: 100.0,
          },
        ],
        totals: { users: 1, actions: 30 },
        coverage: { source: "user_activities", note: COVERAGE_NOTE },
      },
    });

    renderSection(<InsightsTeamActivity period={PERIOD} />);

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    // Gdyby sekcja wołała `/api/activities/leaderboard`, rola `user` dostałaby
    // 403 na zakładce, która pod D7 jest dla niej otwarta.
    expect(mocks.get).toHaveBeenCalledWith(TEAM_ACTIVITY, expect.anything());
  });

  it("przy 403 mówi o uprawnieniach, a nie „nikt nic nie robił”", async () => {
    respond({ [TEAM_ACTIVITY]: httpError(403) });

    renderSection(<InsightsTeamActivity period={PERIOD} />);

    expect(
      await screen.findByText(/nie ma dostępu do sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nikt nie odnotował aktywności/),
    ).not.toBeInTheDocument();
  });

  it("przy 500 pokazuje awarię, nie pusty stan", async () => {
    respond({ [TEAM_ACTIVITY]: httpError(500) });

    renderSection(<InsightsTeamActivity period={PERIOD} />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nikt nie odnotował aktywności/),
    ).not.toBeInTheDocument();
  });

  it("pusty ranking mówi WPROST, czego ta tabela nie obejmuje", async () => {
    respond({
      [TEAM_ACTIVITY]: {
        period: WINDOW,
        limit: 20,
        entries: [],
        totals: { users: 0, actions: 0 },
        coverage: { source: "user_activities", note: COVERAGE_NOTE },
      },
    });

    renderSection(<InsightsTeamActivity period={PERIOD} />);

    expect(
      await screen.findByText(/Nikt nie odnotował aktywności/),
    ).toBeInTheDocument();
    // Bez tego zdania pustka czyta się jako „zespół nic nie robił”, a znaczy
    // „zespół nie pracował W NEXUSIE” (adopcja ~0,5%).
    expect(screen.getByText(/wykonane w NEXUSIE/)).toBeInTheDocument();
  });

  it("`share_pct === null` renderuje „—”, nie „0%”", async () => {
    respond({
      [TEAM_ACTIVITY]: {
        period: WINDOW,
        limit: 20,
        entries: [
          {
            rank: 1,
            user_id: 3,
            name: "Bez skali",
            candidates_added: 0,
            screenings: 0,
            interviews: 0,
            placements: 0,
            calls: 0,
            total_actions: 0,
            share_pct: null,
          },
        ],
        totals: { users: 1, actions: 0 },
        coverage: { source: "user_activities", note: COVERAGE_NOTE },
      },
    });

    renderSection(<InsightsTeamActivity period={PERIOD} />);

    const row = (await screen.findByText("Bez skali")).closest("tr")!;
    expect(row.textContent).toContain("—");
  });
});

describe("InsightsInviteLinks", () => {
  const CHANNELS = {
    period: WINDOW,
    channels: [
      {
        channel: "LinkedIn post 04/26",
        unlabelled: false,
        links_count: 2,
        applications: 5,
        conversion_pct: 250.0,
        last_used_at: "2026-08-20T10:00:00+02:00",
      },
      {
        channel: "Bez etykiety",
        unlabelled: true,
        links_count: 1,
        applications: 0,
        conversion_pct: 0.0,
        last_used_at: null,
      },
    ],
    totals: {
      links: 3,
      applications: 5,
      candidates: 4,
      conversion_pct: 166.7,
    },
    window_scope: {
      channels: "link_created_at",
      candidates: "candidate_created_at",
      applications_are_lifetime_per_link: true,
      note: "Okno filtruje LINKI po dacie utworzenia.",
    },
  };

  it("czyta `/api/insights/*` i NIE przycina procentu do 100", async () => {
    respond({ [INVITE_LINKS]: CHANNELS });

    renderSection(<InsightsInviteLinks period={PERIOD} />);

    expect(await screen.findByText("LinkedIn post 04/26")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(INVITE_LINKS, expect.anything());
    // 250% to sygnał (licznik aplikacji jest kumulatywny na linku), nie błąd
    // widoku — przycięcie do 100% schowałoby dokładnie tę informację.
    expect(screen.getByText("250.0%")).toBeInTheDocument();
    expect(screen.getByText("166.7%")).toBeInTheDocument();
  });

  it("odróżnia kubełek bez etykiety od kanału tak nazwanego", async () => {
    respond({ [INVITE_LINKS]: CHANNELS });

    renderSection(<InsightsInviteLinks period={PERIOD} />);

    const row = (await screen.findByText("Bez etykiety")).closest("tr")!;
    expect(row.textContent).toContain("linki bez etykiety");
    // Kanał z etykietą NIE może dostać tego dopisku.
    const labelled = screen.getByText("LinkedIn post 04/26").closest("tr")!;
    expect(labelled.textContent).not.toContain("linki bez etykiety");
  });

  it("mówi WPROST, że licznik aplikacji jest kumulatywny na linku", async () => {
    respond({ [INVITE_LINKS]: CHANNELS });

    renderSection(<InsightsInviteLinks period={PERIOD} />);

    expect(
      await screen.findByText(/Okno filtruje LINKI po dacie utworzenia/),
    ).toBeInTheDocument();
  });

  it("`conversion_pct === null` renderuje „—”, nie „0%”", async () => {
    respond({
      [INVITE_LINKS]: {
        ...CHANNELS,
        channels: [],
        totals: {
          links: 0,
          applications: 0,
          candidates: 0,
          conversion_pct: null,
        },
      },
    });

    renderSection(<InsightsInviteLinks period={PERIOD} />);

    // Kafel „Konwersja” bez mianownika: legacy podstawiał tu 0%, czyli
    // twierdził, że kanały miały zerową konwersję, gdy nie było ani jednego
    // linku.
    const tile = (await screen.findByText("Konwersja")).previousElementSibling;
    expect(tile?.textContent?.trim()).toBe("—");
    expect(
      screen.getByText(/Nie wygenerowano żadnych linków/),
    ).toBeInTheDocument();
  });

  it("przy 403 nie udaje pustej listy kanałów", async () => {
    respond({ [INVITE_LINKS]: httpError(403) });

    renderSection(<InsightsInviteLinks period={PERIOD} />);

    expect(
      await screen.findByText(/nie ma dostępu do sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie wygenerowano żadnych linków/),
    ).not.toBeInTheDocument();
  });
});

describe("InsightsHiringManagers", () => {
  const MANAGERS = {
    period: WINDOW,
    limit: 50,
    managers: [
      {
        contact_id: 11,
        contact_name: "Jan Nowak",
        position: "CTO",
        client_id: 5,
        client_name: "Bank Testowy",
        jobs_total: 4,
        jobs_open: 2,
        contracts_total: 3,
        contracts_active: 1,
        contract_rate_pct: 75.0,
      },
      {
        contact_id: 12,
        contact_name: "Ewa Bez Rekrutacji",
        position: null,
        client_id: 6,
        client_name: "Klient Drugi",
        jobs_total: 1,
        jobs_open: 0,
        contracts_total: 0,
        contracts_active: 0,
        contract_rate_pct: null,
      },
    ],
    totals: {
      managers: 2,
      jobs_total: 5,
      jobs_open: 2,
      contracts_total: 3,
      contracts_active: 1,
      open_rate_pct: 40.0,
    },
    truncated: 3,
    scope: {
      jobs: "job_created_at_in_window",
      contracts: "contracts_of_jobs_in_window",
      contracts_active_is_snapshot_now: true,
      note: "„Aktywni” to stan NA DZIŚ — statusy kontraktów nie mają historii.",
    },
  };

  it("czyta `/api/insights/*`, nie router legacy z trzema rolami", async () => {
    respond({ [HIRING_MANAGERS]: MANAGERS });

    renderSection(<InsightsHiringManagers period={PERIOD} />);

    expect(await screen.findByText("Jan Nowak")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(HIRING_MANAGERS, expect.anything());
  });

  it("`contract_rate_pct === null` renderuje „—”, nie „0%”", async () => {
    respond({ [HIRING_MANAGERS]: MANAGERS });

    renderSection(<InsightsHiringManagers period={PERIOD} />);

    const row = (await screen.findByText("Ewa Bez Rekrutacji")).closest("tr")!;
    expect(row.textContent).toContain("—");
  });

  it("mówi, ilu HM odsiał limit — przycięta lista czyta się jako komplet", async () => {
    respond({ [HIRING_MANAGERS]: MANAGERS });

    renderSection(<InsightsHiringManagers period={PERIOD} />);

    expect(await screen.findByText(/Pokazano 2 z 5/)).toBeInTheDocument();
  });

  it("mówi, że „Aktywni” to migawka na dziś, nie stan z końca okna", async () => {
    respond({ [HIRING_MANAGERS]: MANAGERS });

    renderSection(<InsightsHiringManagers period={PERIOD} />);

    expect(await screen.findByText(/stan NA DZIŚ/)).toBeInTheDocument();
  });

  it("przy 403 nie renderuje zachęty do uzupełnienia danych", async () => {
    respond({ [HIRING_MANAGERS]: httpError(403) });

    renderSection(<InsightsHiringManagers period={PERIOD} />);

    expect(
      await screen.findByText(/nie ma dostępu do sekcji/),
    ).toBeInTheDocument();
    // Pusty stan namawia do wypełnienia pola „Hiring manager”. Przy braku
    // uprawnień to rada, której odbiorca nie może wykonać, i sugeruje, że
    // danych nie ma — a są.
    expect(
      screen.queryByText(/nie ma przypisanego hiring managera/),
    ).not.toBeInTheDocument();
  });

  it("przy 500 pokazuje awarię zamiast dawnego zdania o rolach", async () => {
    respond({ [HIRING_MANAGERS]: httpError(500) });

    renderSection(<InsightsHiringManagers period={PERIOD} />);

    // Dawna sekcja pisała przy KAŻDYM błędzie „Wymaga roli admin /
    // head_of_recruitment.” — także przy 500, czyli myliła awarię serwera
    // z brakiem uprawnień.
    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Wymaga roli admin/)).not.toBeInTheDocument();
  });
});
