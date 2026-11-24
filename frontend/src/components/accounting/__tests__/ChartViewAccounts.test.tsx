import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: (...a: unknown[]) => patch(...a),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));

let accounting: { config: unknown; period: { year: number; month: number } };
vi.mock("@/components/accounting/AccountingShell", () => ({
  useAccounting: () => accounting,
}));

import { ChartView } from "@/components/accounting/ChartView";
import type { ChartAccount } from "@/lib/api/accounting";

function account(overrides: Partial<ChartAccount>): ChartAccount {
  return {
    id: 1,
    number: "100",
    name: "Konto testowe",
    kind: "other",
    kind_label: "inne",
    active: true,
    parent_number: null,
    account_type: null,
    account_type_label: null,
    dictionary: null,
    dictionary_label: null,
    report_line: null,
    class: "1",
    has_children: false,
    postable: true,
    used: 0,
    in_rules: 0,
    ...overrides,
  };
}

const ACCOUNTS: ChartAccount[] = [
  account({ id: 1, number: "130", name: "Rachunek bieżący", class: "1", used: 42, account_type: "active", account_type_label: "bilansowe aktywne" }),
  account({ id: 2, number: "402", name: "Usługi obce", class: "4", kind: "cost", postable: false, has_children: true }),
  account({
    id: 3,
    number: "402-215",
    name: "Najem biura",
    class: "4",
    kind: "cost",
    parent_number: "402",
    in_rules: 2,
    dictionary: "counterparty",
    dictionary_label: "kontrahenci",
  }),
  account({ id: 4, number: "999", name: "Stare konto", class: "9", active: false, kind: "egzotyczny" }),
];

function config(approver = false) {
  return {
    me: { admin: false, approver, payroll: false },
    account_kinds: ["cost", "vat", "settlement", "revenue", "other"],
    account_types: [
      { code: "active", label: "bilansowe aktywne" },
      { code: "passive", label: "bilansowe pasywne" },
    ],
    dictionaries: [{ code: "counterparty", label: "kontrahenci" }],
  };
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChartView />
    </QueryClientProvider>,
  );
}

function field(dialog: HTMLElement, label: string) {
  return within(dialog).getByText(label).closest("label")!.querySelector("input, select") as
    | HTMLInputElement
    | HTMLSelectElement;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  showToast.mockReset();
  accounting = { config: config(), period: { year: 2026, month: 10 } };
  get.mockResolvedValue({ data: { items: ACCOUNTS } });
});

describe("Plan kont — lista", () => {
  it("pokazuje stan, rodzaj, analitykę i liczbę zapisów każdego konta", async () => {
    renderView();
    const table = await screen.findByRole("table");
    const bank = within(table).getByText("130").closest("tr")!;
    expect(within(bank).getByText("42")).toBeInTheDocument();
    expect(within(bank).getByText("bilansowe aktywne")).toBeInTheDocument();
    expect(within(bank).getByText("Księgowalne")).toBeInTheDocument();
    const synthetic = within(table).getByText("402").closest("tr")!;
    expect(within(synthetic).getByText("Syntetyczne")).toBeInTheDocument();
    expect(within(synthetic).getByText("konta pod spodem")).toBeInTheDocument();
    expect(within(synthetic).getByText("koszt")).toBeInTheDocument();
    const analytic = within(table).getByText("402-215").closest("tr")!;
    expect(within(analytic).getByText("pod 402")).toBeInTheDocument();
    expect(within(analytic).getByText("słownik: kontrahenci")).toBeInTheDocument();
    expect(within(analytic).getByText("w regułach dekretu: 2")).toBeInTheDocument();
    const off = within(table).getByText("999").closest("tr")!;
    expect(within(off).getByText("Wyłączone")).toBeInTheDocument();
    // Nieznany rodzaj z API pokazuje się surowo, nie znika.
    expect(within(off).getByText("egzotyczny")).toBeInTheDocument();
  });

  it("filtruje po zespole i po numerze albo nazwie; brak trafień to pusty stan", async () => {
    const user = userEvent.setup();
    renderView();
    await screen.findByRole("table");
    const select = screen.getByLabelText("Zespół kont");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Wszystkie zespoły",
      "Zespół 1",
      "Zespół 4",
      "Zespół 9",
    ]);
    await user.selectOptions(select, "4");
    expect(screen.queryByText("130")).not.toBeInTheDocument();
    expect(screen.getByText("402-215")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Szukaj konta"), "NAJEM");
    expect(screen.queryByText("Usługi obce")).not.toBeInTheDocument();
    expect(screen.getByText("Najem biura")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Szukaj konta"));
    await user.type(screen.getByLabelText("Szukaj konta"), "130");
    expect(screen.getByText("Nie ma kont dla wybranych filtrów.")).toBeInTheDocument();
  });

  it("awaria planu kont to błąd z ponowieniem, nie „nie ma kont”", async () => {
    get.mockRejectedValue(new Error("500"));
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText("Nie ma kont dla wybranych filtrów.")).not.toBeInTheDocument();
  });
});

describe("Plan kont — konto", () => {
  it("nowe konto wysyła numer i puste pola jako null", async () => {
    post.mockResolvedValue({ data: { items: ACCOUNTS } });
    const user = userEvent.setup();
    renderView();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Dodaj konto" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Nowe konto")).toBeInTheDocument();
    expect(within(dialog).queryByText(/Konto aktywne/)).not.toBeInTheDocument();
    await user.type(field(dialog, "Numer"), "402-216");
    await user.type(field(dialog, "Nazwa"), "Najem magazynu");
    await user.type(field(dialog, "Konto nadrzędne"), "402");
    await user.selectOptions(field(dialog, "Rodzaj w dekrecie faktur"), "cost");
    await user.selectOptions(field(dialog, "Słownik analityki"), "counterparty");
    await user.click(within(dialog).getByRole("button", { name: "Dodaj konto" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/accounting/chart", {
      number: "402-216",
      name: "Najem magazynu",
      kind: "cost",
      account_type: null,
      parent_number: "402",
      dictionary: "counterparty",
      report_line: null,
    });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Dodano konto do planu."));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("edycja konta nie pozwala zmienić numeru, a konto z reguły dekretu — rodzaju; wyłączenie idzie PATCH-em", async () => {
    patch.mockResolvedValue({ data: { items: ACCOUNTS } });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByText("Najem biura"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Konto 402-215")).toBeInTheDocument();
    expect(field(dialog, "Numer")).toBeDisabled();
    expect(field(dialog, "Rodzaj w dekrecie faktur")).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox"));
    await user.selectOptions(field(dialog, "Typ konta"), "passive");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch).toHaveBeenCalledWith("/api/accounting/chart/3", {
      name: "Najem biura",
      kind: "cost",
      account_type: "passive",
      parent_number: "402",
      dictionary: "counterparty",
      report_line: null,
      active: false,
    });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano konto."));
  });

  it("odmowa zapisu zostawia okno otwarte i pokazuje powód z API", async () => {
    post.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: "Konto 130 już jest w planie." } } });
    const user = userEvent.setup();
    renderView();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Dodaj konto" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(field(dialog, "Numer"), "130");
    await user.click(within(dialog).getByRole("button", { name: "Dodaj konto" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Konto 130 już jest w planie.", "error"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Anuluj zamyka okno bez zapisu", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByText("Rachunek bieżący"));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(patch).not.toHaveBeenCalled();
  });
});

describe("Plan kont — import z Symfonii", () => {
  it("błąd pliku pokazuje komunikat, a lista problemów mówi, ile jeszcze nie pokazano", async () => {
    accounting = { config: config(true), period: { year: 2026, month: 10 } };
    post
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 422, data: { detail: "To nie jest plik modelu księgowego." } } })
      .mockResolvedValueOnce({
        data: {
          saved: false,
          accounts_in_file: 20,
          created: 14,
          existing: 6,
          blocked: 0,
          filled: 0,
          dictionaries: 1,
          markers: 0,
          markers_ignored: 0,
          problems: ["Problem A", "Problem B"],
          problems_total: 5,
          notes: [],
          preview: Array.from({ length: 14 }, (_, index) => ({
            number: `500-${index + 1}`,
            name: `Konto ${index + 1}`,
            account_type: null,
            account_type_label: null,
            dictionary: index === 0 ? "counterparty" : null,
            report_line: null,
          })),
        },
      });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Wczytaj plan z Symfonii" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Sprawdź plik" })).toBeDisabled();
    await user.upload(within(dialog).getByLabelText("Plik planu kont z Symfonii"), new File(["x"], "model.xml"));
    await user.click(within(dialog).getByRole("button", { name: "Sprawdź plik" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("To nie jest plik modelu księgowego.", "error"));
    await user.click(within(dialog).getByRole("button", { name: "Sprawdź plik" }));
    expect(await within(dialog).findByText("…i jeszcze 3.")).toBeInTheDocument();
    expect(within(dialog).getByText("Pokazano 12 z 14 nowych kont.")).toBeInTheDocument();
    expect(within(dialog).getByText("500-12")).toBeInTheDocument();
    expect(within(dialog).queryByText("500-13")).not.toBeInTheDocument();
    expect(within(dialog).getByText("— · słownik kontrahentów")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Dodaj 14 kont" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Anuluj" })).toBeInTheDocument();
  });
});
