/**
 * „Zlecenie i Champion” → „Podgląd” (29.09.2026): zlecenie jako brief do
 * czytania. Tylko odczyt — każda zmiana idzie przez „Edytuj” w tej samej sekcji.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionBriefView } from "@/components/champion/ChampionBriefView";

const getMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: { ...actual.championApi, get: (...args: unknown[]) => getMock(...args) },
  };
});
// Własne zapytania (reguła CV, karta klienta, pytania z rozmów) — poza zakresem.
vi.mock("@/components/v2/cv-generator/ClientCvRuleBanner", () => ({
  useClientCvRule: () => ({ data: { is_active: true, cv_language: "pl" } }),
}));
vi.mock("@/components/client-playbook/ClientPlaybookCard", () => ({
  ClientPlaybookCard: () => <div data-testid="playbook-card" />,
}));
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: ({ readOnly }: { readOnly: boolean }) => (
    <div data-testid="request-history" data-read-only={String(readOnly)} />
  ),
}));
vi.mock("@/components/ChampionClientQuestionsPanel", () => ({
  ChampionClientQuestionsPanel: ({ canEdit }: { canEdit: boolean }) => (
    <div data-testid="client-questions" data-can-edit={String(canEdit)} />
  ),
}));

const PROFILE = {
  basics: {
    rate_value: 95,
    work_mode: "remote",
    start_date: "2026-11-03",
    contract_length: "do 30.06.2027",
    seniority_min_years: 5,
    language: "PL, EN B2",
  },
  stack: { must: [{ name: "Angular" }, { name: "TypeScript" }], nice: [], notes: "" },
  search: {
    keywords: "Angular Developer",
    target_companies: "",
    disqualifiers: [],
    notes: "",
    requirements: [["Angular"], ["NgRx", "SignalStore"]],
    exclude: [],
  },
  project: { about: "Budowa nowego systemu od podstaw.", responsibilities: "testy\ncode review" },
  screening_questions: [
    { id: "q1", question: "Opowiedz o projekcie w Angularze", ideal_answer: "Angular + TS", deal_breaker: "" },
    { id: "q2", question: "Jak testowałeś?", ideal_answer: "", deal_breaker: "brak testów" },
    { id: "q3", question: "Integracja z backendem?", ideal_answer: "", deal_breaker: "" },
    { id: "q4", question: "RxJS w praktyce?", ideal_answer: "", deal_breaker: "" },
  ],
  client: { selling_points: "Budowa systemu od zera", sectors: [], historical_questions: "" },
  insights: [{ id: "n1", topic: "ask_client", text: "Czy start dotyczy 2026?", source: "manual", audience: "team" }],
};

function renderBrief(onEditSection?: (anchor: string) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChampionBriefView
        jobId={5}
        job={{ title: "Starszy Programista Frontend", client_id: 9, client_name: "Klient A", deadline: null, description: "Opis od klienta" }}
        onEditSection={onEditSection}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  getMock.mockResolvedValue({ data: { job_id: 5, champion_profile: PROFILE } });
});

describe("ChampionBriefView", () => {
  it("czyta zlecenie jak brief: fakty, stack, wymagania do wyszukiwania, projekt, klient, do dopytania", async () => {
    renderBrief();
    expect(await screen.findByText("do 95,00 PLN/h")).toBeInTheDocument();
    expect(screen.getByText("zdalnie")).toBeInTheDocument();
    expect(screen.getByText("5+ lat")).toBeInTheDocument();
    expect(screen.getByText("PL (reguła klienta)")).toBeInTheDocument();
    expect(screen.getByText("Angular", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByText("Budowa nowego systemu od podstaw.")).toBeInTheDocument();
    expect(screen.getByText("Budowa systemu od zera")).toBeInTheDocument();
    expect(screen.getByText("Czy start dotyczy 2026?")).toBeInTheDocument();
    expect(screen.getByText("Oryginalny opis od klienta")).toBeInTheDocument();
    // Pytania klienta z rozmów — tylko do odczytu.
    expect(screen.getByTestId("client-questions")).toHaveAttribute("data-can-edit", "false");
  });

  it("pokazuje 3 pytania screeningowe, resztę po „Pokaż kolejne”", async () => {
    renderBrief();
    expect(await screen.findByText(/1\. Opowiedz o projekcie/)).toBeVisible();
    expect(screen.getByText("Pokaż 1 kolejne")).toBeInTheDocument();
    expect(screen.getByText("Odpada, gdy: brak testów")).toBeInTheDocument();
  });

  it("„Edytuj” przy sekcji prowadzi do tej samej sekcji edytora", async () => {
    const onEdit = vi.fn();
    renderBrief(onEdit);
    await userEvent.click(await screen.findByRole("button", { name: "Edytuj: Pytania screeningowe (4)" }));
    expect(onEdit).toHaveBeenCalledWith("champion-section-screening");
    await userEvent.click(screen.getByRole("button", { name: "Edytuj: Co zamówił klient" }));
    expect(onEdit).toHaveBeenCalledWith("champion-section-basics");
  });

  it("bez prawa edycji — brak przycisków „Edytuj”", async () => {
    renderBrief(undefined);
    await screen.findByText("do 95,00 PLN/h");
    expect(screen.queryByRole("button", { name: /^Edytuj:/ })).toBeNull();
  });

  it("awaria odczytu profilu to komunikat z „Ponów”, nie pusty brief", async () => {
    getMock.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 503 } }));
    renderBrief();
    expect(await screen.findByRole("button", { name: /Ponów|Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByTestId("champion-brief-view")).toBeNull();
  });
});

describe("ChampionBriefView — profil sprzed 09.2026 (pola z rekrutacji, M04-B02)", () => {
  it("pusty stack i budżet profilu biorą wartości z kolumn rekrutacji — jak edytor", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 5,
        champion_profile: { stack: { must: [], nice: [], notes: "" }, basics: {} },
        job_values: { must: "Java", nice: null, rate_value: 120, work_mode: "remote" },
        job_title: "Java Developer",
      },
    });
    renderBrief();
    expect(await screen.findByText("Java", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByText("do 120,00 PLN/h")).toBeInTheDocument();
    expect(screen.getByText("zdalnie")).toBeInTheDocument();
  });
});

describe("ChampionBriefView — wcześniejsze zapytania klienta", () => {
  it("są w Podglądzie dla każdej roli (do 29.09 zakładka „Historia” panelu), zapis wg uprawnień", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChampionBriefView
          jobId={5}
          job={{ title: "X", client_id: 9 }}
          requestHistory={{ readOnly: true }}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("request-history")).toHaveAttribute("data-read-only", "true");
  });
});
