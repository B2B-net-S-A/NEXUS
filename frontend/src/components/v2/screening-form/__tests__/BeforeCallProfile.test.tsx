/**
 * „Co już wiemy” nad formularzem screeningu (P2, 14.10.2026; wcześniej profil
 * przed telefonem, 12.10.2026): ostatnio podana stawka, dostępność, tryb pracy,
 * ostatnia zakończona rekrutacja z wynikiem i wcześniejsze notatki z „Pokaż”.
 * Blok rozwinięty, dopóki formularz jest pusty; po pierwszym zapisie zwinięty
 * do jednej linii skrótu. Od 09.10.2026 głowa rozwiniętego panelu nie pokazuje
 * faktów w „Nowych”, więc przed telefonem rekruter nie widział ich nigdzie.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), candidate: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn() },
  candidatesApi: { get: (...a: unknown[]) => mocks.candidate(...a) },
  extractErrorMsg: () => "Błąd",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { id: number; role: string } }) => unknown) =>
    sel({ user: { id: 5, role: "recruiter" } }),
  hasRole: () => false,
}));

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";

import { BeforeCallProfile } from "../BeforeCallProfile";

const JOB = 42;
const CANDIDATE = 6;
const DAY = 24 * 60 * 60 * 1000;
const daysAgo = (days: number) => new Date(Date.now() - days * DAY).toISOString();

const ITEM = {
  id: 11,
  candidate_id: CANDIDATE,
  stage: "new",
  name: "Anna",
  lastname: "Przykładowa",
  entry_source: "added_manual",
  candidate_rate_from_hourly: 120,
  can_take: true,
  claim_user_id: null,
} as unknown as KanbanItem;

const QUICK_VIEW = {
  candidate: { city: "Warszawa" },
  current_position: { title: "Analityk", started_at: "2023-03-01" },
  current_recruitments: [],
  recent_notes: [],
  contact_attempts: 0,
  cv_highlights: { years_experience: 8 },
};

const DETAIL = {
  availability_date: null,
  availability_status: "open_to_offers",
  notice_period: 1,
  notice_period_unit: "months",
  max_onsite_days_per_week: 2,
};

const RATES = { latest_amount: 130, latest_at: "2025-03-14T15:20:00Z" };

const note = (id: number, extra: Record<string, unknown>) => ({
  id,
  content: `Notatka ${id}`,
  created_at: daysAgo(30),
  group: "talks",
  job_id: 7,
  ...extra,
});

const HISTORY = {
  jobs: [
    {
      job_id: 7,
      job_title: "Analityk systemowy",
      job_status: "published",
      client_name: "Bank Przykładowy",
      latest_stage: "rejected",
      rejection_reason: "Klient — za mało integracji",
      last_seen: "2025-04-02T09:00:00Z",
      stages: [],
    },
    // Rekrutacja w toku nie jest „ostatnią zakończoną”.
    { job_id: 8, job_title: "Tester", job_status: "published", latest_stage: "screening", last_seen: daysAgo(2), stages: [] },
    // Bieżąca rekrutacja też nie.
    { job_id: JOB, job_title: "Ta rekrutacja", job_status: "published", latest_stage: "new", last_seen: daysAgo(0), stages: [] },
  ],
};

interface Routes {
  notes?: unknown;
  history?: unknown;
  rates?: unknown;
  detail?: unknown;
}

function respond({ notes = { items: [] }, history = { jobs: [] }, rates = RATES, detail = DETAIL }: Routes = {}) {
  const answer = (value: unknown) => (value instanceof Error ? Promise.reject(value) : Promise.resolve({ data: value }));
  mocks.get.mockImplementation((url: string) => {
    if (url.includes("/quick-view")) return answer(QUICK_VIEW);
    if (url.startsWith("/api/notes")) return answer(notes);
    if (url.includes("/history")) return answer(history);
    if (url.includes("/rate-overview")) return answer(rates);
    return answer({});
  });
  mocks.candidate.mockImplementation(() => answer(detail));
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  const rerenderWith = (next: ReactNode) =>
    view.rerender(<QueryClientProvider client={client}>{next}</QueryClientProvider>);
  return { ...view, rerenderWith };
}

const renderProfile = (onOpenHistory?: () => void) =>
  wrap(<BeforeCallProfile item={ITEM} jobId={JOB} readOnly={false} onOpenHistory={onOpenHistory} />);

beforeEach(() => {
  mocks.get.mockReset();
  mocks.candidate.mockReset();
});

describe("BeforeCallProfile — zwijany blok nad formularzem (P2, 14.10.2026)", () => {
  const toggle = () => screen.getByRole("button", { name: /Co już wiemy/ });

  it("pusty formularz: blok rozwinięty, w głowie „Nie odebrał”, bez „Zacznij screening” i „Biorę”", async () => {
    respond();
    renderProfile();
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByTestId("before-call-conditions")).toBeVisible();
    expect(screen.getByRole("button", { name: /Nie odebrał/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Zacznij screening/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Biorę/ })).toBeNull();
    expect(screen.queryByTestId("before-call-summary")).toBeNull();
  });

  it("po zapisie formularza zwija się do jednej linii skrótu; klik rozwija", async () => {
    respond({ history: HISTORY });
    const view = wrap(<BeforeCallProfile item={ITEM} jobId={JOB} readOnly={false} defaultOpen />);
    await screen.findByText("130 zł/h");
    view.rerenderWith(<BeforeCallProfile item={ITEM} jobId={JOB} readOnly={false} defaultOpen={false} />);

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("before-call-conditions")).not.toBeVisible();
    const summary = screen.getByTestId("before-call-summary");
    expect(summary).toHaveTextContent("Analityk · 130 zł/h · Otwarty na oferty · wypowiedzenie 1 mies.");
    await waitFor(() => expect(summary).toHaveTextContent("wcześniej: Odrzucony"));

    await userEvent.setup().click(toggle());
    expect(screen.getByTestId("before-call-conditions")).toBeVisible();
    expect(screen.queryByTestId("before-call-summary")).toBeNull();
  });

  it("zwinięty blok mówi o awarii odczytu zamiast udawać komplet", async () => {
    respond({ detail: new Error("500") });
    wrap(<BeforeCallProfile item={ITEM} jobId={JOB} readOnly={false} defaultOpen={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Część danych się nie wczytała — rozwiń, żeby ponowić.");
  });

  it("tylko do odczytu: bez „Nie odebrał”", () => {
    respond();
    wrap(<BeforeCallProfile item={ITEM} jobId={JOB} readOnly />);
    expect(screen.queryByRole("button", { name: /Nie odebrał/ })).toBeNull();
  });
});

describe("BeforeCallProfile — co już wiemy przed telefonem", () => {
  it("„W bazie od” w bloku „Kandydat”: data, wiek i skąd (13.10.2026)", async () => {
    respond({
      detail: {
        ...DETAIL,
        added_to_base_at: "2019-05-11T22:00:00Z",
        added_to_base_exact: true,
        added_via: "Traffit · Aktywny Search",
        created_by_user: null,
      },
    });
    renderProfile();

    const facts = await screen.findByTestId("before-call-facts");
    expect(within(facts).getByText("W bazie od")).toBeInTheDocument();
    expect(
      await within(facts).findByText(/^12\.05\.2019 · \d+ lat temu · Traffit · Aktywny Search$/),
    ).toBeInTheDocument();
  });

  it("„W bazie od” z importu bez daty u źródła mówi „przed …”", async () => {
    respond({
      detail: { ...DETAIL, added_to_base_at: "2026-04-16T10:00:00Z", added_to_base_exact: false },
    });
    renderProfile();

    const facts = await screen.findByTestId("before-call-facts");
    expect(await within(facts).findByText("przed 16.04.2026 · dokładnej daty nie znamy")).toBeInTheDocument();
  });

  it("pokazuje ostatnio podaną stawkę z datą, dostępność i tryb pracy z profilu", async () => {
    respond();
    renderProfile();

    const conditions = await screen.findByTestId("before-call-conditions");
    expect(await within(conditions).findByText("130 zł/h")).toBeInTheDocument();
    // Najniższa stawka z karty („Stawka od”) stoi obok, gdy różni się od ostatniej.
    expect(within(conditions).getByText("ostatnio podana 03.2025 · najniższa 120 zł/h")).toBeInTheDocument();
    expect(await within(conditions).findByText("Otwarty na oferty · wypowiedzenie 1 mies.")).toBeInTheDocument();
    expect(within(conditions).getByText("Do 2 dni w biurze")).toBeInTheDocument();
    expect(mocks.candidate).toHaveBeenCalledWith(CANDIDATE);
  });

  it("bez dostępu do historii stawek zostaje „Stawka od” z karty — po cichu, bo to kwestia roli", async () => {
    respond({ rates: new Error("403") });
    renderProfile();

    const conditions = await screen.findByTestId("before-call-conditions");
    expect(within(conditions).getByText("od 120 zł/h")).toBeInTheDocument();
    expect(await within(conditions).findByText("Do 2 dni w biurze")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("awaria odczytu profilu: kreski dostają komunikat z „Ponów”, nie udają braku danych", async () => {
    respond({ detail: new Error("500") });
    renderProfile();

    const conditions = await screen.findByTestId("before-call-conditions");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się wczytać warunków z profilu.");
    // Dostępność i tryb pracy — kreska, nie znikający wiersz.
    expect(within(conditions).getAllByText("—")).toHaveLength(2);
    const calls = mocks.candidate.mock.calls.length;
    fireEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(mocks.candidate.mock.calls.length).toBe(calls + 1));
  });

  it("„Wcześniej u nas”: ostatnia ZAKOŃCZONA rekrutacja z wynikiem i wcześniejsze notatki z „Pokaż”", async () => {
    const onOpenHistory = vi.fn();
    respond({
      notes: {
        items: [
          note(1, { job_id: JOB }),
          note(2, { created_at: daysAgo(20) }),
          note(3, { created_at: daysAgo(400) }),
          note(4, { is_system: true, group: "automat" }),
        ],
      },
      history: HISTORY,
    });
    renderProfile(onOpenHistory);

    const earlier = await screen.findByRole("region", { name: "Wcześniej u nas" });
    expect(await within(earlier).findByText("Analityk systemowy")).toBeInTheDocument();
    expect(within(earlier).getByText("Odrzucony")).toBeInTheDocument();
    expect(within(earlier).getByText("Klient — za mało integracji · 04.2025")).toBeInTheDocument();
    expect(within(earlier).queryByText("Tester")).toBeNull();
    expect(within(earlier).queryByText("Ta rekrutacja")).toBeNull();
    // Notatki ludzi spoza tej rekrutacji: dwie (notatka tej rekrutacji i wpis automatu się nie liczą).
    expect(within(earlier).getByText(/2 notatki z wcześniejszych rozmów/)).toBeInTheDocument();
    // Świeża notatka — bez uwagi o wieku danych.
    expect(within(earlier).queryByRole("note")).toBeNull();

    fireEvent.click(within(earlier).getByRole("button", { name: "Pokaż" }));
    expect(onOpenHistory).toHaveBeenCalledTimes(1);
  });

  it("stare notatki dostają uwagę, żeby potwierdzić warunki w rozmowie", async () => {
    respond({ notes: { items: [note(2, { created_at: daysAgo(580) })] } });
    renderProfile(vi.fn());

    const earlier = await screen.findByRole("region", { name: "Wcześniej u nas" });
    expect(within(earlier).getByRole("note")).toHaveTextContent(
      "Ostatnia wcześniejsza notatka sprzed 19 mies. — potwierdź warunki w rozmowie.",
    );
  });

  it("osoba bez historii nie dostaje pustej sekcji „Wcześniej u nas”", async () => {
    respond({ notes: { items: [note(1, { job_id: JOB })] }, history: { jobs: [HISTORY.jobs[1], HISTORY.jobs[2]] } });
    renderProfile(vi.fn());

    await screen.findByTestId("before-call-conditions");
    await waitFor(() =>
      expect(mocks.get.mock.calls.some(([url]) => String(url).includes("/history"))).toBe(true),
    );
    expect(screen.queryByRole("region", { name: "Wcześniej u nas" })).toBeNull();
  });

  it("awaria odczytu notatek nie wygląda jak osoba bez historii", async () => {
    respond({ notes: new Error("500") });
    renderProfile(vi.fn());

    const earlier = await screen.findByRole("region", { name: "Wcześniej u nas" });
    expect(within(earlier).getByRole("alert")).toHaveTextContent("Nie udało się sprawdzić wcześniejszych notatek.");
    expect(within(earlier).queryByRole("button", { name: "Pokaż" })).toBeNull();
  });

  it("awaria historii rekrutacji nie zabiera liczby wcześniejszych notatek", async () => {
    respond({ notes: { items: [note(2, {})] }, history: new Error("500") });
    renderProfile(vi.fn());

    const earlier = await screen.findByRole("region", { name: "Wcześniej u nas" });
    expect(within(earlier).getByText(/1 notatka z wcześniejszych rozmów/)).toBeInTheDocument();
    expect(within(earlier).queryByText(/Odrzucony|zamknięta/)).toBeNull();
  });
});
