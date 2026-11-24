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
    patch: (...a: unknown[]) => patch(...a),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { ChartTab } from "@/components/finance/ledger/ChartTab";
import type { Account, PostingRule } from "@/lib/api/finance-posting";

const ACCOUNTS: Account[] = [
  { id: 1, number: "402-203", name: "Usługi obce — kontraktorzy", kind: "cost", kind_label: "koszt", active: true, rules: 2 },
  { id: 2, number: "221", name: "VAT naliczony", kind: "vat", kind_label: "VAT", active: false, rules: 0 },
];

const RULES: PostingRule[] = [
  {
    id: 10,
    category: "contractor",
    category_label: "Kontraktorzy",
    counterparty_id: null,
    counterparty_name: null,
    label: "Kontraktorzy",
    cost_account: "402-203",
    vat_account: "221",
    deduction: "full",
    deduction_label: "100%",
    register: "purchase",
    register_label: "Zakup",
    doc_type: "FVZ",
    service_label: "Usługi IT",
    description_template: "{usługa} {MM}/{RRRR}",
    active: true,
  },
  {
    id: 11,
    category: "office",
    category_label: "Biuro",
    counterparty_id: 7,
    counterparty_name: "Firma Testowa sp. z o.o.",
    label: "Biuro · Firma Testowa sp. z o.o.",
    cost_account: "402-100",
    vat_account: null,
    deduction: "none",
    deduction_label: "brak",
    register: "purchase",
    register_label: "Zakup",
    doc_type: "FVZ",
    service_label: "Najem",
    description_template: "{usługa} {MM}/{RRRR}",
    active: false,
  },
];

type Reply = unknown[] | Error;

function routes({ accounts = ACCOUNTS as Reply, rules = RULES as Reply, options = [] as Reply } = {}) {
  get.mockImplementation(async (url: string) => {
    const pick = url.endsWith("/accounts")
      ? accounts
      : url.endsWith("/rules")
        ? rules
        : url.endsWith("/counterparty-options")
          ? options
          : new Error(`nieznany adres ${url}`);
    if (pick instanceof Error) throw pick;
    return { data: { items: pick } };
  });
}

function renderTab(canWrite?: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      {canWrite === undefined ? <ChartTab /> : <ChartTab canWrite={canWrite} />}
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  showToast.mockReset();
});

describe("ChartTab — plan kont", () => {
  it("pokazuje konta z rodzajem, liczbą reguł i wyłączone konto jako „wyłączone”", async () => {
    routes();
    renderTab();
    const section = await screen.findByRole("region", { name: "Plan kont" });
    await within(section).findByText("Usługi obce — kontraktorzy");
    expect(within(section).getByText("w regułach: 2")).toBeInTheDocument();
    expect(within(section).getByText("koszt")).toBeInTheDocument();
    expect(within(section).getByText("wyłączone")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Włącz" })).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Wyłącz" })).toBeInTheDocument();
  });

  it("pusty plan kont tylko przy udanym odczycie", async () => {
    routes({ accounts: [] });
    renderTab();
    expect(await screen.findByText("Plan kont jest pusty.")).toBeInTheDocument();
  });

  it("awaria odczytu planu kont to komunikat błędu, nie „Plan kont jest pusty”", async () => {
    routes({ accounts: new Error("503") });
    renderTab();
    const section = await screen.findByRole("region", { name: "Plan kont" });
    expect(await within(section).findByRole("button", { name: /spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText("Plan kont jest pusty.")).not.toBeInTheDocument();
  });

  it("bez prawa zapisu: bez „Dodaj konto”, „Edytuj” i „Wyłącz”", async () => {
    routes();
    renderTab(false);
    await screen.findByText("Usługi obce — kontraktorzy");
    expect(screen.queryByRole("button", { name: "Dodaj konto" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj regułę" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edytuj" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyłącz" })).not.toBeInTheDocument();
  });

  it("nowe konto: „Zapisz” wyłączone bez numeru i nazwy, potem POST z rodzajem", async () => {
    const user = userEvent.setup();
    routes();
    post.mockResolvedValue({ data: ACCOUNTS[0] });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj konto" }));
    const section = screen.getByRole("region", { name: "Plan kont" });
    const save = within(section).getByRole("button", { name: "Zapisz" });
    expect(save).toBeDisabled();
    await user.type(within(section).getByLabelText("Nazwa konta"), "Usługi biurowe");
    expect(save).toBeDisabled();
    await user.type(within(section).getByLabelText("Numer konta"), "402-210");
    await user.selectOptions(within(section).getByLabelText("Rodzaj konta"), "revenue");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/posting/accounts", {
        number: "402-210",
        name: "Usługi biurowe",
        kind: "revenue",
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Konto dodane.", "success"));
    expect(within(section).queryByLabelText("Numer konta")).not.toBeInTheDocument();
  });

  it("edycja konta: bez pola numeru, PATCH tylko nazwy i rodzaju", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValue({ data: ACCOUNTS[0] });
    renderTab();
    const section = await screen.findByRole("region", { name: "Plan kont" });
    await within(section).findByText("Usługi obce — kontraktorzy");
    await user.click(within(section).getAllByRole("button", { name: "Edytuj" })[0]);
    expect(within(section).queryByLabelText("Numer konta")).not.toBeInTheDocument();
    const name = within(section).getByLabelText("Nazwa konta");
    await user.clear(name);
    await user.type(name, "Usługi obce");
    await user.click(within(section).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/finance/posting/accounts/1", { name: "Usługi obce", kind: "cost" }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Konto zapisane.", "success"));
  });

  it("błąd zapisu konta idzie toastem, formularz zostaje; „Anuluj” go zamyka", async () => {
    const user = userEvent.setup();
    routes();
    post.mockRejectedValue(new Error("409"));
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj konto" }));
    const section = screen.getByRole("region", { name: "Plan kont" });
    await user.type(within(section).getByLabelText("Numer konta"), "402-203");
    await user.type(within(section).getByLabelText("Nazwa konta"), "Duplikat");
    await user.click(within(section).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
    expect(within(section).getByLabelText("Numer konta")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Anuluj" }));
    expect(within(section).queryByLabelText("Numer konta")).not.toBeInTheDocument();
  });

  it("wyłączenie i włączenie konta odwraca flagę aktywności; błąd idzie toastem", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValueOnce({ data: ACCOUNTS[0] }).mockRejectedValueOnce(new Error("boom"));
    renderTab();
    const section = await screen.findByRole("region", { name: "Plan kont" });
    await user.click(await within(section).findByRole("button", { name: "Wyłącz" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/finance/posting/accounts/1", { active: false }),
    );
    await user.click(within(section).getByRole("button", { name: "Włącz" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/finance/posting/accounts/2", { active: true }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
  });
});

describe("ChartTab — reguły dekretu", () => {
  it("reguła z pełnym odliczeniem pokazuje konto VAT, bez odliczenia — dopisek", async () => {
    routes();
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    const [full, none] = await within(section).findAllByRole("listitem");
    expect(full.textContent).toContain("+ VAT 221");
    expect(none.textContent).toContain("(VAT bez odliczenia)");
    expect(none.textContent).not.toContain("+ VAT");
    expect(within(none).getByText("wyłączona")).toBeInTheDocument();
  });

  it("pusta lista reguł ostrzega, że bez reguły dekret nie powstanie", async () => {
    routes({ rules: [] });
    renderTab();
    expect(await screen.findByText(/Nie ma reguł — bez reguły dekret faktury nie powstanie/)).toBeInTheDocument();
  });

  it("awaria odczytu reguł to komunikat błędu, nie pusta lista", async () => {
    routes({ rules: new Error("503") });
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    expect(await within(section).findByRole("button", { name: /spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma reguł/)).not.toBeInTheDocument();
  });

  it("nowa reguła: domyślne konta i podgląd opisu, POST z kategorią i kontrahentem", async () => {
    const user = userEvent.setup();
    routes({ options: [{ id: 7, name: "Firma Testowa sp. z o.o.", id_value: "0000000000", cost_account: null }] });
    post.mockResolvedValue({ data: RULES[0] });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj regułę" }));
    const form = screen.getByLabelText("Reguła dekretu");
    expect(within(form).getByLabelText("Konto VAT")).toHaveValue("221");
    expect(within(form).getByText("Przykład: „Usługi IT 10/2026”")).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Kategoria"), "contractor");
    await user.type(within(form).getByLabelText("Kontrahent reguły"), "Firma");
    const option = await within(form).findByRole("button", { name: /Firma Testowa sp\. z o\.o\./ }, { timeout: 2000 });
    expect(option.textContent).toContain("· bez konta");
    await user.click(option);
    expect(within(form).getByRole("button", { name: "Każdy kontrahent" })).toBeInTheDocument();
    await user.type(within(form).getByLabelText("Konto kosztu"), "402-203");
    await user.type(within(form).getByLabelText("Usługa"), "Programowanie");
    expect(within(form).getByText("Przykład: „Programowanie 10/2026”")).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/posting/rules", {
        cost_account: "402-203",
        vat_account: "221",
        deduction: "full",
        register: "purchase",
        doc_type: "FVZ",
        service_label: "Programowanie",
        description_template: "{usługa} {MM}/{RRRR}",
        category: "contractor",
        counterparty_id: 7,
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Reguła dodana.", "success"));
    expect(get).toHaveBeenCalledWith("/api/finance/posting/counterparty-options", { params: { q: "Firma" } });
  });

  it("kontrahent z kontem w podpowiedzi pokazuje numer konta; „Każdy kontrahent” go zdejmuje", async () => {
    const user = userEvent.setup();
    routes({ options: [{ id: 8, name: "Dostawca Testowy", id_value: null, cost_account: "402-300" }] });
    post.mockResolvedValue({ data: RULES[0] });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj regułę" }));
    const form = screen.getByLabelText("Reguła dekretu");
    await user.type(within(form).getByLabelText("Kontrahent reguły"), "Do");
    const option = await within(form).findByRole("button", { name: /Dostawca Testowy/ }, { timeout: 2000 });
    expect(option.textContent).toContain("· 402-300");
    await user.click(option);
    await user.click(within(form).getByRole("button", { name: "Każdy kontrahent" }));
    expect(within(form).getByLabelText("Kontrahent reguły")).toHaveValue("");
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/finance/posting/rules",
        expect.objectContaining({ category: "office", counterparty_id: null }),
      ),
    );
  });

  it("nieznane pole we wzorze opisu blokuje zapis i podaje dozwolone pola", async () => {
    const user = userEvent.setup();
    routes();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj regułę" }));
    const form = screen.getByLabelText("Reguła dekretu");
    const template = within(form).getByLabelText("Wzór opisu");
    await user.clear(template);
    // userEvent traktuje „{” jako początek klawisza — „{{” wpisuje sam znak.
    await user.type(template, "{{miesiąc}");
    expect(within(form).getByText(/Nieznane pole: \{miesiąc\}\. Dozwolone:/)).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Zapisz regułę" })).toBeDisabled();
  });

  it("odliczenie inne niż pełne chowa konto VAT", async () => {
    const user = userEvent.setup();
    routes();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj regułę" }));
    const form = screen.getByLabelText("Reguła dekretu");
    await user.selectOptions(within(form).getByLabelText("Odliczenie VAT"), "partial");
    expect(within(form).queryByLabelText("Konto VAT")).not.toBeInTheDocument();
  });

  it("edycja reguły: PATCH po id, bez kategorii i kontrahenta", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValue({ data: RULES[1] });
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    await within(section).findByText("Biuro · Firma Testowa sp. z o.o.");
    await user.click(within(section).getAllByRole("button", { name: "Edytuj" })[1]);
    const form = within(section).getByLabelText("Reguła dekretu");
    expect(within(form).queryByLabelText("Kategoria")).not.toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Rejestr"), "sale");
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const [url, body] = patch.mock.calls[0];
    expect(url).toBe("/api/finance/posting/rules/11");
    expect(body).toMatchObject({
      cost_account: "402-100",
      deduction: "none",
      register: "sale",
      doc_type: "FVZ",
      service_label: "Najem",
      description_template: "{usługa} {MM}/{RRRR}",
    });
    expect(body).not.toHaveProperty("category");
    expect(body).not.toHaveProperty("counterparty_id");
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Reguła zapisana.", "success"));
  });

  // Pole konta VAT jest przy odliczeniu innym niż pełne ukryte, więc edycja
  // innego pola nie może po cichu dopisać domyślnego „221” do reguły z null.
  it("edycja reguły bez odliczenia z vat_account null nie dopisuje ukrytego konta VAT 221", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValue({ data: RULES[1] });
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    await within(section).findByText("Biuro · Firma Testowa sp. z o.o.");
    await user.click(within(section).getAllByRole("button", { name: "Edytuj" })[1]);
    const form = within(section).getByLabelText("Reguła dekretu");
    await user.selectOptions(within(form).getByLabelText("Rejestr"), "sale");
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0][1]).toMatchObject({ deduction: "none", vat_account: null });
  });

  it("reguła bez konta VAT po przełączeniu na pełne odliczenie dostaje domyślne 221", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValue({ data: RULES[1] });
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    await within(section).findByText("Biuro · Firma Testowa sp. z o.o.");
    await user.click(within(section).getAllByRole("button", { name: "Edytuj" })[1]);
    const form = within(section).getByLabelText("Reguła dekretu");
    await user.selectOptions(within(form).getByLabelText("Odliczenie VAT"), "full");
    expect(within(form).getByLabelText("Konto VAT")).toHaveValue("221");
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0][1]).toMatchObject({ deduction: "full", vat_account: "221" });
  });

  it("reguła bez konta VAT przełączona na odliczenie 50% wysyła 221 (baza wymaga konta poza „brak”)", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValue({ data: RULES[1] });
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    await within(section).findByText("Biuro · Firma Testowa sp. z o.o.");
    await user.click(within(section).getAllByRole("button", { name: "Edytuj" })[1]);
    const form = within(section).getByLabelText("Reguła dekretu");
    await user.selectOptions(within(form).getByLabelText("Odliczenie VAT"), "partial");
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0][1]).toMatchObject({ deduction: "partial", vat_account: "221" });
  });

  it("błąd zapisu reguły idzie toastem; „Anuluj” zamyka formularz", async () => {
    const user = userEvent.setup();
    routes();
    post.mockRejectedValue(new Error("422"));
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Dodaj regułę" }));
    const form = screen.getByLabelText("Reguła dekretu");
    await user.click(within(form).getByRole("button", { name: "Zapisz regułę" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
    await user.click(within(form).getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByLabelText("Reguła dekretu")).not.toBeInTheDocument();
  });

  it("wyłączenie i włączenie reguły; błąd idzie toastem", async () => {
    const user = userEvent.setup();
    routes();
    patch.mockResolvedValueOnce({ data: RULES[0] }).mockRejectedValueOnce(new Error("boom"));
    renderTab();
    const section = await screen.findByRole("region", { name: "Reguły dekretu" });
    await user.click(await within(section).findByRole("button", { name: "Wyłącz" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/finance/posting/rules/10", { active: false }));
    await user.click(within(section).getByRole("button", { name: "Włącz" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/finance/posting/rules/11", { active: true }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
  });
});
