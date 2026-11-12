/**
 * Mapy decydentów od bota: „Znajdź decydentów (bot)”, lista wyników w Leadach
 * i przegląd wyniku na ekranie listy z researchu. Dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BotPeopleAcceptInput,
  BotPeopleAccepted,
  BotPeopleList as BotPeopleListData,
  BotPeoplePreview,
} from "@/lib/api/sales-bot-people";
import type { ResearchCompany, ResearchRow } from "@/lib/api/sales-research-import";

const startMutate = vi.fn();
const previewMutate = vi.fn();
const acceptBot = vi.fn<(input: BotPeopleAcceptInput) => Promise<BotPeopleAccepted>>();
const acceptFile = vi.fn();
const rejectBot = vi.fn();
const askConfirm = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn() };
let pending: { isPending: boolean; isError: boolean; isSuccess: boolean; data?: BotPeopleListData } = {
  isPending: false,
  isError: false,
  isSuccess: true,
};

vi.mock("@/lib/api/sales-bot-people", () => ({
  useBotPeoplePending: () => ({ ...pending, refetch: vi.fn() }),
  useStartBotPeople: () => ({ mutate: startMutate, isPending: false }),
  useBotPeoplePreview: () => ({ mutate: previewMutate, reset: vi.fn(), isPending: false, isError: false }),
  useAcceptBotPeople: () => ({ mutateAsync: acceptBot, isPending: false }),
  useRejectBotPeople: () => ({ mutateAsync: rejectBot, isPending: false }),
}));
vi.mock("@/lib/api/sales-research-import", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-research-import")>()),
  usePreviewResearchList: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false }),
  useAcceptResearchPeople: () => ({ mutateAsync: acceptFile, isPending: false }),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useOwnerCandidates: () => ({ data: [{ id: 1, name: "Zalogowana Osoba" }] }),
}));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    ariaLabel,
    value,
    onValueChange,
    options,
  }: {
    ariaLabel?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: readonly { value: string; label: string }[];
  }) => (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
      <option value="" />
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number; name: string } }) => unknown) =>
    selector({ user: { id: 1, name: "Zalogowana Osoba" } }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { BotPeopleAction } from "../bot-people/BotPeopleAction";
import { BotPeopleList } from "../bot-people/BotPeopleList";
import { sourceLine } from "../decision-map-labels";
import { ResearchImport } from "../research-import/ResearchImport";

const LIST: BotPeopleListData = {
  enabled: true,
  items: [
    {
      id: 7,
      company: { id: 40, name: "Fabryka Testowa" },
      status: "partial",
      people: 5,
      open: 3,
      created_at: "2026-11-12T08:05:00Z",
    },
  ],
  running_company_ids: [41],
};

const COMPANY: ResearchCompany = {
  key: "fabryka testowa",
  name: "Fabryka Testowa",
  state: "account",
  company_id: 40,
  client: null,
  cards: [
    {
      id: 40,
      name: "Fabryka Testowa",
      exact: true,
      contacts: 0,
      account: {
        opportunity_id: 400,
        title: "Fabryka Testowa",
        stage_name: "Mapa decyzyjna w trakcie",
        status: "open",
        map_total: 1,
        map_contacted: 0,
      },
      archived_account: false,
      client: null,
      blocked: false,
      known_current: null,
      known_past: null,
    },
  ],
};

const row = (line: number, name: string, over: Partial<ResearchRow> = {}): ResearchRow => ({
  line,
  company_key: COMPANY.key,
  company: COMPANY.name,
  name,
  role_in_company: "Head of Data",
  email: null,
  phone: null,
  linkedin_url: null,
  source_url: "https://firma.example/zespol",
  domain: null,
  notes: null,
  confidence: "to_verify",
  decision_level: 2,
  warnings: [],
  person: "new",
  on_map_opportunity_id: null,
  ...over,
});

const PREVIEW: BotPeoplePreview = {
  result_id: 7,
  company: { id: 40, name: "Fabryka Testowa" },
  status: "new",
  preview: {
    companies: [COMPANY],
    rows: [
      row(1, "Anna Przykładowa", { email: "anna@firma.example" }),
      row(2, "Ewa Testowa", { warnings: ["pominięto e-mail (bez źródła albo niepełny)"] }),
    ],
    skipped: [],
    known_failed: false,
    known_truncated: false,
  },
  published: { "1": "2026-10-01", "2": null },
  decided: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  pending = { isPending: false, isError: false, isSuccess: true, data: LIST };
});

describe("lista osób od bota", () => {
  it("pokazuje wyniki do przeglądu i otwiera wskazany", () => {
    const onOpen = vi.fn();
    render(<BotPeopleList opening={null} error={null} onOpen={onOpen} />);
    expect(screen.getByText("Fabryka Testowa")).toBeInTheDocument();
    expect(screen.getByText("3 osoby")).toBeInTheDocument();
    expect(screen.getByText("z 5, część już dodana")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Przejrzyj osoby od bota: Fabryka Testowa" }));
    expect(onOpen).toHaveBeenCalledWith(7);
  });

  it("z wyłączonymi zadaniami bota nic nie pokazuje", () => {
    pending = { ...pending, data: { enabled: false, items: [], running_company_ids: [] } };
    const { container } = render(<BotPeopleList opening={null} error={null} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria zapytania nie wygląda jak pusta lista", () => {
    pending = { isPending: false, isError: true, isSuccess: false };
    render(<BotPeopleList opening={null} error={null} onOpen={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać osób od bota.");
    expect(screen.queryByText("Żaden wynik bota nie czeka na przegląd.")).toBeNull();
  });
});

describe("„Znajdź decydentów (bot)”", () => {
  it("zleca bieg dla firmy", () => {
    render(<BotPeopleAction companyId={50} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: /Znajdź decydentów \(bot\)/ }));
    expect(startMutate).toHaveBeenCalledWith(50, expect.anything());
  });

  it("czeka, gdy bieg dla firmy ruszył w ostatniej dobie", () => {
    render(<BotPeopleAction companyId={41} canEdit />);
    const button = screen.getByRole("button", { name: /Znajdź decydentów/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", expect.stringContaining("24 godzinach"));
  });

  it("wynik do przeglądu zastępuje przycisk odnośnikiem", () => {
    render(<BotPeopleAction companyId={40} canEdit />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("link", { name: "Przejrzyj: 3 osoby" })).toHaveAttribute("href", "/sales/leads?osoby=7");
  });

  it("konto bez edycji nie ma przycisku", () => {
    const { container } = render(<BotPeopleAction companyId={50} canEdit={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("przegląd wyniku bota", () => {
  const openReview = () => {
    previewMutate.mockImplementation((_id: number, options: { onSuccess: (data: BotPeoplePreview) => void }) =>
      options.onSuccess(PREVIEW),
    );
    render(<ResearchImport botResultId={7} />);
  };
  const rowOf = (name: string) => within(screen.getByText(new RegExp(name)).closest("tr") as HTMLElement);

  it("wejście z plakietki otwiera ten sam ekran bez pola „Skąd lista”", () => {
    openReview();
    expect(previewMutate).toHaveBeenCalledWith(7, expect.anything());
    expect(screen.getByText("Osoby od bota")).toBeInTheDocument();
    expect(screen.queryByLabelText("Skąd lista")).toBeNull();
    expect(screen.queryByRole("button", { name: /Dodaj pewne do map/ })).toBeNull();
    expect(rowOf("Anna Przykładowa").getByRole("link", { name: "źródło" })).toHaveAttribute(
      "href",
      "https://firma.example/zespol",
    );
    expect(rowOf("Ewa Testowa").getByText("pominięto e-mail (bez źródła albo niepełny)")).toBeInTheDocument();
  });

  it("zapis wysyła tylko wiersz, poziom i kartę", async () => {
    acceptBot.mockResolvedValue({
      status: "partial",
      outcomes: [
        {
          line: 1,
          result: "added",
          detail: null,
          company_id: 40,
          opportunity_id: 400,
          created_company: false,
          created_account: false,
          client: null,
        },
      ],
      added: 1,
      created_companies: 0,
      created_accounts: 0,
    });
    openReview();
    fireEvent.change(screen.getByLabelText("Poziom decyzji: Anna Przykładowa"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do mapy: Anna Przykładowa" }));

    await waitFor(() => expect(rowOf("Anna Przykładowa").getByText("Dodano")).toBeInTheDocument());
    expect(acceptBot).toHaveBeenCalledWith({
      owner_user_id: null,
      people: [{ line: 1, decision_level: 1, company_id: 40 }],
    });
    expect(acceptFile).not.toHaveBeenCalled();
  });

  it("„Odrzuć resztę” pyta i odrzuca wynik", async () => {
    askConfirm.mockResolvedValue(true);
    rejectBot.mockResolvedValue({});
    openReview();
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć resztę" }));
    await waitFor(() => expect(rejectBot).toHaveBeenCalledWith(7));
  });
});

describe("źródło przy osobie od bota", () => {
  it("linia źródła ma datę publikacji", () => {
    expect(
      sourceLine({
        source_label: "Grok Bot",
        source_added_at: "2026-11-12",
        source_published_at: "2026-10-01",
        source_confidence: "to_verify",
      }),
    ).toMatch(/^źródło: Grok Bot · opublikowane .+ · na mapie od .+ · do weryfikacji$/);
  });
});
