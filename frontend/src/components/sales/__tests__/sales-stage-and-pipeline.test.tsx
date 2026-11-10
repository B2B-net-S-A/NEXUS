/**
 * Karta szansy zapisuje etap, który wybrał użytkownik (nie zawsze „Przegrana”),
 * a „+ Szansa” zakłada szansę w lejku oglądanej tablicy.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OpportunityDetail, Pipeline, Ref, Stage } from "@/lib/api/sales";

const move = vi.fn();
const create = vi.fn();
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
  useOpportunities: () => ({
    data: { items: [], total: 0 },
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

import { OpportunitiesView } from "../OpportunitiesView";
import { OpportunityCard } from "../OpportunityCard";

beforeEach(() => {
  move.mockClear();
  create.mockClear();
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
