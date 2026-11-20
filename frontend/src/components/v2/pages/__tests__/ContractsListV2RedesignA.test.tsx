/**
 * Lista kontraktów w wariancie A (przebudowa 20.11.2026): „Co dalej” w wierszu,
 * typ i status drobnym drukiem tylko przy innej wartości niż „B2B”/„Aktywny”,
 * „Więcej filtrów” zamiast listy statusów obok pigułek, „Grupuj: klient”
 * i „Kończące się” jako odejścia do domknięcia z osią czasu.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ContractsListV2, periodEndLine } from "@/components/v2/pages/ContractsListV2";
import { useAuthStore } from "@/store/auth";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    default: {
      get: (...args: unknown[]) => mocks.get(...args),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
    contractorsApi: { stats: () => Promise.resolve({ data: { drafts_incomplete: 0 } }) },
  };
});

vi.mock("@/components/contracts/ContractSidePanel", () => ({
  ContractSidePanel: (props: { contractId: number }) => (
    <div data-testid="contract-side-panel">panel {props.contractId}</div>
  ),
}));

// Dzień firmy na sztywno — progi „Co dalej” liczą się od dziś.
vi.mock("@/lib/warsaw-date", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/warsaw-date")>()),
  warsawToday: () => "2026-11-20",
}));

type Row = Record<string, unknown> & { id: number; candidate_name: string };

const contract = (over: Row): Row => ({
  candidate_id: over.id + 1000,
  client_id: 1,
  client_name: "Bank Alfa",
  job_title: "Tester",
  status: "active",
  contract_type: "b2b",
  start_date: "2025-01-01",
  end_date: null,
  terminated_at: null,
  termination_reason: null,
  agreement_termination_mode: null,
  client_order_start_date: "2026-01-01",
  client_order_end_date: "2027-06-30",
  prolongation_status: "unknown",
  rate_candidate: 120,
  rate_client: 160,
  margin: 40,
  rate_unit: "hourly",
  billing_hours_per_month: 168,
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  missing_fields: [],
  ...over,
});

const ROWS: Row[] = [
  contract({ id: 1, candidate_name: "Ola Spokojna" }),
  contract({ id: 2, candidate_name: "Jan Zamówienie", client_order_end_date: "2026-12-31", prolongation_status: "yes" }),
  contract({
    id: 3,
    candidate_name: "Ewa Odchodzi",
    client_id: 2,
    client_name: "Bank Beta",
    status: "ending",
    end_date: "2026-11-30",
    terminated_at: "2026-11-30",
    termination_reason: "project_ended",
    client_order_end_date: "2026-11-30",
  }),
  contract({ id: 4, candidate_name: "Piotr Zlecenie", contract_type: "uzlecenie", start_date: "2026-12-01" }),
];

const ENDING: Row[] = [
  ROWS[2],
  contract({
    id: 5,
    candidate_name: "Marek Konflikt",
    status: "ending",
    end_date: "2026-11-30",
    terminated_at: "2026-11-30",
    termination_reason: "better_offer",
    agreement_termination_mode: "notice",
    client_order_start_date: "2026-12-01",
    client_order_end_date: "2027-05-31",
  }),
];

function payload(rows: Row[], grouped: boolean) {
  return {
    items: rows.map((row) => ({ ...row, group_members: grouped ? [row] : [] })),
    total: rows.length,
    contractors_total: rows.length,
    contracts_total: rows.length,
    future_start_total: 0,
    page: 1,
    page_size: grouped ? 20 : 100,
  };
}

const listCalls = () =>
  mocks.get.mock.calls
    .filter((call) => call[0] === "/api/contracts" && call[1]?.params?.page_size !== 1)
    .map((call) => call[1].params as Record<string, unknown>);

function renderList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ContractsListV2 />
    </QueryClientProvider>,
  );
}

function signIn(capabilities: string[], extra: Record<string, unknown> = {}) {
  useAuthStore.setState({
    user: {
      id: 1,
      email: "admin@example.com",
      name: "Admin",
      role: "admin",
      roles: ["admin"],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      capabilities,
      analytics_capabilities: capabilities,
      ...extra,
    },
    realUser: null,
    hydrated: true,
  } as never);
}

const row = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;

beforeEach(() => {
  window.history.replaceState({}, "", "/contracts");
  window.sessionStorage.clear();
  signIn(["view_finance"]);
  mocks.get.mockReset();
  mocks.get.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
    if (url !== "/api/contracts") return Promise.resolve({ data: [] });
    const params = config?.params ?? {};
    if (params.page_size === 1) return Promise.resolve({ data: payload(ROWS, true) });
    const rows = params.bucket === "ending" ? ENDING : ROWS;
    return Promise.resolve({ data: payload(rows, params.group_by_candidate === true) });
  });
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("lista „Aktywne” — „Co dalej” i drobny druk", () => {
  it("zdanie w wierszu z progów paska strony, kreska przy spokojnym kontrakcie", async () => {
    renderList();
    await screen.findByText("Ola Spokojna");
    expect(within(row("Ola Spokojna")).getByText("—", { selector: "span" })).toBeInTheDocument();
    const next = within(row("Jan Zamówienie")).getByTestId("contract-next-steps");
    expect(next).toHaveTextContent("Zamówienie kończy się 31.12.2026 — za 41 dni");
    expect(next).toHaveTextContent("Klient przedłuża.");
    expect(within(row("Ewa Odchodzi")).getByTestId("contract-next-steps")).toHaveTextContent(
      "Współpraca kończy się 30.11.2026 — za 10 dni",
    );
  });

  it("typ i status drobnym drukiem tylko, gdy to nie „B2B” i „Aktywny”", async () => {
    renderList();
    await screen.findByText("Ola Spokojna");
    expect(row("Ola Spokojna").querySelector('[data-testid="contract-row-note"]')).toBeNull();
    expect(within(row("Ewa Odchodzi")).getByTestId("contract-row-note")).toHaveTextContent("Kończący się");
    expect(within(row("Piotr Zlecenie")).getByTestId("contract-row-note")).toHaveTextContent("Zlecenie");
    expect(within(row("Piotr Zlecenie")).getByTestId("contract-next-steps")).toHaveTextContent(
      "Startuje 01.12.2026 — za 11 dni",
    );
  });

  it("bez filtra statusu obok pigułek; status i typ w „Więcej filtrów” z chipem", async () => {
    renderList();
    await screen.findByText("Ola Spokojna");
    expect(screen.queryByText(/^Status: \d/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Więcej filtrów/ }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Typ: Umowa zlecenie" }));
    await waitFor(() => expect(listCalls().at(-1)).toMatchObject({ contract_type: ["uzlecenie"] }));
    expect(screen.getByRole("button", { name: "Usuń filtr typu: Umowa zlecenie" })).toBeInTheDocument();
  });
});

describe("„Grupuj: klient”", () => {
  it("bierze cały zbiór umowa po umowie i pokazuje nagłówki klientów z liczbami", async () => {
    renderList();
    await screen.findByText("Ola Spokojna");
    fireEvent.click(screen.getByRole("button", { name: /Grupuj: klient/ }));

    const alfa = await screen.findByRole("button", { name: /Bank Alfa/ });
    await waitFor(() =>
      expect(listCalls().at(-1)).toMatchObject({ group_by_candidate: false, page: 1, page_size: 100 }),
    );
    expect(window.location.search).toContain("group=client");
    const alfaHeader = alfa.closest("td") as HTMLElement;
    expect(alfaHeader).toHaveTextContent("3 osoby");
    // 3 umowy × 40 zł/h × 168 h
    expect(alfaHeader).toHaveTextContent(/marża 20\s160 zł\/mies\./);
    expect(alfaHeader).toHaveTextContent("1 startuje");
    expect(alfa).toHaveAttribute("aria-expanded", "true");
    // Druga grupa domyślnie zwinięta; rozwija się kliknięciem.
    const beta = screen.getByRole("button", { name: /Bank Beta/ });
    expect(beta).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Ewa Odchodzi")).toBeNull();
    expect(beta.closest("td")).toHaveTextContent("1 odchodzi");
    fireEvent.click(beta);
    expect(await screen.findByText("Ewa Odchodzi")).toBeInTheDocument();
  });

  it("bez wglądu w kwoty nagłówek grupy nie mówi o marży", async () => {
    signIn([], { role: "recruiter", roles: ["recruiter"] });
    renderList();
    await screen.findByText("Ola Spokojna");
    fireEvent.click(screen.getByRole("button", { name: /Grupuj: klient/ }));
    const alfa = await screen.findByRole("button", { name: /Bank Alfa/ });
    expect(alfa.closest("td")).not.toHaveTextContent(/marża/);
  });
});

describe("„Kończące się” — odejścia i oś czasu", () => {
  it("tabela odejść: ostatni dzień, powód, umowa B2B i niespójność z zamówieniem", async () => {
    window.history.replaceState({}, "", "/contracts?status=all&ending=30");
    renderList();
    const view = await screen.findByTestId("contracts-ending-view");
    await within(view).findByText("Ewa Odchodzi");
    expect(within(view).getByTestId("contracts-ending-summary")).toHaveTextContent("2 osoby odchodzi do 30.11.2026");
    expect(within(view).getByTestId("contracts-ending-summary")).toHaveTextContent("1 z 2 umów B2B bez zapisanego rozwiązania");
    const ewa = within(view).getByText("Ewa Odchodzi").closest("tr") as HTMLElement;
    expect(ewa).toHaveTextContent("Koniec projektu");
    expect(ewa).toHaveTextContent("nierozwiązana");
    expect(ewa).toHaveTextContent("za 10 dni");
    const marek = within(view).getByText("Marek Konflikt").closest("tr") as HTMLElement;
    expect(within(marek).getByTestId("contract-ending-conflict")).toHaveTextContent(
      "Zamówienie 01.12.2026 – 31.05.2027 trwa po odejściu — sprawdź zakończenie",
    );
    expect(marek).toHaveTextContent("wypowiedziana");
    // Klik w wiersz otwiera panel, jak na liście.
    fireEvent.click(ewa);
    expect(await screen.findByTestId("contract-side-panel")).toHaveTextContent("panel 3");
  });

  it("oś czasu: przełącznik w adresie, grupy po miesiącu i przerywany pasek zamówienia", async () => {
    window.history.replaceState({}, "", "/contracts?status=all&ending=30");
    renderList();
    const view = await screen.findByTestId("contracts-ending-view");
    await within(view).findByText("Ewa Odchodzi");
    fireEvent.click(within(view).getByRole("button", { name: "Oś czasu" }));
    const timeline = await within(view).findByTestId("contracts-ending-timeline");
    await waitFor(() => expect(window.location.search).toContain("timeline=1"));
    expect(timeline).toHaveTextContent("Listopad 2026");
    expect(within(timeline).getAllByTestId("contract-ending-order-bar")).toHaveLength(1);
  });

  it("bez prawa do statusu kontraktu nie ma „Zapisz rozwiązanie umowy”", async () => {
    signIn(["view_finance"], { role: "recruiter", roles: ["recruiter"] });
    window.history.replaceState({}, "", "/contracts?status=all&ending=30");
    renderList();
    const view = await screen.findByTestId("contracts-ending-view");
    await within(view).findByText("Ewa Odchodzi");
    expect(within(view).queryByRole("button", { name: "Zapisz rozwiązanie umowy" })).toBeNull();
  });
});

describe("druga linia „Okresu”", () => {
  it("koniec zamówienia, bezterminowo, ostatnie zamówienie albo umowa", () => {
    expect(periodEndLine({ client_order_start_date: "2026-01-01", client_order_end_date: "2026-12-31" })).toEqual({
      text: "→ 31.12.2026",
      warning: false,
    });
    expect(periodEndLine({ client_order_start_date: "2026-01-01", client_order_end_date: null })?.text).toBe("→ bezterminowo");
    expect(periodEndLine({ latest_order_end_date: "2026-11-30" })).toEqual({ text: "→ 30.11.2026", warning: true });
    expect(periodEndLine({ end_date: "2026-09-30" })?.text).toBe("umowa do 30.09.2026");
    expect(periodEndLine({})).toBeNull();
  });
});
