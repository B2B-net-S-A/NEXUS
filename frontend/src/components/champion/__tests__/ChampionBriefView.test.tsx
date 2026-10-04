/**
 * „Profil Championa” → „Brief” (04.10.2026): to, co rekruter musi wiedzieć
 * przed telefonem. Tylko odczyt — „Edytuj” otwiera szufladę bloku.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionBriefView } from "@/components/champion/ChampionBriefView";
import type { ChampionBlock } from "@/lib/champion-blocks";

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
  RequestHistorySection: ({ readOnly, narrow }: { readOnly: boolean; narrow?: boolean }) => (
    <div data-testid="request-history" data-read-only={String(readOnly)} data-narrow={String(!!narrow)} />
  ),
}));
vi.mock("@/components/champion/plain/PlainBriefBlock", () => ({
  PlainBriefBlock: ({ parts }: { parts?: string }) => (
    <div data-testid="plain-brief-block" data-parts={parts ?? "all"} />
  ),
}));
const plainBriefMock = vi.fn();
vi.mock("@/lib/api/plainKnowledge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/plainKnowledge")>();
  return { ...actual, usePlainBrief: () => plainBriefMock() };
});
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

function renderBrief(onEditBlock?: (block: ChampionBlock) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChampionBriefView
        jobId={5}
        job={{
          title: "Starszy Programista Frontend",
          client_id: 9,
          client_name: "Klient A",
          deadline: null,
          description: "Opis od klienta",
          hiring_manager_name: "Adam Brzoza",
          delivery_lead_user: { name: "Ewa Lis" },
          recruiters: [
            { user_id: 1, name: "Jan Kowal", via: "owner", proposed: false, assigned_by_name: null },
          ],
        }}
        onEditBlock={onEditBlock}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  plainBriefMock.mockReset();
  plainBriefMock.mockReturnValue({ data: undefined });
  getMock.mockReset();
  getMock.mockResolvedValue({ data: { job_id: 5, champion_profile: PROFILE } });
});

describe("ChampionBriefView", () => {
  it("krytyczne: gwiazdka przy pozycji MUST i linia z decyzją albo podpowiedzią", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 5,
        champion_profile: PROFILE,
        critical_resolution: {
          stored: null,
          decided: false,
          effective: ["Angular"],
          source: "suggested",
          suggested: ["Angular"],
        },
      },
    });
    renderBrief();
    expect(await screen.findByTestId("brief-critical")).toHaveTextContent(
      "Nie zdecydowano (podpowiedź: Angular)",
    );
    expect(screen.getByText("— krytyczna").closest("li")).toHaveTextContent("Angular");
  });

  it("krytyczne: „Brak krytycznych” bez gwiazdek", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 5,
        champion_profile: PROFILE,
        critical_resolution: { stored: [], decided: true, effective: [], source: "dl", suggested: ["Angular"] },
      },
    });
    renderBrief();
    expect(await screen.findByTestId("brief-critical")).toHaveTextContent("Brak krytycznych");
    expect(screen.queryByText("— krytyczna")).toBeNull();
  });

  it("czyta zlecenie jak brief: warunki, stack, wymagania, projekt, co powiedzieć, kto prowadzi, do dopytania", async () => {
    renderBrief();
    expect(await screen.findByText("do 95,00 PLN/h")).toBeInTheDocument();
    expect(screen.getByText("zdalnie")).toBeInTheDocument();
    expect(screen.getByText("5+ lat")).toBeInTheDocument();
    expect(screen.getByText("PL (reguła klienta)")).toBeInTheDocument();
    expect(screen.getByText("Angular", { selector: "li > span" })).toBeInTheDocument();
    expect(screen.getByText("Budowa nowego systemu od podstaw.")).toBeInTheDocument();
    expect(screen.getByText("Budowa systemu od zera")).toBeInTheDocument();
    expect(screen.getByText("Czy start dotyczy 2026?")).toBeInTheDocument();
    expect(screen.getByText("Oryginalny opis od klienta")).toBeInTheDocument();
    expect(screen.getByText("Wymagania do wyszukiwania w bazie (2)")).toBeInTheDocument();
    // Kto prowadzi — z rekrutacji, bez osobnego zapytania.
    const team = screen.getByTestId("brief-team");
    expect(team).toHaveTextContent("Ewa Lis");
    expect(team).toHaveTextContent("Jan Kowal");
    expect(team).toHaveTextContent("Adam Brzoza");
    // „Jednym zdaniem” — skrót z „Po ludzku”; słowniczek i klient są w innych zakładkach.
    expect(screen.getByTestId("plain-brief-block")).toHaveAttribute("data-parts", "summary");
    expect(screen.queryByTestId("client-questions")).toBeNull();
    expect(screen.queryByTestId("playbook-card")).toBeNull();
    expect(screen.queryByTestId("request-history")).toBeNull();
  });

  it("technologia ze słowniczka dostaje dymek „po ludzku”, bez hasła — zwykły chip", async () => {
    plainBriefMock.mockReturnValue({
      data: {
        glossary: [
          {
            term_key: "angular",
            display_name: "Angular",
            level: "must",
            level_label: "wymagane",
            status: "ready",
            summary: "Narzędzie do budowania ekranów w przeglądarce.",
            does: null,
            cv_hints: ["AngularJS"],
            confused_with: null,
            in_this_project: null,
            sources: [],
            origin: null,
          },
        ],
      },
    });
    renderBrief();
    const chip = await screen.findByRole("button", { name: "Angular" });
    expect(chip).toHaveAttribute("data-glossary", "angular");
    expect(screen.queryByRole("button", { name: "TypeScript" })).toBeNull();
    expect(screen.getByText("TypeScript", { selector: "li > span" })).toBeInTheDocument();
  });

  it("pokazuje 3 pytania screeningowe, resztę po „Pokaż kolejne”", async () => {
    renderBrief();
    expect(await screen.findByText(/1\. Opowiedz o projekcie/)).toBeVisible();
    expect(screen.getByText("Pokaż 1 kolejne")).toBeInTheDocument();
    expect(screen.getByText("Odpada, gdy: brak testów")).toBeInTheDocument();
  });

  it("„Edytuj” przy bloku otwiera szufladę tego bloku", async () => {
    const onEdit = vi.fn();
    renderBrief(onEdit);
    await userEvent.click(await screen.findByRole("button", { name: "Edytuj: Pytania na rozmowę (4)" }));
    expect(onEdit).toHaveBeenCalledWith("screening");
    await userEvent.click(screen.getByRole("button", { name: "Edytuj: Warunki" }));
    expect(onEdit).toHaveBeenCalledWith("conditions");
    await userEvent.click(screen.getByRole("button", { name: "Edytuj: Czego szukamy" }));
    expect(onEdit).toHaveBeenCalledWith("search");
    await userEvent.click(screen.getByRole("button", { name: "Edytuj: Do dopytania u klienta" }));
    expect(onEdit).toHaveBeenCalledWith("insights");
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
    expect(await screen.findByText("Java", { selector: "li > span" })).toBeInTheDocument();
    expect(screen.getByText("do 120,00 PLN/h")).toBeInTheDocument();
    expect(screen.getByText("zdalnie")).toBeInTheDocument();
  });
});
