import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, put: mocks.put, post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: vi.fn(), showToast: vi.fn() }),
}));

import { FrameworkCategoryCard } from "../FrameworkCategoryCard";
import type { FrameworkCategory } from "@/lib/api/framework-rates";

const SENIOR = {
  id: 3,
  label: "Developer Senior",
  role: "developer",
  seniority: "senior",
  rate_max: 178,
  valid_from: "2026-01-01",
  valid_to: null,
  addons: ["Kafka 20%", "Rust 15%"],
};
const JUNIOR = { ...SENIOR, id: 4, label: "Developer Junior", seniority: "junior", rate_max: 90, addons: [] };

function category(overrides: Partial<FrameworkCategory> = {}): FrameworkCategory {
  return {
    contract_id: 11,
    client_id: 7,
    rate_client: "226.10",
    framework_limit: "213.60",
    gap: "12.5",
    status: "over",
    card: SENIOR,
    source: "coa",
    coa_label: "Developer Senior",
    addon: {
      technology: "Kafka",
      percent: "20.00",
      confirmed_by: "Anna Przykładowa",
      confirmed_on: "2026-11-03",
      evidence: "mail z 03.11",
    },
    cards: [SENIOR, JUNIOR],
    ...overrides,
  };
}

function route(data: FrameworkCategory | Error) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === "/api/contracts/11/framework-category") {
      if (data instanceof Error) throw data;
      return { data };
    }
    if (url === "/api/contracts/11/premium-skills") return { data: { evidence: [], claims: [] } };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderCard(props: { canView?: boolean; canEdit?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FrameworkCategoryCard contractId={11} canView={props.canView ?? true} canEdit={props.canEdit ?? true} />
    </QueryClientProvider>,
  );
}

function row(term: string) {
  return screen.getByText(term, { selector: "dt" }).parentElement as HTMLElement;
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.put.mockReset();
  mocks.success.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("FrameworkCategoryCard — karta", () => {
  it("bez prawa podglądu nie pyta API i nic nie pokazuje", () => {
    route(category());
    const { container } = renderCard({ canView: false });
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("klient bez cennika i bez kategorii z COA nie ma karty", async () => {
    route(category({ cards: [], coa_label: null, card: null }));
    const { container } = renderCard();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container.querySelector("[data-testid='framework-category-card']")).toBeNull();
  });

  it("stawka ponad limitem: różnica w zł/h, limit z dopłatą i potwierdzenie klienta", async () => {
    route(category());
    renderCard();
    await screen.findByTestId("framework-category-card");
    expect(within(row("Status")).getByText("Ponad stawką")).toBeInTheDocument();
    expect(within(row("Status")).getByText("o 12,50 zł/h ponad limit")).toBeInTheDocument();
    expect(within(row("Kategoria")).getByText("(z COA)")).toBeInTheDocument();
    expect(row("Limit")).toHaveTextContent("178,00 zł/h + 20% Kafka = 213,60 zł/h");
    expect(row("Potwierdzenie dopłaty")).toHaveTextContent("Anna Przykładowa, 03.11.2026");
    // Kategoria z COA zgadza się z kartą — bez ostrzeżenia.
    expect(screen.queryByText("W ostatnim COA")).not.toBeInTheDocument();
  });

  it("w stawce dzięki dopłacie nie pokazuje różnicy, a wybór DL ma swoją etykietę", async () => {
    route(category({ status: "in_addon", gap: "-3.4", source: "dl" }));
    renderCard();
    await screen.findByTestId("framework-category-card");
    expect(within(row("Status")).getByText("W stawce dzięki dopłacie")).toBeInTheDocument();
    expect(screen.queryByText(/ponad limit/)).not.toBeInTheDocument();
    expect(within(row("Kategoria")).getByText("(wybrał Delivery Lead)")).toBeInTheDocument();
  });

  it("bez kategorii: „nie ustalono”, ostrzeżenie o pozycji z COA spoza cennika i limit „—”", async () => {
    route(
      category({
        card: null,
        source: null,
        status: "no_limit",
        gap: null,
        framework_limit: null,
        addon: null,
        coa_label: "Architekt Expert",
      }),
    );
    renderCard({ canEdit: false });
    await screen.findByTestId("framework-category-card");
    expect(within(row("Kategoria")).getByText("nie ustalono")).toBeInTheDocument();
    expect(row("W ostatnim COA")).toHaveTextContent("Architekt Expert — brak tej pozycji w cenniku");
    expect(row("Limit")).toHaveTextContent("—");
    expect(within(row("Status")).getByText("Bez limitu z umowy")).toBeInTheDocument();
    expect(screen.queryByText("Potwierdzenie dopłaty")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kategoria i dopłata" })).not.toBeInTheDocument();
  });

  it("kategoria bez stawki maksymalnej pokazuje sam limit z API", async () => {
    route(category({ card: { ...SENIOR, rate_max: null }, addon: null, framework_limit: null, status: "no_limit", gap: null }));
    renderCard();
    await screen.findByTestId("framework-category-card");
    expect(row("Limit")).toHaveTextContent("—");
  });

  it("awaria GET /framework-category pokazuje kartę z błędem i ponowieniem, a nie znika jak u klienta bez umowy ramowej", async () => {
    let calls = 0;
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/contracts/11/framework-category") {
        calls += 1;
        if (calls === 1) throw { isAxiosError: true, response: { status: 500, data: { detail: "Cennik chwilowo niedostępny." } } };
        return { data: category() };
      }
      if (url === "/api/contracts/11/premium-skills") return { data: { evidence: [], claims: [] } };
      throw new Error(`nieoczekiwane ${url}`);
    });
    const user = userEvent.setup();
    renderCard();
    const card = await screen.findByTestId("framework-category-card");
    expect(within(card).getByText("Umowa ramowa")).toBeInTheDocument();
    const alert = within(card).getByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać danych");
    expect(alert).toHaveTextContent("Cennik chwilowo niedostępny.");
    // Bez danych nie ma czego edytować.
    expect(screen.queryByRole("button", { name: "Kategoria i dopłata" })).not.toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByText("Ponad stawką")).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it.each([403, 404])("odmowa albo brak kontraktu (%i) chowa kartę jak dotąd", async (status) => {
    mocks.get.mockRejectedValue({ isAxiosError: true, response: { status, data: { detail: "nie" } } });
    const { container } = renderCard();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe("FrameworkCategoryCard — „Kategoria i dopłata”", () => {
  it("bez kategorii nie zapisuje; kategoria bez dopłat blokuje wybór dopłaty", async () => {
    route(category({ card: null, addon: null, source: null }));
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: "Kategoria i dopłata" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(within(dialog).getByText("Wybierz kategorię z umowy ramowej.")).toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(within(dialog).getByLabelText("Dopłata za technologię")).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText("Kategoria i poziom"), "4");
    expect(within(dialog).getByText("Umowa nie przewiduje dopłat w tej kategorii.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Dopłata za technologię")).toBeDisabled();
    expect(within(dialog).getByRole("option", { name: "Developer Senior — 178,00 zł/h" })).toBeInTheDocument();
  });

  it("dopłata wymaga potwierdzenia klienta; zapis wysyła technologię bez procentu i datę „od” z kalendarza firmy", async () => {
    // 30.11 23:30 UTC to już 1 grudnia w Warszawie — granica miesiąca.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-30T23:30:00Z"));
    route(category({ card: null, addon: null, source: null, coa_label: null }));
    mocks.put.mockResolvedValue({ data: category() });
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: "Kategoria i dopłata" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Limit obowiązuje od")).toHaveValue("2026-12-01");
    await user.selectOptions(within(dialog).getByLabelText("Kategoria i poziom"), "3");
    await user.selectOptions(within(dialog).getByLabelText("Dopłata za technologię"), "Kafka");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(within(dialog).getByText("Dopłatę wpisz z potwierdzeniem klienta: kto potwierdził i kiedy.")).toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
    await user.type(within(dialog).getByLabelText("Potwierdził po stronie klienta"), "  Jan Testowy ");
    await user.type(within(dialog).getByLabelText("Data potwierdzenia"), "2026-11-28");
    await user.type(within(dialog).getByLabelText("Dowód (mail, wpis w CPRO)"), "   ");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    expect(mocks.put).toHaveBeenCalledWith("/api/contracts/11/framework-category", {
      rate_card_id: 3,
      addon_technology: "Kafka",
      confirmed_by: "Jan Testowy",
      confirmed_on: "2026-11-28",
      evidence: null,
      effective_from: "2026-12-01",
    });
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Zapisano kategorię i limit z umowy ramowej"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("zmiana kategorii kasuje dopłatę; bez dopłaty potwierdzenie nie idzie, pusta data „od” to null", async () => {
    route(category());
    mocks.put.mockResolvedValue({ data: category() });
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: "Kategoria i dopłata" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Dopłata za technologię")).toHaveValue("Kafka");
    expect(within(dialog).getByLabelText("Potwierdził po stronie klienta")).toHaveValue("Anna Przykładowa");
    await user.selectOptions(within(dialog).getByLabelText("Kategoria i poziom"), "4");
    expect(within(dialog).queryByLabelText("Potwierdził po stronie klienta")).not.toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Limit obowiązuje od"));
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    expect(mocks.put.mock.calls[0][1]).toEqual({
      rate_card_id: 4,
      addon_technology: null,
      confirmed_by: null,
      confirmed_on: null,
      evidence: null,
      effective_from: null,
    });
  });

  it("odmowa serwera zostaje w oknie jako komunikat", async () => {
    route(category());
    mocks.put.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: "Cennik wygasł 31.10.2026." } } });
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: "Kategoria i dopłata" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(await within(dialog).findByText("Cennik wygasł 31.10.2026.")).toBeInTheDocument();
    expect(mocks.success).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
