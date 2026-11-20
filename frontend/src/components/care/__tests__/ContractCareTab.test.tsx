/**
 * Zakładka „Opieka i rozmowy” kontraktu w wariancie A (20.11.2026): cienki
 * wiersz z opiekunem i rytmem, po lewej jeden strumień rozmów i notatek
 * z polem zapisu, po prawej następny krok, plan, zadowolenie i opinie, sprawy
 * i projekt. Awaria karty nie chowa notatek, awaria notatek nie udaje pustki,
 * czytelnik bez prawa zapisu nie widzi przycisków, „Zapisz” przy punkcie planu
 * zamyka go rozmową, „Pomiń” wymaga powodu, tekst z pola strumienia trafia do
 * okna rozmowy, notatka zapisuje się trasą kontraktu z rodzajem z menu, a starą
 * kartę technologiczną edytuje się ze strumienia.
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

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: (...a: unknown[]) => mocks.patch(...a),
  },
  contractsApi: {
    notesTimeline: (id: number) => mocks.get(`/api/contracts/${id}/notes`),
    createNote: (id: number, payload: unknown) => mocks.post(`/api/contracts/${id}/notes`, payload),
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
import type { ContractTimelineItem } from "@/lib/api";
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
      last_contact: { on: "2026-10-20", days_ago: 30 },
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

function timeline(): Pick<ContractTimeline, "events" | "feedback_visible" | "can_edit"> {
  const event = (kind: ContractTimeline["events"][number]["kind"], on: string, title: string) => ({
    kind,
    on,
    title,
    detail: null,
    link: null,
    future: false,
  });
  return {
    events: [
      event("start", "2026-10-01", "Start u klienta"),
      event("tech_card", "2026-10-05", "Karta technologiczna"),
      event("case_opened", "2026-10-06", "Sprawa otwarta: Dostęp do VPN"),
    ],
    feedback_visible: true,
    can_edit: true,
  };
}

const STATE: ClientStateView = { state: null, source: null, questions: [] };

function contractCare(): Pick<ContractCare, "tech_cards" | "conversations"> {
  return {
    conversations: [
      {
        id: 41,
        occurred_on: "2026-10-20",
        channel: "phone",
        satisfaction: 3,
        note: "Brakuje dostępu do VPN.",
        attrition_risk: false,
        wants_change: false,
        project_end_on: null,
        client_hiring: false,
        client_hiring_note: null,
        follow_up_on: null,
        author: { id: 2, name: "Natalia Opiekunka" },
      },
    ],
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
        note: "Zespół płatności.",
        sales_status: null,
        author: null,
      },
    ],
  };
}

const NOTE: ContractTimelineItem = {
  id: 61,
  kind: "note",
  at: "2026-10-15T10:00:00Z",
  summary: null,
  content: "Klient pyta o przedłużenie.",
  sub_type: "general",
  status: null,
  author_id: 7,
  author_name: "jan.testowy@firma.test",
  duration_seconds: null,
};

function serve(data: ConsultantCardData, notes: ContractTimelineItem[] = [NOTE]) {
  mocks.get.mockImplementation((url: string) => {
    if (url.endsWith("/card")) return Promise.resolve({ data });
    if (url.endsWith("/timeline")) return Promise.resolve({ data: timeline() });
    if (url.endsWith("/client-state")) return Promise.resolve({ data: STATE });
    if (url.endsWith("/feedback")) return Promise.resolve({ data: { items: [], client_id: 3, can_write: true } });
    if (url === "/api/contracts/5/notes") return Promise.resolve({ data: notes });
    if (url === "/api/hr/config") return Promise.reject(httpError(403));
    if (url.endsWith("/api/care/contracts/5")) return Promise.resolve({ data: contractCare() });
    if (url.includes("/areas")) return Promise.resolve({ data: { items: [] } });
    return Promise.resolve({ data: { items: [] } });
  });
}

function renderTab(props: Partial<React.ComponentProps<typeof ContractCareTab>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractCareTab contractId={5} canAddNote canReadFeedback {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.patch.mockReset();
  mocks.showToast.mockReset();
});

describe("ContractCareTab — wariant A", () => {
  it("awaria karty to komunikat obok, a notatki kontraktu zostają", async () => {
    mocks.get.mockImplementation((url: string) =>
      url === "/api/contracts/5/notes" ? Promise.resolve({ data: [NOTE] }) : Promise.reject(httpError(500)),
    );
    renderTab();
    expect(await screen.findByText("Nie udało się wczytać karty konsultanta.")).toBeInTheDocument();
    expect(await screen.findByText("Klient pyta o przedłużenie.")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze rozmów/)).not.toBeInTheDocument();
  });

  it("wyłączony moduł mówi to wprost", async () => {
    mocks.get.mockRejectedValue(httpError(404, "Ten moduł nie jest jeszcze włączony."));
    renderTab();
    expect(await screen.findByText("Ten moduł nie jest jeszcze włączony.")).toBeInTheDocument();
  });

  it("awaria notatek to zdanie z ponowieniem, nie pusty strumień", async () => {
    serve(card());
    const served = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url: string) =>
      url === "/api/contracts/5/notes" ? Promise.reject(httpError(500)) : served(url),
    );
    renderTab();
    await screen.findByRole("group", { name: "Opiekun i rytm" });
    expect(await screen.findByText("Nie udało się wczytać notatek kontraktu.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spróbuj ponownie" })).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze rozmów/)).not.toBeInTheDocument();
  });

  it("wiersz z opiekunem i rytmem, strumień i prawa kolumna; bez imienia i powodów „Uwaga”", async () => {
    serve(card());
    renderTab();
    const owner = await screen.findByRole("group", { name: "Opiekun i rytm" });
    expect(owner).toHaveTextContent("Opiekun: Natalia Opiekunka (Delivery Lead kontraktu)");
    expect(owner).toHaveTextContent("rytm: co 2 tygodnie");
    expect(owner).toHaveTextContent("ostatni kontakt 20.10.2026 (30 dni temu)");
    // Imię, zdrowie i „dlaczego” stoją w nagłówku i w pasie „Co się dzieje”.
    expect(screen.queryByRole("heading", { name: "Anna Przykładowa" })).toBeNull();
    expect(screen.queryByText(/Dlaczego „Uwaga”/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Karta technologiczna" })).toBeNull();

    const stream = await screen.findByRole("list", { name: "Strumień rozmów i notatek" });
    await waitFor(() => expect(within(stream).getAllByRole("listitem")).toHaveLength(4));
    expect(within(stream).getByText("Rozmowa z konsultantem · telefon")).toBeInTheDocument();
    expect(within(stream).getByText("Sprawa otwarta: Dostęp do VPN")).toBeInTheDocument();
    expect(within(stream).getByText(/Jan Testowy/)).toBeInTheDocument();
    expect(screen.queryByText("Start u klienta")).toBeNull();

    expect(screen.getByRole("region", { name: "Następny krok" })).toHaveTextContent("Zaległa rozmowa");
    const opinions = screen.getByRole("region", { name: "Zadowolenie i opinie" });
    expect(within(opinions).getByText("3 / 5")).toBeInTheDocument();
    expect(within(opinions).getByText("3,7")).toBeInTheDocument();
    expect(await within(opinions).findByText("brak")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Sprawy" })).toHaveTextContent("Brak otwartych spraw");
    expect(screen.getByText(/Nic jeszcze nie wiemy o projekcie/)).toBeInTheDocument();
  });

  it("czytelnik bez zapisu opieki i bez D11: tylko notatka w polu, bez przycisków planu", async () => {
    serve(
      card({
        health: null,
        can_edit: false,
        can_change_owner: false,
        can_see_feedback: false,
        kpis: { last_contact: null, satisfaction: null, manager_feedback: null, order_end: null },
      }),
    );
    renderTab({ canReadFeedback: false });
    await screen.findByRole("group", { name: "Opiekun i rytm" });
    expect(screen.getByText("widzi opiekun, DL, HoR i admin")).toBeInTheDocument();
    // Zostaje sama notatka kontraktu (edycja kontraktów), bez rozmowy i opinii.
    expect(screen.queryByRole("radiogroup", { name: "Rodzaj wpisu" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Zapisz rozmowę…" })).toBeNull();
    const plan = screen.getByRole("region", { name: "Plan kontaktów" });
    expect(within(plan).getByText(/po terminie/)).toBeInTheDocument();
    expect(within(plan).queryByRole("button")).toBeNull();
    expect(screen.getByText(/Opinie klienta widzą opiekun/)).toBeInTheDocument();
  });

  it("„Zapisz” przy punkcie planu wysyła rozmowę zamykającą ten punkt", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    mocks.post.mockResolvedValue({ data: { conversation_id: 1, tech_card_id: null, case_ids: [], demand_notified: 0 } });
    renderTab();
    const plan = await screen.findByRole("region", { name: "Plan kontaktów" });
    await user.click(within(plan).getByRole("button", { name: "Zapisz" }));
    const dialog = await screen.findByRole("dialog", { name: "Rozmowa · Anna Przykładowa" });
    expect(within(dialog).getByText(/Zamyka punkt planu: dzień 7 \d\d\.\d\d\./)).toBeInTheDocument();
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
    const plan = await screen.findByRole("region", { name: "Plan kontaktów" });
    await user.click(within(plan).getByRole("button", { name: "Pomiń" }));
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

  it("tekst z pola strumienia trafia do okna rozmowy, a po zapisie pole jest puste", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    mocks.post.mockResolvedValue({ data: { conversation_id: 2, tech_card_id: null, case_ids: [], demand_notified: 0 } });
    renderTab();
    const kinds = await screen.findByRole("radiogroup", { name: "Rodzaj wpisu" });
    // Czeka punkt planu — na start rozmowa z konsultantem.
    expect(within(kinds).getByRole("radio", { name: "Rozmowa z konsultantem" })).toHaveAttribute("aria-checked", "true");
    const field = screen.getByLabelText("Treść wpisu");
    await user.type(field, "Dostał VPN.");
    await user.click(screen.getByRole("button", { name: "Zapisz rozmowę…" }));
    const dialog = await screen.findByRole("dialog", { name: "Rozmowa · Anna Przykładowa" });
    expect(within(dialog).getByLabelText("Notatka")).toHaveValue("Dostał VPN.");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz rozmowę" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ plan_item_id: 11, note: "Dostał VPN." });
    await waitFor(() => expect(screen.getByLabelText("Treść wpisu")).toHaveValue(""));
  });

  it("notatka zapisuje się trasą kontraktu z rodzajem z menu, nie z natywnej listy", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    mocks.post.mockResolvedValue({ data: NOTE });
    renderTab();
    await user.click(await screen.findByRole("radio", { name: "Notatka" }));
    expect(screen.queryByRole("combobox", { name: "Rodzaj notatki" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Rodzaj notatki: Notatka" }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Spotkanie" }));
    const field = screen.getByLabelText("Treść wpisu");
    await user.type(field, "Spotkanie u klienta.");
    await user.click(within(field.closest("form")!).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0]).toEqual([
      "/api/contracts/5/notes",
      { content: "Spotkanie u klienta.", note_type: "meeting" },
    ]);
    expect(mocks.showToast).toHaveBeenCalledWith("Notatka zapisana przy kontrakcie", "success");
  });

  it("„Edytuj” przy karcie technologicznej w strumieniu otwiera starą kartę", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    serve(card());
    renderTab();
    // Strumień przed wczytaniem karty stoi w układzie zastępczym — szukamy go po karcie.
    await screen.findByRole("group", { name: "Opiekun i rytm" });
    const stream = await screen.findByRole("list", { name: "Strumień rozmów i notatek" });
    await user.click(await within(stream).findByRole("button", { name: "Edytuj" }));
    expect(await screen.findByRole("dialog", { name: "Karta technologiczna" })).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/care/contracts/5");
  });

  it("bez modułu opieki zostają same notatki — karta opieki nie jest pytana", async () => {
    serve(card());
    renderTab({ careOpen: false });
    expect(await screen.findByText("Klient pyta o przedłużenie.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Opiekun i rytm" })).toBeNull();
    expect(mocks.get.mock.calls.some(([url]) => String(url).startsWith("/api/care/"))).toBe(false);
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
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
