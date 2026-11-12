/**
 * Karta szansy zapisuje etap, który wybrał użytkownik (nie zawsze „Przegrana”),
 * a „+ Szansa” zakłada szansę w lejku oglądanej tablicy.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OpportunityDetail, Pipeline, Ref, Stage } from "@/lib/api/sales";

const move = vi.fn();
const create = vi.fn();
const createActivity = vi.fn();
const logCall = vi.fn();
const opportunitiesParams = vi.fn();
const bulk = vi.fn();
let opportunityItems: object[] = [];
let searchParams = new URLSearchParams();
let pipelinesData: Pipeline[] | undefined;

const stage = (id: number, key: string, name: string, outcome: Stage["outcome"]): Stage => ({
  id,
  key,
  name,
  position: id,
  probability: 0,
  outcome,
  qualifies: false,
  color: null,
});

const SALES_STAGES = [
  stage(1, "lead", "Lead", "open"),
  stage(4, "offer-sent", "Oferta wysłana", "open"),
  stage(5, "not-qualified", "Niezakwalifikowany", "lost"),
  stage(6, "won", "Wygrana", "won"),
  stage(7, "lost", "Przegrana", "lost"),
];

const PIPELINES = [
  { id: 1, key: "sales", name: "Sprzedaż", is_default: true, stages: SALES_STAGES },
  {
    id: 2,
    key: "atlas-it-factories",
    name: "Fabryki IT",
    is_default: false,
    stages: [stage(21, "prospecting", "Rozpoznanie", "open")],
  },
] as unknown as Pipeline[];

const OPPORTUNITY = {
  id: 11,
  title: "Zespół QA",
  pipeline_id: 1,
  status: "open",
  archived_at: null,
  company: { id: 3, name: "Firma" },
  stage: SALES_STAGES[0],
  contacts: [],
  atlas_motion: null,
  roles: [],
  value: null,
  currency: "PLN",
} as unknown as OpportunityDetail;

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useOpportunity: () => ({ data: OPPORTUNITY, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() }),
  useCompanyBriefing: () => ({ data: undefined, isSuccess: false, isError: false }),
  usePipelines: () => ({ data: pipelinesData, isLoading: false, error: null, isSuccess: pipelinesData !== undefined }),
  useMoveOpportunity: () => ({ mutate: move, isPending: false }),
  useArchiveOpportunity: () => ({ mutate: vi.fn(), isPending: false }),
  useSalesCompany: () => ({ data: undefined, isSuccess: false }),
  useSalesContacts: () => ({ data: undefined, isSuccess: false }),
  useCreateActivity: () => ({ mutate: createActivity, isPending: false }),
  useLogCall: () => ({ mutate: logCall, isPending: false }),
  useBulkOpportunities: () => ({ mutate: bulk, isPending: false }),
  useOwnerCandidates: () => ({ isSuccess: true, isError: false, data: [], refetch: vi.fn() }),
  useOpportunities: (params: unknown) => (opportunitiesParams(params), {
    data: { items: opportunityItems, total: opportunityItems.length },
    isLoading: false,
    error: null,
    isSuccess: true,
    refetch: vi.fn(),
  }),
  useCreateOpportunity: () => ({ mutate: create, isPending: false }),
  useUpdateOpportunity: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => vi.fn() }));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => true,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } }) => unknown) => selector({ user: { id: 1 } }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: vi.fn(), confirmDialog: null }),
}));
vi.mock("../useOwnerFilterOptions", () => ({ useOwnerFilterOptions: () => [] }));
vi.mock("../SalesSelect", () => ({
  ANY: "__any__",
  SalesSelect: ({
    id,
    ariaLabel,
    value,
    onValueChange,
    options,
  }: {
    id?: string;
    ariaLabel?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: readonly { value: string; label: string }[];
  }) => (
    <select id={id} aria-label={ariaLabel ?? id} value={value} onChange={(event) => onValueChange(event.target.value)}>
      <option value="">—</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("../CompanyPicker", () => ({
  CompanyPicker: ({ onChange }: { onChange: (company: Ref) => void }) => (
    <button type="button" onClick={() => onChange({ id: 7, name: "Firma z listy" })}>
      Wybierz firmę
    </button>
  ),
}));
vi.mock("../SalesShell", () => ({
  SalesShell: ({ actions, children }: { actions?: React.ReactNode; children: React.ReactNode }) => (
    <div>
      {actions}
      {children}
    </div>
  ),
}));
vi.mock("../OpportunityTimeline", () => ({ OpportunityTimelineCard: () => null }));
vi.mock("../FilesSection", () => ({ FilesSection: () => null }));
vi.mock("../LinkClientDialog", () => ({ LinkClientDialog: () => null }));
vi.mock("../OpportunityContacts", () => ({ OpportunityContacts: () => null }));
vi.mock("../OpportunityHistory", () => ({ OpportunityHistory: () => null }));
vi.mock("../handoff/OpportunityHandoff", () => ({ OpportunityHandoff: () => null }));
vi.mock("@/lib/api/sales-handoffs", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-handoffs")>()),
  useOpportunityHandoff: () => ({ isSuccess: true, data: null }),
}));
vi.mock("../WhoWeKnowPanel", () => ({ WhoWeKnowPanel: () => null }));
vi.mock("../SalesMotionPanel", () => ({ SalesMotionPanel: () => null }));
// Lejek Fabryki IT otwiera listę kont z własnymi zapytaniami; tu liczy się pasek nad nią.
vi.mock("../factories/FactoriesView", () => ({ FactoriesView: () => null }));

import { OpportunitiesView } from "../OpportunitiesView";
import { OpportunityCard } from "../OpportunityCard";

beforeEach(() => {
  move.mockClear();
  create.mockClear();
  createActivity.mockReset();
  logCall.mockReset();
  opportunitiesParams.mockClear();
  bulk.mockReset();
  opportunityItems = [];
  searchParams = new URLSearchParams();
  pipelinesData = PIPELINES;
});

describe("karta szansy: etap z wynikiem przegranej", () => {
  const save = () => fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
  const pickStage = (name: string) => {
    const select = screen.getByLabelText("Etap");
    const option = Array.from(select.querySelectorAll("option")).find((item) => item.textContent === name);
    fireEvent.change(select, { target: { value: option?.value } });
  };

  it("„Niezakwalifikowany” zapisuje ten etap z powodem", () => {
    render(<OpportunityCard opportunityId={11} />);
    pickStage("Niezakwalifikowany");
    expect(move).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("Niezakwalifikowany");
    fireEvent.change(screen.getByLabelText("Powód (opcjonalnie)"), { target: { value: "brak budżetu" } });
    save();
    expect(move).toHaveBeenCalledTimes(1);
    expect(move.mock.calls[0][0]).toEqual({ id: 11, stage_id: 5, lost_reason: "brak budżetu" });
  });

  it("etap „Przegrana” z listy zapisuje przegraną", () => {
    render(<OpportunityCard opportunityId={11} />);
    pickStage("Przegrana");
    save();
    expect(move.mock.calls[0][0]).toMatchObject({ id: 11, stage_id: 7 });
  });

  it("przycisk „Przegrana” zapisuje przegraną, także po porzuceniu innego etapu", () => {
    render(<OpportunityCard opportunityId={11} />);
    pickStage("Niezakwalifikowany");
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(move).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Przegrana" }));
    save();
    expect(move.mock.calls[0][0]).toMatchObject({ id: 11, stage_id: 7 });
  });
});

describe("karta szansy: pasek etapów", () => {
  it("klik w etap na pasku przenosi szansę jak przeciągnięcie na tablicy", () => {
    render(<OpportunityCard opportunityId={11} />);
    const strip = within(screen.getByRole("group", { name: "Etap szansy" }));
    expect(strip.getByRole("button", { name: "Lead" })).toBeDisabled();
    fireEvent.click(strip.getByRole("button", { name: "Oferta wysłana" }));
    expect(move.mock.calls[0][0]).toEqual({ id: 11, stage_id: 4, lost_reason: undefined });
  });

  it("pasek pokazuje tylko otwarte etapy: wygraną i przegraną zamyka się przyciskami", () => {
    render(<OpportunityCard opportunityId={11} />);
    const strip = within(screen.getByRole("group", { name: "Etap szansy" }));
    expect(strip.queryByRole("button", { name: "Wygrana" })).toBeNull();
    expect(strip.queryByRole("button", { name: "Przegrana" })).toBeNull();
  });
});

describe("karta szansy: krok po rozmowie zapisuje się sam", () => {
  const logNoAnswer = () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess({}));
    render(<OpportunityCard opportunityId={11} />);
    fireEvent.click(screen.getByRole("button", { name: "Zaloguj rozmowę" }));
    fireEvent.click(screen.getByRole("button", { name: "Nie odebrał" }));
  };

  it("wynik zapisuje krok z podpowiedzi bez okna „Co dalej”", () => {
    createActivity.mockImplementation((_input, { onSuccess }) => onSuccess());
    logNoAnswer();
    expect(logCall.mock.calls[0][0]).toMatchObject({ opportunity_id: 11, outcome: "no_answer" });
    expect(createActivity.mock.calls[0][0]).toMatchObject({
      kind: "task",
      subject: "Zadzwonić ponownie",
      opportunity_id: 11,
      company_id: null,
    });
    expect(screen.queryByText("Co dalej i kiedy")).toBeNull();
  });

  it("gdy krok się nie zapisze, wraca okno „Co dalej”, żeby go nie zgubić", () => {
    createActivity.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    logNoAnswer();
    expect(screen.getByText("Co dalej i kiedy")).toBeTruthy();
  });
});

describe("Szanse: domyślnie „Moje”", () => {
  const owner = () => opportunitiesParams.mock.calls.at(-1)?.[0]?.owner_id;

  it("osoba z edycją wchodzi od razu na swoje szanse", () => {
    render(<OpportunitiesView />);
    expect(owner()).toBe(1);
    expect((screen.getByLabelText("Opiekun") as HTMLSelectElement).value).toBe("me");
  });

  it("„Każdy opiekun” zostaje wybrany w adresie jako mine=0", () => {
    searchParams = new URLSearchParams("mine=0");
    render(<OpportunitiesView />);
    expect(owner()).toBeNull();
  });

  it("konkretny opiekun z adresu wygrywa z domyślnym „Moje”", () => {
    searchParams = new URLSearchParams("opiekun=5");
    render(<OpportunitiesView />);
    expect(owner()).toBe(5);
  });
});

describe("Szanse: lista z zaznaczaniem", () => {
  const item = (id: number, title: string) => ({
    ...OPPORTUNITY,
    id,
    title,
    status: "open",
    owner: { id: 1, name: "Handlowiec" },
    last_touch_at: null,
    service_line: null,
    next_step: null,
    overdue_step: null,
  });

  it("„Zaznacz wszystkie” pokazuje pasek akcji dla widocznych szans", () => {
    opportunityItems = [item(41, "Zespół QA"), item(42, "Zespół DevOps")];
    searchParams = new URLSearchParams("view=list");
    render(<OpportunitiesView />);
    expect(screen.queryByRole("region", { name: "Zaznaczone szanse" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz wszystkie widoczne" }));
    expect(screen.getByRole("region", { name: "Zaznaczone szanse" })).toHaveTextContent("Zaznaczone: 2 szanse");
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz Zespół QA" }));
    expect(screen.getByRole("region", { name: "Zaznaczone szanse" })).toHaveTextContent("Zaznaczone: 1 szansę");
    // Lejek ma etap „lost”, więc jest też zamknięcie.
    expect(screen.getByRole("button", { name: "Zamknij z powodem" })).toBeInTheDocument();
  });

  const region = () => screen.queryByRole("region", { name: "Zaznaczone szanse" });

  it("wpisanie szukanej frazy zdejmuje zaznaczenie, więc akcja nie trafia w niewidoczne szanse", () => {
    opportunityItems = [item(41, "Zespół QA"), item(42, "Zespół DevOps")];
    searchParams = new URLSearchParams("view=list");
    render(<OpportunitiesView />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz wszystkie widoczne" }));
    expect(region()).toHaveTextContent("Zaznaczone: 2 szanse");
    fireEvent.change(screen.getByLabelText("Szukaj szansy, firmy albo NIP"), { target: { value: "Wedel" } });
    expect(region()).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Zespół QA" })).not.toBeChecked();
  });

  it.each([
    ["opiekun", "view=list&mine=0"],
    ["lejek", "view=list&lejek=3"],
    ["bez kroku", "view=list&bez_kroku=1"],
    ["czeka na odpowiedź", "view=list&czeka=1"],
    ["bez ruchu", "view=list&bezruchu=1"],
  ])("zmiana filtra „%s” zdejmuje zaznaczenie", (_name, next) => {
    // Szanse przechodzą przez każdy z filtrów, więc po zmianie lista nadal je pokazuje.
    const waiting = { waiting_for_reply: true, last_touch_at: "2026-01-02T10:00:00Z" };
    opportunityItems = [{ ...item(41, "Zespół QA"), ...waiting }, { ...item(42, "Zespół DevOps"), ...waiting }];
    pipelinesData = [
      ...PIPELINES,
      { id: 3, key: "tenders", name: "Przetargi", is_default: false, stages: SALES_STAGES },
    ] as unknown as Pipeline[];
    searchParams = new URLSearchParams("view=list");
    const { rerender } = render(<OpportunitiesView />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz wszystkie widoczne" }));
    expect(region()).not.toBeNull();
    searchParams = new URLSearchParams(next);
    rerender(<OpportunitiesView />);
    expect(screen.getByRole("checkbox", { name: "Zaznacz Zespół QA" })).not.toBeChecked();
    expect(region()).toBeNull();
  });

  it("zmiana widoku na tablicę i z powrotem nie przywraca starego zaznaczenia", () => {
    opportunityItems = [item(41, "Zespół QA")];
    searchParams = new URLSearchParams("view=list");
    const { rerender } = render(<OpportunitiesView />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz Zespół QA" }));
    searchParams = new URLSearchParams("view=board");
    rerender(<OpportunitiesView />);
    searchParams = new URLSearchParams("view=list");
    rerender(<OpportunitiesView />);
    expect(region()).toBeNull();
  });

  it("pasek liczy i wysyła tylko zaznaczone szanse, które nadal są na liście", () => {
    bulk.mockImplementation((_input, { onSuccess }) => onSuccess({ done: [42], skipped: [] }));
    opportunityItems = [item(41, "Zespół QA"), item(42, "Zespół DevOps")];
    searchParams = new URLSearchParams("view=list");
    const { rerender } = render(<OpportunitiesView />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz wszystkie widoczne" }));
    // Szansa 41 znika z listy (np. zamknął ją ktoś inny, lista się odświeżyła).
    opportunityItems = [item(42, "Zespół DevOps")];
    rerender(<OpportunitiesView />);
    expect(region()).toHaveTextContent("Zaznaczone: 1 szansę");
    expect(screen.getByRole("checkbox", { name: "Zaznacz wszystkie widoczne" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj krok" }));
    fireEvent.click(screen.getByRole("button", { name: "Jutro" }));
    expect(bulk.mock.calls[0][0]).toMatchObject({ ids: [42], action: "plan" });
  });

  it("archiwum nie ma zaznaczania", () => {
    opportunityItems = [item(41, "Zespół QA")];
    searchParams = new URLSearchParams("view=list&archiwum=1");
    render(<OpportunitiesView />);
    expect(screen.queryByRole("checkbox", { name: "Zaznacz wszystkie widoczne" })).toBeNull();
  });
});

describe("„+ Szansa” na tablicy", () => {
  const addOpportunity = () => {
    fireEvent.click(screen.getByRole("button", { name: /Szansa/ }));
    fireEvent.click(screen.getByRole("button", { name: "Wybierz firmę" }));
    fireEvent.change(screen.getByLabelText("Nazwa szansy"), { target: { value: "Fabryka QA" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj szansę" }));
  };

  it("zakłada szansę w lejku oglądanej tablicy", () => {
    searchParams = new URLSearchParams("lejek=2");
    render(<OpportunitiesView />);
    addOpportunity();
    expect(create.mock.calls[0][0]).toMatchObject({ company_id: 7, title: "Fabryka QA", pipeline_id: 2 });
  });

  it("bez wyboru w adresie zakłada w lejku domyślnym", () => {
    render(<OpportunitiesView />);
    addOpportunity();
    expect(create.mock.calls[0][0]).toMatchObject({ pipeline_id: 1 });
  });

  it("przed wczytaniem lejków nie da się założyć szansy", () => {
    searchParams = new URLSearchParams("lejek=2");
    pipelinesData = undefined;
    render(<OpportunitiesView />);
    expect(screen.getByRole("button", { name: /Szansa/ })).toBeDisabled();
  });
});
