/**
 * Lejek Fabryki IT mierzony kontaktem: lista kont z podpowiedzią rozjazdu etapu,
 * kolejka osób do pierwszego kontaktu i liczniki „Kogo znamy”. Dane fikcyjne.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionMapEntry, Opportunity, Pipeline, Stage } from "@/lib/api/sales";
import type { FactoryAccount, FactoryQueue as QueueData, FactoryQueuePerson, KnownCounts } from "@/lib/api/sales-factories";

const replaceUrl = vi.fn();
const accountsQuery = vi.fn();
const queueQuery = vi.fn();
const knownQuery = vi.fn();
const opportunitiesQuery = vi.fn();
let searchParams = new URLSearchParams();
let canEdit = true;

vi.mock("@/lib/api/sales-factories", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-factories")>()),
  useFactoryAccounts: (archived: boolean) => accountsQuery(archived),
  useFactoryQueue: (ownerId: number | null) => queueQuery(ownerId),
  useFactoryKnownPeople: (archived: boolean) => knownQuery(archived),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  usePipelines: () => ({ data: PIPELINES, isLoading: false, error: null, isSuccess: true }),
  useOpportunities: () => opportunitiesQuery(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl }) }));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } }) => unknown) => selector({ user: { id: 1 } }),
}));
vi.mock("../useOwnerFilterOptions", () => ({ useOwnerFilterOptions: () => [] }));
vi.mock("../DecisionPersonDialog", () => ({
  DecisionPersonDialog: ({ opportunityId, entry }: { opportunityId: number; entry: DecisionMapEntry }) => (
    <div role="dialog">
      Poprawka: {entry.name} (szansa {opportunityId})
    </div>
  ),
}));
vi.mock("../OpportunityBoard", () => ({ OpportunityBoard: () => <div>Tablica etapów</div> }));
vi.mock("../OpportunityFormDialog", () => ({ OpportunityFormDialog: () => null }));

import { FactoriesView } from "../factories/FactoriesView";
import { FactoryAccountsTable } from "../factories/FactoryAccountsTable";
import { FactoryQueue } from "../factories/FactoryQueue";
import {
  channelsLabel,
  knownLabel,
  levelLabel,
  matchesSearch,
  stageHint,
  summarizeAccounts,
  summaryLine,
} from "../factories/factories";
import { OpportunitiesView } from "../OpportunitiesView";

const stage = (id: number, key: string, name: string): Stage => ({
  id,
  key,
  name,
  position: id,
  probability: 0,
  outcome: "open",
  qualifies: false,
  color: null,
});

const PIPELINES = [
  { id: 1, key: "sales", name: "Sprzedaż", is_default: true, stages: [stage(1, "lead", "Lead")] },
  {
    id: 2,
    key: "atlas-it-factories",
    name: "Fabryki IT",
    is_default: false,
    stages: [stage(21, "itf-decision-map-done", "Mapa decyzyjna gotowa"), stage(22, "itf-first-contact", "Pierwszy kontakt")],
  },
] as Pipeline[];

function opportunity(id: number, company: string, stageName: string, overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id,
    title: `Fabryka: ${company}`,
    company: { id: id * 10, name: company },
    pipeline_id: 2,
    stage: stage(22, "itf-first-contact", stageName),
    status: "open",
    owner: { id: 5, name: "Opiekun Testowy" },
    last_touch_at: "2026-10-01T10:00:00Z",
    next_step: null,
    overdue_step: null,
    step_alarm: false,
    waiting_for_reply: false,
    ...overrides,
  } as Opportunity;
}

function account(opportunityId: number, overrides: Partial<FactoryAccount> = {}): FactoryAccount {
  return {
    opportunity_id: opportunityId,
    company_id: opportunityId * 10,
    map_total: 4,
    map_contacted: 0,
    top_total: 3,
    top_contacted: 0,
    waiting: 3,
    stage_mismatch: false,
    client: null,
    ...overrides,
  };
}

function person(name: string, level: number | null, overrides: Partial<FactoryQueuePerson> = {}): FactoryQueuePerson {
  return {
    opportunity: { id: 31, title: "Fabryka: Firma Sowa" },
    company: { id: 310, name: "Firma Sowa" },
    client: null,
    person: { name, key: `klucz-${name}`, decision_level: level, contact_status: "not_contacted", phone: "600 100 200" },
    ...overrides,
  };
}

const known = (companyId: number, current: number, past: number): KnownCounts => ({
  company_id: companyId,
  current,
  past,
  via_us: 0,
  unknown: 0,
});

const success = <T,>(data: T) => ({ data, isLoading: false, isSuccess: true, isError: false, error: null, refetch: vi.fn() });
const failure = () => ({
  data: undefined,
  isLoading: false,
  isSuccess: false,
  isError: true,
  error: { response: { status: 500 } },
  refetch: vi.fn(),
});

const queueData = (people: FactoryQueuePerson[], lower: FactoryQueuePerson[] = []): QueueData => ({
  owner: { id: 1, name: "Opiekun Testowy" },
  people,
  lower_levels: lower,
});

beforeEach(() => {
  replaceUrl.mockClear();
  accountsQuery.mockReset().mockReturnValue(success<FactoryAccount[]>([]));
  queueQuery.mockReset().mockReturnValue(success(queueData([])));
  knownQuery.mockReset().mockReturnValue(success({ items: [], truncated: false }));
  opportunitiesQuery.mockReset();
  searchParams = new URLSearchParams();
  canEdit = true;
});

describe("podpisy i sumy", () => {
  it("podsumowanie liczy konta widoczne na liście", () => {
    const items = [opportunity(1, "Firma Sowa", "Pierwszy kontakt"), opportunity(2, "Firma Kos", "Mapa decyzyjna gotowa")];
    const facts = new Map([
      [1, account(1, { map_total: 4, map_contacted: 1, top_total: 3, top_contacted: 1 })],
      [2, account(2, { map_total: 6, map_contacted: 2, top_total: 2, top_contacted: 0 })],
    ]);
    expect(summaryLine(summarizeAccounts(items, facts))).toBe(
      "2 konta · 10 osób na mapach · po kontakcie 3 (30%) · poziom 1 i 2: 1 z 5",
    );
    expect(summaryLine(summarizeAccounts(items, new Map()))).toBe("2 konta · mapy są puste");
  });

  it("podpowiedź etapu rozróżnia pustą mapę od mapy bez kontaktu", () => {
    expect(stageHint(account(1))).toBeNull();
    expect(stageHint(undefined)).toBeNull();
    expect(stageHint(account(1, { stage_mismatch: true }))).toBe("na mapie nikt po kontakcie");
    expect(stageHint(account(1, { stage_mismatch: true, map_total: 0 }))).toBe("mapa jest pusta");
  });

  it("opisuje poziom, kanały i ludzi z bazy bez nazwisk kandydatów", () => {
    const entry = person("Anna Testowa", 2).person;
    expect(levelLabel(entry)).toBe("Poziom 2 · Dyrektorzy");
    expect(levelLabel({ ...entry, decision_level: null })).toBe("Bez poziomu");
    expect(channelsLabel({ ...entry, email: "a@example.com", linkedin_url: "https://example.com/in/a" })).toBe(
      "telefon · e-mail · LinkedIn",
    );
    expect(channelsLabel({ ...entry, phone: null })).toBe("brak danych kontaktowych");
    expect(knownLabel(undefined)).toBeNull();
    expect(knownLabel(known(1, 0, 0))).toBe("nikogo z bazy tam nie znamy");
    expect(knownLabel(known(1, 49, 114))).toBe("z bazy pracuje tam teraz 49 · kiedyś 114");
  });

  it("szukanie w kolejce patrzy na firmę, osobę i stanowisko", () => {
    const row = person("Anna Testowa", 1);
    row.person.role_in_company = "Dyrektor IT";
    expect(matchesSearch(row, "")).toBe(true);
    expect(matchesSearch(row, "sowa")).toBe(true);
    expect(matchesSearch(row, "DYREKTOR")).toBe(true);
    expect(matchesSearch(row, "kos")).toBe(false);
  });
});

describe("lista kont", () => {
  const items = [
    opportunity(1, "Firma Sowa", "Pierwszy kontakt"),
    opportunity(2, "Firma Kos", "Pierwszy kontakt"),
    opportunity(3, "Firma Czyż", "Mapa decyzyjna gotowa"),
  ];
  const facts = new Map([
    [1, account(1, { stage_mismatch: true })],
    [2, account(2, { map_contacted: 2, waiting: 1 })],
    [3, account(3, { client: { name: "Czyż S.A.", delivery_lead: "Lider Dostaw" }, waiting: 0 })],
  ]);
  const rowOf = (company: string) => screen.getByRole("link", { name: company }).closest("tr") as HTMLElement;

  it("pokazuje podpowiedź, gdy etap mówi o kontakcie, a mapa go nie potwierdza", () => {
    render(<FactoryAccountsTable items={items} accounts={facts} known={new Map()} knownState="ready" />);
    const mismatch = within(rowOf("Firma Sowa"));
    expect(mismatch.getByText(/na mapie nikt po kontakcie/)).toHaveAttribute(
      "title",
      expect.stringContaining("Nic nie jest blokowane"),
    );
    expect(mismatch.getByText("0 z 4")).toBeInTheDocument();
    expect(mismatch.getByText("w kolejce: 3 osoby")).toBeInTheDocument();
    // Ten sam etap z kontaktem na mapie nie dostaje podpowiedzi.
    const fine = within(rowOf("Firma Kos"));
    expect(fine.getByText("2 z 4")).toBeInTheDocument();
    expect(fine.queryByText(/nikt po kontakcie/)).not.toBeInTheDocument();
  });

  it("klient NEXUSA ma oznaczenie i prowadzi do Delivery Leada", () => {
    render(<FactoryAccountsTable items={items} accounts={facts} known={new Map()} knownState="ready" />);
    const client = within(rowOf("Firma Czyż"));
    expect(client.getByText("Klient NEXUSA")).toBeInTheDocument();
    expect(client.getByText("Uzgodnij z DL: Lider Dostaw")).toBeInTheDocument();
    expect(within(rowOf("Firma Sowa")).queryByText("Klient NEXUSA")).not.toBeInTheDocument();
  });

  it("liczniki z bazy: liczba prowadzi do „Kto ich zna”, zero zostaje zerem", () => {
    const counts = new Map([
      [10, known(10, 49, 114)],
      [20, known(20, 0, 0)],
    ]);
    render(<FactoryAccountsTable items={items} accounts={facts} known={counts} knownState="ready" />);
    expect(screen.getByRole("link", { name: "Kto ich zna: Firma Sowa" })).toHaveAttribute(
      "href",
      "/sales/companies/10?tab=people",
    );
    expect(within(rowOf("Firma Sowa")).getByText("114")).toBeInTheDocument();
    expect(within(rowOf("Firma Kos")).getAllByText("0")).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Kto ich zna: Firma Kos" })).not.toBeInTheDocument();
  });

  it("awaria liczników nie udaje zer", () => {
    const { rerender } = render(
      <FactoryAccountsTable items={items} accounts={null} known={new Map()} knownState="error" />,
    );
    const row = within(rowOf("Firma Sowa"));
    expect(row.queryByText(/ z /)).not.toBeInTheDocument();
    expect(row.queryByText("0")).not.toBeInTheDocument();
    expect(row.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    rerender(<FactoryAccountsTable items={items} accounts={facts} known={new Map()} knownState="loading" />);
    expect(within(rowOf("Firma Sowa")).getAllByText("…")).toHaveLength(2);
  });
});

describe("kolejka osób", () => {
  const props = { ownerId: null, ownerDenied: false, canEdit: true, search: "", known: new Map<number, KnownCounts>() };

  it("pusty stan pokazuje się tylko po udanym odczycie", () => {
    queueQuery.mockReturnValue(failure());
    const { unmount } = render(<FactoryQueue {...props} />);
    expect(screen.getByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText("Nikt nie czeka na pierwszy kontakt")).not.toBeInTheDocument();
    unmount();

    // Przerwa między ponowieniami: nie ładuje się, nie ma błędu i nie ma danych.
    queueQuery.mockReturnValue({ data: undefined, isLoading: false, isSuccess: false, error: null, refetch: vi.fn() });
    const between = render(<FactoryQueue {...props} />);
    expect(screen.getByText("Wczytywanie kolejki…")).toBeInTheDocument();
    expect(screen.queryByText("Nikt nie czeka na pierwszy kontakt")).not.toBeInTheDocument();
    between.unmount();

    queueQuery.mockReturnValue(success(queueData([])));
    render(<FactoryQueue {...props} />);
    expect(screen.getByText("Nikt nie czeka na pierwszy kontakt")).toBeInTheDocument();
  });

  it("pokazuje poziom 1 i 2, a niższe poziomy dopiero po rozwinięciu", () => {
    queueQuery.mockReturnValue(
      success(queueData([person("Prezes Testowy", 1), person("Dyrektor Testowy", 2)], [person("Tester Testowy", 4)])),
    );
    render(<FactoryQueue {...props} known={new Map([[310, known(310, 12, 30)]])} />);

    expect(screen.getByRole("button", { name: "Zapisz kontakt: Prezes Testowy" })).toBeInTheDocument();
    expect(screen.getByText(/Poziom 2 · Dyrektorzy · telefon · z bazy pracuje tam teraz 12 · kiedyś 30/)).toBeInTheDocument();
    expect(screen.getByText(/nie daje prawa do zimnego kontaktu/)).toBeInTheDocument();
    expect(screen.queryByText("Tester Testowy")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Kto ich zna: Firma Sowa" })[0]).toHaveAttribute(
      "href",
      "/sales/companies/310?tab=people",
    );

    const toggle = screen.getByRole("button", { name: /Niższe poziomy .* 1 osoba bez kontaktu/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Tester Testowy")).toBeInTheDocument();
  });

  it("„Zapisz kontakt” otwiera okno osoby z mapy; sam podgląd go nie ma", () => {
    queueQuery.mockReturnValue(success(queueData([person("Prezes Testowy", 1)])));
    const { unmount } = render(<FactoryQueue {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz kontakt: Prezes Testowy" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Poprawka: Prezes Testowy (szansa 31)");
    unmount();

    render(<FactoryQueue {...props} canEdit={false} />);
    expect(screen.getByText("Prezes Testowy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zapisz kontakt/ })).not.toBeInTheDocument();
  });

  it("klient NEXUSA w kolejce prowadzi do Delivery Leada", () => {
    queueQuery.mockReturnValue(
      success(queueData([person("Prezes Testowy", 1, { client: { name: "Sowa S.A.", delivery_lead: null } })])),
    );
    render(<FactoryQueue {...props} />);
    expect(screen.getByText("Klient NEXUSA")).toBeInTheDocument();
    expect(screen.getByText("Klient bez Delivery Leada: zgłoś do Heada")).toBeInTheDocument();
  });
});

describe("przełącznik Wszystkie / Kolejka", () => {
  const items = [opportunity(1, "Firma Sowa", "Pierwszy kontakt")];
  const view = { items, currentUserId: 1, archived: false, search: "" };

  it("zapisuje wybór w adresie i pokazuje sumę kont", () => {
    accountsQuery.mockReturnValue(success([account(1, { map_contacted: 1, top_contacted: 1 })]));
    render(<FactoriesView {...view} ownerId={null} canEdit />);
    expect(screen.getByText("1 konto · 4 osoby na mapach · po kontakcie 1 (25%) · poziom 1 i 2: 1 z 3")).toBeInTheDocument();
    expect(queueQuery).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "Kolejka" }));
    expect(replaceUrl).toHaveBeenCalledWith(expect.stringContaining("kolejka=1"));
  });

  it("kolejka jest domyślnie własna, a cudzą otwiera filtr opiekuna u konta z edycją", () => {
    searchParams = new URLSearchParams("kolejka=1");
    const { unmount } = render(<FactoriesView {...view} ownerId={null} canEdit />);
    expect(queueQuery).toHaveBeenLastCalledWith(null);
    unmount();
    // „Moje” to ta sama własna kolejka, bez parametru opiekuna.
    const mine = render(<FactoriesView {...view} ownerId={1} canEdit />);
    expect(queueQuery).toHaveBeenLastCalledWith(null);
    mine.unmount();
    const other = render(<FactoriesView {...view} ownerId={7} canEdit />);
    expect(queueQuery).toHaveBeenLastCalledWith(7);
    expect(screen.queryByText(/Kolejkę innej osoby otwiera/)).not.toBeInTheDocument();
    other.unmount();
    // Konto z samym podglądem nie pyta o cudzą kolejkę i dostaje wyjaśnienie.
    render(<FactoriesView {...view} ownerId={7} canEdit={false} />);
    expect(queueQuery).toHaveBeenLastCalledWith(null);
    expect(
      screen.getByText(/Kolejkę innej osoby otwiera konto z uprawnieniem „Sprzedaż: prowadzenie szans i kartoteki firm”/),
    ).toBeInTheDocument();
  });

  it("awaria liczników z bazy ma własny komunikat i ponowienie", () => {
    const refetch = vi.fn();
    knownQuery.mockReturnValue({ ...failure(), refetch });
    render(<FactoriesView {...view} ownerId={null} canEdit />);
    const alert = screen.getByText(/Nie udało się policzyć osób z bazy/);
    fireEvent.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Firma Sowa" })).toBeInTheDocument();
  });
});

describe("Szanse: lejek Fabryki IT startuje od listy kont", () => {
  const loaded = (pipelineId: number) =>
    success({ items: [opportunity(1, "Firma Sowa", "Pierwszy kontakt", { pipeline_id: pipelineId })], total: 1 });

  it("bez parametru widoku Fabryki IT pokazują listę, a `view=board` tablicę", () => {
    opportunitiesQuery.mockReturnValue(loaded(2));
    accountsQuery.mockReturnValue(success([account(1, { stage_mismatch: true })]));
    searchParams = new URLSearchParams("lejek=2");
    const { unmount } = render(<OpportunitiesView />);
    expect(screen.getByRole("columnheader", { name: "Mapa po kontakcie" })).toBeInTheDocument();
    expect(screen.getByText(/na mapie nikt po kontakcie/)).toBeInTheDocument();
    expect(screen.queryByText("Tablica etapów")).not.toBeInTheDocument();
    // Wybór tablicy trzeba zapisać w adresie, bo nie jest tu domyślny.
    fireEvent.click(screen.getByRole("radio", { name: "Tablica" }));
    expect(replaceUrl).toHaveBeenCalledWith(expect.stringContaining("view=board"));
    unmount();

    searchParams = new URLSearchParams("lejek=2&view=board");
    render(<OpportunitiesView />);
    expect(screen.getByText("Tablica etapów")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Mapa po kontakcie" })).not.toBeInTheDocument();
  });

  it("pozostałe lejki zostają przy tablicy i zwykłej liście", () => {
    opportunitiesQuery.mockReturnValue(loaded(1));
    const { unmount } = render(<OpportunitiesView />);
    expect(screen.getByText("Tablica etapów")).toBeInTheDocument();
    unmount();
    searchParams = new URLSearchParams("view=list");
    render(<OpportunitiesView />);
    expect(screen.getByRole("columnheader", { name: "Szansa" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Mapa po kontakcie" })).not.toBeInTheDocument();
    expect(accountsQuery).not.toHaveBeenCalled();
  });
});
