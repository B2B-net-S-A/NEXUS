/**
 * Leady → „Lista z researchu”: wgranie pliku, przegląd wierszy (stan firmy w NEXUSIE,
 * wybór karty, poziom decyzji) i akceptacja do map Fabryk IT. Dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionMapEntry } from "@/lib/api/sales";
import type {
  ResearchAccepted,
  ResearchAcceptInput,
  ResearchCard,
  ResearchCompany,
  ResearchOutcome,
  ResearchPreview,
  ResearchRow,
} from "@/lib/api/sales-research-import";

const previewMutate = vi.fn();
const acceptMutate = vi.fn<(input: ResearchAcceptInput) => Promise<ResearchAccepted>>();
const askConfirm = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn() };
let previewError: Error | null = null;
let canEdit = true;
let signalsOn = false;

interface SelectMockProps {
  id?: string;
  ariaLabel?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  anyLabel?: string;
  disabled?: boolean;
}

// Radix Select nie otwiera listy w jsdom: natywne pole z tymi samymi opcjami.
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({ id, ariaLabel, value, onValueChange, options, anyLabel, disabled }: SelectMockProps) => (
    <select
      id={id}
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {anyLabel !== undefined && <option value="">{anyLabel}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("@/lib/api/sales-research-import", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-research-import")>()),
  usePreviewResearchList: () => ({
    mutate: previewMutate,
    reset: vi.fn(),
    isPending: false,
    isError: previewError !== null,
    error: previewError,
  }),
  useAcceptResearchPeople: () => ({ mutateAsync: acceptMutate, isPending: false }),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useOwnerCandidates: () => ({
    data: [
      { id: 1, name: "Zalogowana Osoba" },
      { id: 2, name: "Kolega Testowy" },
    ],
  }),
  useLeads: () => ({
    data: { items: [], total: 0, counts: {}, signals_enabled: signalsOn },
    isLoading: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  }),
  useCreateLead: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateLead: () => ({ mutate: vi.fn(), isPending: false }),
  useConvertLead: () => ({ mutate: vi.fn(), isPending: false }),
  useSaveDecisionPerson: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveDecisionPerson: () => ({ mutate: vi.fn(), isPending: false }),
}));
// Osoby od bota mają własny test (`sales-bot-people.test.tsx`); tu zadania bota są wyłączone.
vi.mock("@/lib/api/sales-bot-people", () => ({
  useBotPeoplePending: () => ({
    isPending: false,
    isError: false,
    isSuccess: true,
    data: { enabled: false, items: [], running_company_ids: [] },
  }),
  useBotPeoplePreview: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false }),
  useAcceptBotPeople: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRejectBotPeople: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number; name: string } }) => unknown) =>
    selector({ user: { id: 1, name: "Zalogowana Osoba" } }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/sales/leads",
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("../signals/SignalsInbox", () => ({ SignalsInbox: () => <div>Skrzynka sygnałów</div> }));

import { sourceLine } from "../decision-map-labels";
import { DecisionPersonDialog } from "../DecisionPersonDialog";
import { LeadsView } from "../LeadsView";
import {
  bulkEffect,
  bulkQuestion,
  canCreateCard,
  previewSummary,
  resolveTarget,
  rowPhase,
  sourceFromFile,
} from "../research-import/research-import";
import { ResearchImport } from "../research-import/ResearchImport";

const card = (over: Partial<ResearchCard>): ResearchCard => ({
  id: 1,
  name: "Karta",
  exact: true,
  contacts: 0,
  account: null,
  archived_account: false,
  client: null,
  blocked: false,
  known_current: null,
  known_past: null,
  ...over,
});

const WITH_ACCOUNT: ResearchCompany = {
  key: "zuraw test",
  name: "Żuraw Test",
  state: "account",
  company_id: 10,
  client: null,
  cards: [
    card({
      id: 10,
      name: "Żuraw Test",
      contacts: 5,
      known_current: 7,
      account: {
        opportunity_id: 100,
        title: "Żuraw Test",
        stage_name: "Mapa decyzyjna gotowa",
        status: "open",
        map_total: 3,
        map_contacted: 1,
      },
    }),
  ],
};
const BARE_CARD: ResearchCompany = {
  key: "czapla test",
  name: "Czapla Test",
  state: "card",
  company_id: 20,
  client: null,
  cards: [card({ id: 20, name: "Czapla Test", contacts: 12, known_current: 0, archived_account: true })],
};
const SEVERAL: ResearchCompany = {
  key: "bocian",
  name: "Bocian",
  state: "choose",
  company_id: null,
  client: null,
  cards: [
    card({ id: 30, name: "Bocian", contacts: 2, known_current: 1 }),
    card({
      id: 31,
      name: "Bocian Group",
      exact: false,
      known_current: 4,
      account: {
        opportunity_id: 131,
        title: "Bocian Group",
        stage_name: "Pierwszy kontakt",
        status: "open",
        map_total: 0,
        map_contacted: 0,
      },
    }),
    card({
      id: 32,
      name: "Bocian Polska",
      exact: false,
      client: { name: "Bocian Polska", delivery_lead: "Opiekun Testowy" },
    }),
  ],
};
const MISSING: ResearchCompany = {
  key: "perkoz nowy",
  name: "Perkoz Nowy",
  state: "no_card",
  company_id: null,
  client: null,
  cards: [],
};
const CLIENT: ResearchCompany = {
  key: "klient dudek",
  name: "Klient Dudek",
  state: "client",
  company_id: null,
  client: { name: "Klient Dudek", delivery_lead: "Opiekun Testowy" },
  cards: [],
};

const row = (line: number, company: ResearchCompany, name: string, over: Partial<ResearchRow> = {}): ResearchRow => ({
  line,
  company_key: company.key,
  company: company.name,
  name,
  role_in_company: "Manager",
  email: null,
  phone: null,
  linkedin_url: null,
  source_url: null,
  domain: null,
  notes: null,
  confidence: "confirmed",
  decision_level: 3,
  warnings: [],
  person: "new",
  on_map_opportunity_id: null,
  ...over,
});

const PREVIEW: ResearchPreview = {
  companies: [WITH_ACCOUNT, BARE_CARD, SEVERAL, MISSING, CLIENT],
  rows: [
    row(2, WITH_ACCOUNT, "Jan Fikcyjny", {
      role_in_company: "Head of Data",
      decision_level: 2,
      linkedin_url: "https://linkedin.example/jan",
    }),
    row(3, BARE_CARD, "Ewa Zmyślona", { confidence: "to_verify", warnings: ["pominięto adres e-mail (niepełny)"] }),
    row(4, SEVERAL, "Adam Wymyślony", { role_in_company: "Director", decision_level: 2 }),
    row(5, MISSING, "Olga Zmyślna", { domain: "perkoz.example" }),
    row(6, MISSING, "Piotr Zmyślny"),
    row(7, CLIENT, "Anna Fikcyjna"),
    row(8, WITH_ACCOUNT, "Stary Wpis", { person: "on_map", on_map_opportunity_id: 100 }),
  ],
  skipped: [
    { line: 9, reason: "brak nazwy firmy" },
    { line: 11, reason: "brak nazwy firmy" },
  ],
  known_failed: false,
  known_truncated: false,
};

const outcome = (line: number, over: Partial<ResearchOutcome> = {}): ResearchOutcome => ({
  line,
  result: "added",
  detail: null,
  company_id: 10,
  opportunity_id: 100,
  created_company: false,
  created_account: false,
  client: null,
  ...over,
});

function accepted(outcomes: ResearchOutcome[]): ResearchAccepted {
  const added = outcomes.filter((item) => item.result === "added");
  return {
    outcomes,
    added: added.length,
    created_companies: added.filter((item) => item.created_company).length,
    created_accounts: added.filter((item) => item.created_account).length,
  };
}

function openReview(preview: ResearchPreview = PREVIEW, fileName = "centra-it_lista.csv") {
  previewMutate.mockImplementation((_file: File, options: { onSuccess: (data: ResearchPreview) => void }) =>
    options.onSuccess(preview),
  );
  render(<ResearchImport />);
  const file = new File(["Firma;Osoba"], fileName, { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("Plik z listą osób"), { target: { files: [file] } });
}

const rowOf = (name: string) => {
  const cell = screen.getByText((text) => text.startsWith(name));
  const found = cell.closest("tr");
  if (!found) throw new Error(`Brak wiersza: ${name}`);
  return within(found);
};
const sentPeople = (call = 0) => acceptMutate.mock.calls[call][0].people;

beforeEach(() => {
  previewMutate.mockReset();
  acceptMutate.mockReset();
  askConfirm.mockReset();
  toast.showError.mockReset();
  toast.showSuccess.mockReset();
  previewError = null;
  canEdit = true;
  signalsOn = false;
});

describe("cel wiersza", () => {
  it("firma z kontem, sama karta i brak karty mają cel od razu", () => {
    expect(resolveTarget(WITH_ACCOUNT, undefined, undefined)).toMatchObject({
      kind: "account",
      companyId: 10,
      opportunityId: 100,
    });
    expect(resolveTarget(BARE_CARD, undefined, undefined)).toMatchObject({ kind: "card", companyId: 20 });
    expect(resolveTarget(MISSING, undefined, undefined)).toMatchObject({ kind: "new_company", companyId: null });
  });

  it("kilka kart czeka na wybór, a karty klienta wybrać się nie da", () => {
    expect(resolveTarget(SEVERAL, undefined, undefined)).toBeNull();
    expect(resolveTarget(SEVERAL, 31, undefined)).toMatchObject({ kind: "account", opportunityId: 131 });
    expect(resolveTarget(SEVERAL, 30, undefined)).toMatchObject({ kind: "card", companyId: 30 });
    expect(resolveTarget(SEVERAL, 32, undefined)).toBeNull();
    // Karta o nazwie z pliku już jest, więc nowej się nie zakłada.
    expect(canCreateCard(SEVERAL)).toBe(false);
    expect(resolveTarget(SEVERAL, "new", undefined)).toBeNull();
    const related = { ...SEVERAL, cards: SEVERAL.cards.filter((item) => !item.exact) };
    expect(resolveTarget(related, "new", undefined)).toMatchObject({ kind: "new_company" });
  });

  it("klient NEXUSA nie ma celu, a konto założone przed chwilą wygrywa z wyborem", () => {
    expect(resolveTarget(CLIENT, undefined, undefined)).toBeNull();
    expect(resolveTarget(MISSING, undefined, { companyId: 77, opportunityId: 177 })).toMatchObject({
      kind: "account",
      companyId: 77,
      opportunityId: 177,
    });
  });

  it("faza wiersza: dodany, pominięty, odmowa, wybór, gotowy", () => {
    const [ready, , choose, , , client, known] = PREVIEW.rows;
    const target = resolveTarget(WITH_ACCOUNT, undefined, undefined);
    expect(rowPhase(ready, WITH_ACCOUNT, target, undefined)).toBe("ready");
    expect(rowPhase(ready, WITH_ACCOUNT, target, outcome(2))).toBe("added");
    expect(rowPhase(ready, WITH_ACCOUNT, target, outcome(2, { result: "on_map" }))).toBe("skip");
    expect(rowPhase(known, WITH_ACCOUNT, target, undefined)).toBe("skip");
    expect(rowPhase(choose, SEVERAL, null, undefined)).toBe("choose");
    expect(rowPhase(client, CLIENT, null, undefined)).toBe("refused");
    // Błąd zapisu zostawia wiersz do ponowienia.
    expect(rowPhase(ready, WITH_ACCOUNT, target, outcome(2, { result: "error" }))).toBe("ready");
  });

  it("zbiorcza akceptacja liczy konta i karty raz na firmę", () => {
    const account = resolveTarget(WITH_ACCOUNT, undefined, undefined);
    const fresh = resolveTarget(MISSING, undefined, undefined);
    const bare = resolveTarget(BARE_CARD, undefined, undefined);
    if (!account || !fresh || !bare) throw new Error("brak celu");
    const effect = bulkEffect([
      { row: PREVIEW.rows[0], target: account },
      { row: PREVIEW.rows[3], target: fresh },
      { row: PREVIEW.rows[4], target: fresh },
      { row: PREVIEW.rows[1], target: bare },
    ]);
    expect(effect).toEqual({ people: 4, accounts: 2, companies: 1 });
    expect(bulkQuestion(effect)).toContain("powstanie 2 konta, a w kartotece 1 karta firmy");
    expect(bulkQuestion({ people: 1, accounts: 0, companies: 0 })).not.toContain("powstanie");
  });

  it("podsumowanie i nazwa źródła z pliku", () => {
    expect(previewSummary(PREVIEW)).toBe("7 osób w 5 firmach · 6 pewnych, 1 do weryfikacji · 2 wiersze pominięte");
    expect(sourceFromFile("centra-it_lista.csv")).toBe("Lista z researchu: centra it lista");
    expect(sourceFromFile(".csv")).toBe("");
  });
});

describe("wgranie pliku", () => {
  it("wybrany plik idzie do serwera, a ekran niczego nie zapisuje", () => {
    render(<ResearchImport />);
    const file = new File(["x"], "lista.xlsx");
    fireEvent.change(screen.getByLabelText("Plik z listą osób"), { target: { files: [file] } });
    expect(previewMutate).toHaveBeenCalledWith(file, expect.anything());
    expect(acceptMutate).not.toHaveBeenCalled();
  });

  it("odmowa serwera jest pokazana jego słowami", () => {
    previewError = Object.assign(new Error("422"), {
      isAxiosError: true,
      response: { status: 422, data: { detail: "W pliku brakuje kolumny z nazwą firmy (np. „Firma”)." } },
    });
    render(<ResearchImport />);
    expect(screen.getByRole("alert")).toHaveTextContent("W pliku brakuje kolumny z nazwą firmy");
  });
});

describe("przegląd listy", () => {
  it("każdy wiersz mówi, co NEXUS wie o firmie i co się stanie", () => {
    openReview();

    const account = rowOf("Jan Fikcyjny");
    expect(account.getByText("Konto w Fabrykach IT")).toBeInTheDocument();
    expect(account.getByText("Mapa decyzyjna gotowa · mapa: 1 z 3 po kontakcie")).toBeInTheDocument();
    expect(account.getByText("Pewne")).toBeInTheDocument();
    expect(account.getByRole("link", { name: "Kto ich zna: Żuraw Test" })).toHaveTextContent("7");
    expect(account.getByRole("link", { name: "profil" })).toHaveAttribute("href", "https://linkedin.example/jan");
    expect(account.getByRole("button", { name: "Dodaj do mapy: Jan Fikcyjny" })).toBeEnabled();

    const bare = rowOf("Ewa Zmyślona");
    expect(bare.getByText("Karta bez konta")).toBeInTheDocument();
    expect(bare.getByText("12 kontaktów na karcie · konto w archiwum")).toBeInTheDocument();
    expect(bare.getByText("Do weryfikacji")).toBeInTheDocument();
    expect(bare.getByText("pominięto adres e-mail (niepełny)")).toBeInTheDocument();
    expect(bare.getByRole("button", { name: "Załóż konto: Ewa Zmyślona" })).toBeInTheDocument();

    const several = rowOf("Adam Wymyślony");
    expect(several.getByText("3 karty firmy")).toBeInTheDocument();
    expect(several.getByText("Wskaż kartę firmy")).toBeInTheDocument();
    expect(several.getByText("w tym klient NEXUSA: Bocian Polska")).toBeInTheDocument();

    const missing = rowOf("Olga Zmyślna");
    expect(missing.getByText("Brak karty")).toBeInTheDocument();
    expect(missing.getByText("powstanie firma z domeną perkoz.example i konto w Fabrykach IT")).toBeInTheDocument();
    expect(missing.getByRole("button", { name: "Załóż firmę: Olga Zmyślna" })).toBeInTheDocument();

    const client = rowOf("Anna Fikcyjna");
    expect(client.getByText("Klient NEXUSA")).toBeInTheDocument();
    expect(client.getByText("Uzgodnij z DL: Opiekun Testowy")).toBeInTheDocument();
    expect(client.queryByRole("button")).toBeNull();
    expect(client.getByText("Temat dla Delivery Leada")).toBeInTheDocument();

    const known = rowOf("Stary Wpis");
    expect(known.getByText(/Już na mapie/)).toBeInTheDocument();
    expect(known.getByRole("link", { name: "otwórz" })).toHaveAttribute("href", "/sales/opportunities/100");
    expect(known.queryByRole("button")).toBeNull();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Pominięte wiersze pliku (2): brak nazwy firmy: wiersze 9, 11.",
    );
  });

  it("akceptacja wiersza wysyła osobę z kartą, poziomem i źródłem", async () => {
    acceptMutate.mockResolvedValue(accepted([outcome(2)]));
    openReview();
    fireEvent.change(screen.getByLabelText("Poziom decyzji: Jan Fikcyjny"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Opiekun nowych kont"), { target: { value: "2" } });

    fireEvent.click(screen.getByRole("button", { name: "Dodaj do mapy: Jan Fikcyjny" }));

    await waitFor(() => expect(rowOf("Jan Fikcyjny").getByText("Dodano")).toBeInTheDocument());
    const input = acceptMutate.mock.calls[0][0];
    expect(input.source_label).toBe("Lista z researchu: centra it lista");
    expect(input.owner_user_id).toBe(2);
    expect(input.people).toEqual([
      expect.objectContaining({
        line: 2,
        company: "Żuraw Test",
        name: "Jan Fikcyjny",
        decision_level: 1,
        confidence: "confirmed",
        company_id: 10,
      }),
    ]);
    expect(rowOf("Jan Fikcyjny").getByRole("link", { name: "Otwórz konto" })).toHaveAttribute(
      "href",
      "/sales/opportunities/100",
    );
    // Po dodaniu poziomu już się nie zmienia tutaj: wpis jest na mapie.
    expect(screen.getByLabelText("Poziom decyzji: Jan Fikcyjny")).toBeDisabled();
  });

  it("firma z kilkoma kartami czeka na wskazanie karty", async () => {
    acceptMutate.mockResolvedValue(accepted([outcome(4, { company_id: 31, opportunity_id: 131 })]));
    openReview();
    const select = screen.getByLabelText("Karta firmy: Bocian");
    // Karty klienta NEXUSA nie ma na liście, a nowej karty nie zakłada się obok dokładnej.
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Wybierz kartę",
      "Bocian · 2 kontakty na karcie · znamy teraz 1",
      "Bocian Group · konto: Pierwszy kontakt · znamy teraz 4",
    ]);

    fireEvent.change(select, { target: { value: "31" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do mapy: Adam Wymyślony" }));

    await waitFor(() => expect(acceptMutate).toHaveBeenCalled());
    expect(sentPeople()[0]).toMatchObject({ line: 4, company_id: 31, decision_level: 2 });
  });

  it("„Dodaj pewne do map” bierze tylko pewne wiersze z ustalonym celem", async () => {
    askConfirm.mockResolvedValue(true);
    acceptMutate.mockResolvedValue(
      accepted([
        outcome(2),
        outcome(5, { company_id: 77, opportunity_id: 177, created_company: true, created_account: true }),
        outcome(6, { company_id: 77, opportunity_id: 177 }),
      ]),
    );
    openReview();

    fireEvent.click(screen.getByRole("button", { name: "Dodaj pewne do map (3)" }));

    await waitFor(() => expect(acceptMutate).toHaveBeenCalled());
    // Bez „do weryfikacji”, bez firmy czekającej na kartę i bez klienta NEXUSA.
    expect(sentPeople().map((person) => person.line)).toEqual([2, 5, 6]);
    expect(sentPeople()[1]).toMatchObject({ company_id: null, domain: "perkoz.example" });
    expect(askConfirm.mock.calls[0][0].description).toContain("powstanie 1 konto, a w kartotece 1 karta firmy");
    await waitFor(() => expect(screen.getAllByText("Dodano")).toHaveLength(3));
    expect(screen.getByRole("button", { name: "Dodaj pewne do map (0)" })).toBeDisabled();
    expect(screen.getByText(/dodano 3/)).toBeInTheDocument();
    expect(toast.showSuccess).toHaveBeenCalledWith("Na mapy trafiło: 3 osoby.");
  });

  it("rezygnacja w potwierdzeniu niczego nie wysyła", async () => {
    askConfirm.mockResolvedValue(false);
    openReview();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj pewne do map (3)" }));
    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(acceptMutate).not.toHaveBeenCalled();
  });

  it("druga osoba nowej firmy trafia na konto założone przed chwilą", async () => {
    acceptMutate.mockResolvedValueOnce(
      accepted([outcome(5, { company_id: 77, opportunity_id: 177, created_company: true, created_account: true })]),
    );
    acceptMutate.mockResolvedValueOnce(accepted([outcome(6, { company_id: 77, opportunity_id: 177 })]));
    openReview();

    fireEvent.click(screen.getByRole("button", { name: "Załóż firmę: Olga Zmyślna" }));

    const next = await screen.findByRole("button", { name: "Dodaj do mapy: Piotr Zmyślny" });
    expect(rowOf("Piotr Zmyślny").getByText("założone z tej listy")).toBeInTheDocument();
    fireEvent.click(next);
    await waitFor(() => expect(acceptMutate).toHaveBeenCalledTimes(2));
    expect(sentPeople(1)[0]).toMatchObject({ line: 6, company_id: 77 });
  });

  it("dwie osoby tej samej firmy nie zapisują się naraz", async () => {
    let finish: (value: ResearchAccepted) => void = () => undefined;
    acceptMutate.mockReturnValueOnce(new Promise<ResearchAccepted>((resolve) => (finish = resolve)));
    acceptMutate.mockResolvedValueOnce(accepted([outcome(6, { company_id: 77, opportunity_id: 177 })]));
    openReview();

    fireEvent.click(screen.getByRole("button", { name: "Załóż firmę: Olga Zmyślna" }));

    // Pierwsze żądanie jeszcze trwa: druga osoba firmy czeka, inne firmy nie.
    const second = screen.getByRole("button", { name: "Załóż firmę: Piotr Zmyślny" });
    expect(second).toBeDisabled();
    fireEvent.click(second);
    expect(acceptMutate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Dodaj do mapy: Jan Fikcyjny" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Dodaj pewne do map (1)" })).toBeEnabled();

    finish(
      accepted([outcome(5, { company_id: 77, opportunity_id: 177, created_company: true, created_account: true })]),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Dodaj do mapy: Piotr Zmyślny" }));
    await waitFor(() => expect(acceptMutate).toHaveBeenCalledTimes(2));
    expect(sentPeople(1)[0]).toMatchObject({ line: 6, company_id: 77 });
  });

  it("odmowa i błąd wiersza zostają przy wierszu", async () => {
    acceptMutate.mockResolvedValueOnce(
      accepted([
        outcome(2, {
          result: "client",
          detail: "Żuraw Test to klient NEXUSA, szansy nie zakładamy. Przekaż do: Opiekun Testowy.",
          opportunity_id: null,
        }),
      ]),
    );
    acceptMutate.mockResolvedValueOnce(
      accepted([outcome(3, { result: "error", detail: "Nie udało się zapisać tego wiersza. Spróbuj ponownie." })]),
    );
    openReview();

    fireEvent.click(screen.getByRole("button", { name: "Dodaj do mapy: Jan Fikcyjny" }));
    await waitFor(() => expect(rowOf("Jan Fikcyjny").getByText("Temat dla Delivery Leada")).toBeInTheDocument());
    expect(toast.showError).toHaveBeenCalledWith(expect.stringContaining("klient NEXUSA"));

    fireEvent.click(screen.getByRole("button", { name: "Załóż konto: Ewa Zmyślona" }));
    const failed = await screen.findByText("Nie udało się zapisać tego wiersza. Spróbuj ponownie.");
    expect(failed).toHaveAttribute("role", "alert");
    // Wiersz z błędem można ponowić.
    expect(screen.getByRole("button", { name: "Załóż konto: Ewa Zmyślona" })).toBeEnabled();
  });

  it("bez „Skąd lista” nie da się niczego dodać", () => {
    openReview();
    fireEvent.change(screen.getByLabelText("Skąd lista"), { target: { value: " a " } });
    expect(screen.getByRole("button", { name: "Dodaj do mapy: Jan Fikcyjny" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Dodaj pewne do map/ })).toBeDisabled();
  });

  it("filtr „Tylko do decyzji” zostawia wiersze do weryfikacji i do wyboru karty", () => {
    openReview();
    fireEvent.click(screen.getByRole("button", { name: "Tylko do decyzji (2)" }));
    expect(screen.getByText(/Ewa Zmyślona/)).toBeInTheDocument();
    expect(screen.getByText(/Adam Wymyślony/)).toBeInTheDocument();
    expect(screen.queryByText(/Jan Fikcyjny/)).toBeNull();
    expect(screen.queryByText(/Anna Fikcyjna/)).toBeNull();
  });

  it("nieudany skan „Znamy teraz” nie zabiera przeglądu", () => {
    const cards = WITH_ACCOUNT.cards.map((item) => ({ ...item, known_current: null }));
    openReview({
      ...PREVIEW,
      known_failed: true,
      skipped: [],
      companies: [{ ...WITH_ACCOUNT, cards }, BARE_CARD, SEVERAL, MISSING, CLIENT],
    });
    expect(screen.getByRole("status")).toHaveTextContent("Nie udało się teraz policzyć „Znamy teraz”");
    expect(rowOf("Jan Fikcyjny").queryByRole("link", { name: /Kto ich zna/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Dodaj do mapy: Jan Fikcyjny" })).toBeEnabled();
  });

  it("„Zmień plik” wraca do wgrania", () => {
    openReview();
    fireEvent.click(screen.getByRole("button", { name: "Zmień plik" }));
    expect(screen.getByRole("button", { name: /Wybierz plik/ })).toBeInTheDocument();
  });
});

describe("wejście w Leadach", () => {
  it("konto z edycją Sprzedaży ma „Listę z researchu” obok leadów", () => {
    render(<LeadsView />);
    fireEvent.click(screen.getByRole("radio", { name: "Lista z researchu" }));
    expect(screen.getByRole("button", { name: /Wybierz plik/ })).toBeInTheDocument();
  });

  it("konto z samym podglądem nie ma wejścia do importu", () => {
    canEdit = false;
    render(<LeadsView />);
    expect(screen.queryByRole("radio", { name: "Lista z researchu" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Wybierz plik/ })).toBeNull();
  });

  it("przy włączonych sygnałach Leady dalej otwierają skrzynkę sygnałów", () => {
    signalsOn = true;
    render(<LeadsView />);
    expect(screen.getByText("Skrzynka sygnałów")).toBeInTheDocument();
    expect(screen.getAllByRole("radio").map((radio) => radio.textContent)).toEqual([
      "Sygnały bota",
      "Wszystkie leady",
      "Lista z researchu",
    ]);
  });
});

describe("źródło przy osobie na mapie", () => {
  const imported: DecisionMapEntry = {
    key: "k1",
    name: "Jan Fikcyjny",
    contact_status: "not_contacted",
    source: "research",
    source_label: "Lista testowa",
    source_added_at: "2026-11-10",
    source_confidence: "to_verify",
    source_url: "https://zrodlo.example/jan",
  };

  it("wpis z importu mówi, skąd pochodzi i od kiedy", () => {
    expect(sourceLine(imported)).toBe("źródło: Lista testowa · na mapie od 10.11.2026 · do weryfikacji");
    expect(sourceLine({ ...imported, source_confidence: "confirmed" })).toBe(
      "źródło: Lista testowa · na mapie od 10.11.2026",
    );
    // Wpis z Atlasa albo dodany ręcznie nie ma źródła.
    expect(sourceLine({ source_label: null })).toBeNull();
  });

  it("okno osoby pokazuje źródło z linkiem", () => {
    render(<DecisionPersonDialog opportunityId={1} entry={imported} onClose={vi.fn()} />);
    const line = screen.getByTestId("decision-person-source");
    expect(line).toHaveTextContent("źródło: Lista testowa · na mapie od 10.11.2026 · do weryfikacji");
    expect(within(line).getByRole("link", { name: "otwórz źródło" })).toHaveAttribute(
      "href",
      "https://zrodlo.example/jan",
    );
  });

  it("okno osoby spoza importu nie ma linii źródła", () => {
    render(
      <DecisionPersonDialog
        opportunityId={1}
        entry={{ key: "k2", name: "Osoba Ręczna", contact_status: "not_contacted" }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("decision-person-source")).toBeNull();
  });
});
