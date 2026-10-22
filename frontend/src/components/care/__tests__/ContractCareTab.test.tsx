/**
 * Zakładka „Opieka” kontraktu = karta konsultanta (22.10.2026): awaria
 * odczytu nie wygląda jak brak historii, czytelnik bez prawa zapisu nie
 * widzi przycisków, zdrowie spoza D11 nie ma etykiety, „Zapisz” przy punkcie
 * planu zamyka go rozmową, „Pomiń” wymaga powodu, historia ma filtry, a starą
 * kartę technologiczną edytuje się z historii (przycisku „Karta
 * technologiczna” już nie ma).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: (...a: unknown[]) => mocks.patch(...a),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

// Lista wyboru Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { ContractCareTab } from "@/components/care/ContractCareTab";
import type {
  ClientStateView,
  ConsultantCardData,
  ContractCare,
  ContractTimeline,
} from "@/lib/api/care";

function httpError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: detail ? { detail } : {} },
  });
}

function card(overrides: Partial<ConsultantCardData> = {}): ConsultantCardData {
  return {
    contract_id: 5,
    candidate_id: 9,
    candidate_name: "Anna Przykładowa",
    client_id: 3,
    client_name: "Firma Testowa",
    role: "Analityczka danych",
    form: "b2b",
    start_on: "2026-10-01",
    end_on: null,
    owner: { user_id: 2, name: "Natalia Opiekunka", source: "delivery_lead" },
    cadence: { level: "biweekly", label: "co 2 tygodnie", until_on: null },
    health: { level: "watch", label: "Uwaga", reasons: ["rozmowa zaległa od 14 dni"] },
    kpis: {
      last_contact: null,
      satisfaction: { value: 3, previous: 5 },
      manager_feedback: { avg: 3.7, extension: "likely", on: "2026-10-12" },
      order_end: { on: "2026-11-20", days: 29 },
    },
    next_step: { kind: "conversation", label: "Zaległa rozmowa", detail: "Dzień 7 · 14 dni po terminie." },
    known_project: null,
    cases: [],
    plan: [{ id: 11, kind: "day_7", label: "Dzień 7", due_on: "2026-10-08", status: "open", skip_reason: null }],
    can_edit: true,
    can_change_owner: true,
    can_see_feedback: true,
    ...overrides,
  };
}

function timeline(): ContractTimeline {
  const event = (kind: ContractTimeline["events"][number]["kind"], on: string, title: string) => ({
    kind,
    on,
    title,
    detail: null,
    link: null,
    future: false,
  });
  return {
    contract: {
      id: 5,
      candidate_id: 9,
      candidate_name: "Anna Przykładowa",
      client_id: 3,
      client_name: "Firma Testowa",
      job_id: null,
      job_title: null,
      status: "active",
      is_live: true,
      start_date: "2026-10-01",
      end_date: null,
    },
    owner: null,
    manager: null,
    signals: [],
    front_office_reasons: [],
    events: [
      event("start", "2026-10-01", "Start u klienta"),
      event("tech_card", "2026-10-05", "Karta technologiczna"),
      event("case_opened", "2026-10-06", "Sprawa: Dostęp do VPN"),
      event("feedback", "2026-10-12", "Opinia: Piotr Menedżerski"),
    ],
    feedback_visible: true,
    can_edit: true,
  };
}

const STATE: ClientStateView = { state: null, source: null, questions: [] };

function contractCare(): Pick<ContractCare, "tech_cards"> {
  return {
    tech_cards: [
      {
        id: 31,
        contract_id: 5,
        client_id: 3,
        interview_on: "2026-10-05",
        status: "ok",
        is_draft: false,
        finalized_at: null,
        satisfaction: 4,
        area: null,
        skills: [],
        unrecognized_skills: [],
        vendors: [],
        hiring: null,
        hiring_source: null,
        hiring_roles: [],
        project_end_on: null,
        project_end_unknown: false,
        team_size: null,
        team_externals: null,
        initiatives: [],
        memorable_quote: null,
        note: null,
        sales_status: null,
        author: null,
      },
    ],
  };
}

function serve(data: ConsultantCardData) {
  mocks.get.mockImplementation((url: string) => {
    if (url.endsWith("/card")) return Promise.resolve({ data });
    if (url.endsWith("/timeline")) return Promise.resolve({ data: timeline() });
    if (url.endsWith("/client-state")) return Promise.resolve({ data: STATE });
    if (url === "/api/hr/config") return Promise.reject(httpError(403));
    if (url.endsWith("/api/care/contracts/5")) return Promise.resolve({ data: contractCare() });
    if (url.includes("/areas")) return Promise.resolve({ data: { items: [] } });
    return Promise.resolve({ data: { items: [] } });
  });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractCareTab contractId={5} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.patch.mockReset();
});

describe("ContractCareTab", () => {
  it("awaria serwera to komunikat z ponowieniem, nie pusta historia", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderTab();
    expect(await screen.findByText("Nie udało się wczytać karty konsultanta.")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma jeszcze zdarzeń/)).not.toBeInTheDocument();
  });

  it("wyłączony moduł mówi to wprost", async () => {
    mocks.get.mockRejectedValue(httpError(404, "Ten moduł nie jest jeszcze włączony."));
    renderTab();
    expect(await screen.findByText("Ten moduł nie jest jeszcze włączony.")).toBeInTheDocument();
  });

  it("zdrowie z „dlaczego”, cztery liczby, opiekun i rytm; bez „Karty technologicznej”", async () => {
    serve(card());
    renderTab();
    expect(await screen.findByRole("heading", { name: "Anna Przykładowa" })).toBeInTheDocument();
    expect(screen.getByText("Uwaga")).toBeInTheDocument();
    expect(screen.getByText("rozmowa zaległa od 14 dni")).toBeInTheDocument();
    const kpis = screen.getByRole("region", { name: "Najważniejsze liczby" });
    expect(within(kpis).getByText("brak rozmów")).toBeInTheDocument();
    expect(within(kpis).getByText("spadek z 5/5")).toBeInTheDocument();
    expect(within(kpis).getByText("3,7 / 5")).toBeInTheDocument();
    expect(within(kpis).getByText("za 29 dni")).toBeInTheDocument();
    expect(screen.getByText(/Opiekun: Natalia Opiekunka · Delivery Lead kontraktu · rytm co 2 tygodnie/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Następny krok" })).toHaveTextContent("Zaległa rozmowa");
    expect(screen.queryByRole("button", { name: "Karta technologiczna" })).toBeNull();
    expect(screen.getByText(/Nic jeszcze nie wiemy o projekcie/)).toBeInTheDocument();
  });

  it("czytelnik spoza D11: bez etykiety zdrowia, bez opinii i bez przycisków zapisu", async () => {
    serve(
      card({
        health: null,
        can_edit: false,
        can_change_owner: false,
        can_see_feedback: false,
        kpis: { last_contact: null, satisfaction: null, manager_feedback: null, order_end: null },
      }),
    );
    renderTab();
    await screen.findByRole("heading", { name: "Anna Przykładowa" });
    expect(screen.queryByText("Uwaga")).toBeNull();
    expect(screen.getByText("widzi opiekun, DL, HoR i admin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz rozmowę" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Plan kontaktów/ }));
    expect(screen.getByText("po terminie")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz" })).toBeNull();
  });

  it("„Zapisz” przy punkcie planu wysyła rozmowę zamykającą ten punkt, bez stanu u klienta", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    mocks.post.mockResolvedValue({ data: { conversation_id: 1, tech_card_id: null, case_ids: [], demand_notified: 0 } });
    renderTab();
    await user.click(await screen.findByRole("button", { name: /Plan kontaktów/ }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    const dialog = await screen.findByRole("dialog", { name: "Rozmowa · Anna Przykładowa" });
    expect(within(dialog).getByText(/Zamyka punkt planu: Dzień 7/)).toBeInTheDocument();
    expect(within(dialog).getByText("Zapiszemy: rozmowę.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("radio", { name: "4 z 5" }));
    await user.click(within(dialog).getByRole("button", { name: "Zapisz rozmowę" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    const [url, body] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/care/contracts/5/conversations");
    expect(body).toMatchObject({ plan_item_id: 11, channel: "phone", satisfaction: 4, client_state: null, cases: [] });
    expect(mocks.showToast).toHaveBeenCalledWith("Rozmowa zapisana", "success");
  });

  it("„Pomiń” wymaga powodu z listy i wysyła go z notatką", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    mocks.patch.mockResolvedValue({ data: { contract: { client_id: 3 } } });
    renderTab();
    await user.click(await screen.findByRole("button", { name: /Plan kontaktów/ }));
    await user.click(screen.getByRole("button", { name: "Pomiń" }));
    const dialog = await screen.findByRole("dialog", { name: "Pomiń kontakt" });
    await user.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz powód pominięcia.");
    expect(mocks.patch).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("combobox", { name: /Powód/ }));
    await user.click(await screen.findByRole("option", { name: "Nieobecność konsultanta" }));
    await user.type(within(dialog).getByLabelText(/Notatka/), "Wraca za tydzień.");
    await user.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalled());
    expect(mocks.patch.mock.calls[0]).toEqual([
      "/api/care/plan-items/11",
      { status: "skipped", reason: "absence", note: "Wraca za tydzień." },
    ]);
  });

  it("historia z filtrami; „Edytuj” przy karcie technologicznej otwiera starą kartę", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    renderTab();
    const history = await screen.findByRole("list", { name: "Historia konsultanta" });
    expect(within(history).getAllByRole("listitem")).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Sprawy 1" }));
    expect(within(screen.getByRole("list", { name: "Historia konsultanta" })).getAllByRole("listitem")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Rozmowy 1" }));
    await user.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(await screen.findByRole("dialog", { name: "Karta technologiczna" })).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/care/contracts/5");
  });
});

describe("findTechCard", () => {
  it("szuka karty po id zdarzenia, a bez id (stara oś) po dacie", async () => {
    const { findTechCard } = await import("../ContractCareTab");
    const cards = [
      { id: 1, interview_on: "2026-10-20" },
      { id: 2, interview_on: "2026-10-20" },
    ];
    expect(findTechCard(cards, { id: 2, on: "2026-10-20" })?.id).toBe(2);
    expect(findTechCard(cards, { id: null, on: "2026-10-20" })?.id).toBe(1);
    expect(findTechCard(cards, { id: 9, on: "2026-10-20" })).toBeNull();
    expect(findTechCard(undefined, { id: 1, on: "2026-10-20" })).toBeNull();
  });
});
