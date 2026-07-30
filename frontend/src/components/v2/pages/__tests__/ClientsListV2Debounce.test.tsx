import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";
import type {
  ClientDirectoryParams,
  ClientDirectoryResponse,
} from "@/lib/api";

const mocks = vi.hoisted(() => ({
  currentSearch: "",
  list: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  canCreate: false,
}));

vi.mock("@/lib/api", () => ({
  clientsDirectoryApi: {
    list: (...args: unknown[]) => mocks.list(...args),
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/clients",
  useRouter: () => ({
    push: mocks.push,
    replace: mocks.replace,
  }),
  useSearchParams: () => new URLSearchParams(mocks.currentSearch),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapability: () => mocks.canCreate,
}));

vi.mock("@/components/AppShell", () => ({
  AddClientModal: ({ category }: { category?: string }) => (
    <div data-testid="add-client-modal-category">{category}</div>
  ),
}));

const BASE_RESPONSE: ClientDirectoryResponse = {
  items: [
    {
      scope_id: 11,
      client_id: 7,
      msa_id: 101,
      display_name: "Nordea ABP",
      legal_name: "Nordea Bank Abp Spółka Akcyjna Oddział w Polsce",
      scope_label: "Bankowość",
      industry: "Banking & Finance",
      active_consultants_count: 4,
      effective_date: "2026-02-01",
      expiry_date: null,
      category: "active",
      client_status: "active",
    },
    {
      scope_id: 12,
      client_id: 7,
      msa_id: null,
      display_name: "Nordea ABP",
      legal_name: "Nordea Bank Abp Spółka Akcyjna Oddział w Polsce",
      scope_label: "Technology",
      industry: "Banking & Finance",
      active_consultants_count: 4,
      effective_date: null,
      expiry_date: null,
      category: "active",
      client_status: "active",
    },
  ],
  total_rows: 2,
  total_clients: 1,
  page: 1,
  page_size: 50,
  category_counts: {
    active: 1,
    relationship: 4,
    inactive: 3,
  },
  as_of: "2026-07-30",
};

function response(
  overrides: Partial<ClientDirectoryResponse> = {},
): ClientDirectoryResponse {
  return {
    ...BASE_RESPONSE,
    ...overrides,
    category_counts:
      overrides.category_counts ?? BASE_RESPONSE.category_counts,
  };
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <ClientsListV2 />
    </QueryClientProvider>,
  );
  return {
    ...rendered,
    rerenderList: () =>
      rendered.rerender(
        <QueryClientProvider client={queryClient}>
          <ClientsListV2 />
        </QueryClientProvider>,
      ),
  };
}

function requestedParams(callIndex = 0): ClientDirectoryParams {
  return mocks.list.mock.calls[callIndex][0] as ClientDirectoryParams;
}

describe("ClientsListV2 — katalog klientów", () => {
  beforeEach(() => {
    mocks.currentSearch = "";
    mocks.list.mockReset();
    mocks.push.mockReset();
    mocks.replace.mockReset();
    mocks.canCreate = false;
    mocks.list.mockResolvedValue({ data: BASE_RESPONSE });
  });

  it(
    "domyślnie pobiera aktywnych i pokazuje docelowe kolumny oraz zakresy",
    async () => {
      renderList();

      expect(await screen.findAllByText("Nordea ABP")).toHaveLength(2);
      expect(requestedParams()).toEqual({
        category: "active",
        q: undefined,
        page: 1,
        page_size: 50,
      });
      expect(mocks.replace).toHaveBeenCalledWith(
        "/clients?category=active&page=1",
        { scroll: false },
      );

      expect(
        screen.getByRole("tab", { name: /^Aktywni klienci/i }),
      ).toHaveAttribute("aria-selected", "true");
      expect(
        screen.getByRole("tab", { name: /^Klienci relacyjni/i }),
      ).toHaveTextContent("4");
      expect(
        screen
          .getAllByRole("columnheader")
          .map((header) => header.textContent?.trim()),
      ).toEqual([
        "Firma",
        "Branża",
        "Aktywni konsultanci",
        "Start umowy",
        "Koniec umowy",
        "Status klienta",
      ]);
      expect(screen.getByText("2 zakresy dla 1 klienta")).toBeVisible();
      expect(
        screen.queryByRole("columnheader", { name: "Hit ratio" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("columnheader", { name: "NDA" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("columnheader", { name: "Dodano" }),
      ).not.toBeInTheDocument();

      expect(screen.getByText("01.02.2026")).toBeVisible();
      expect(screen.getByText("Bezterminowa")).toBeVisible();
      expect(screen.getByText("Bankowość")).toBeVisible();
      expect(screen.getByText("Technology")).toBeVisible();
      expect(
        within(
          screen.getByRole("row", { name: /Nordea ABP Technology/i }),
        ).getAllByText("—"),
      ).toHaveLength(2);
      expect(
        screen.getAllByLabelText(/łącznie we wszystkich zakresach/i),
      ).toHaveLength(2);
    },
    10_000,
  );

  it("odtwarza kategorię, wyszukiwanie i stronę z deep-linku", async () => {
    mocks.currentSearch = "category=relationship&q=Nordea&page=2";
    mocks.list.mockResolvedValue({
      data: response({
        items: [],
        total_rows: 0,
        total_clients: 0,
        page: 2,
      }),
    });

    renderList();

    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(1));
    expect(requestedParams()).toEqual({
      category: "relationship",
      q: "Nordea",
      page: 2,
      page_size: 50,
    });
    expect(screen.getByLabelText("Wyszukaj klienta")).toHaveValue("Nordea");
    expect(
      screen.getByRole("tab", { name: /^Klienci relacyjni/i }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("zmienia kategorię semantycznym kafelkiem, zachowuje frazę i resetuje stronę", async () => {
    const user = userEvent.setup();
    mocks.currentSearch = "category=active&q=bank&page=3";
    renderList();
    await screen.findAllByText("Nordea ABP");

    await user.click(
      screen.getByRole("tab", { name: /^Klienci relacyjni/i }),
    );

    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    expect(requestedParams(1)).toMatchObject({
      category: "relationship",
      q: "bank",
      page: 1,
    });
    expect(mocks.push).toHaveBeenCalledWith(
      "/clients?category=relationship&q=bank&page=1",
      { scroll: false },
    );
  });

  it(
    "przy szybkim type→tab używa od razu aktualnej frazy w nowym kafelku",
    async () => {
      const user = userEvent.setup();
      renderList();
      await screen.findAllByText("Nordea ABP");

      await user.type(screen.getByLabelText("Wyszukaj klienta"), "acme");
      await user.click(
        screen.getByRole("tab", { name: /^Klienci relacyjni/i }),
      );

      await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
      expect(requestedParams(1)).toMatchObject({
        category: "relationship",
        q: "acme",
        page: 1,
      });
      expect(
        mocks.list.mock.calls.some(
          ([params]) =>
            (params as ClientDirectoryParams).category === "relationship" &&
            !(params as ClientDirectoryParams).q,
        ),
      ).toBe(false);
    },
    10_000,
  );

  it("obsługuje klawiaturę zgodnie ze wzorcem semantycznych tabów", async () => {
    const user = userEvent.setup();
    renderList();
    await screen.findAllByText("Nordea ABP");

    const activeTab = screen.getByRole("tab", {
      name: /^Aktywni klienci/i,
    });
    activeTab.focus();
    await user.keyboard("{ArrowRight}");

    const relationshipTab = screen.getByRole("tab", {
      name: /^Klienci relacyjni/i,
    });
    expect(relationshipTab).toHaveFocus();
    expect(relationshipTab).toHaveAttribute("aria-selected", "true");
    await waitFor(() =>
      expect(requestedParams(1)).toMatchObject({
        category: "relationship",
        page: 1,
      }),
    );

    await user.keyboard("{Home}");
    expect(activeTab).toHaveFocus();
    expect(activeTab).toHaveAttribute("aria-selected", "true");
  });

  it("otwiera formularz z kategorią aktualnie wybranego kafelka", async () => {
    const user = userEvent.setup();
    mocks.canCreate = true;
    mocks.currentSearch = "category=inactive&page=1";
    renderList();
    await screen.findAllByText("Nordea ABP");

    await user.click(screen.getByRole("button", { name: "Nowy klient" }));

    expect(screen.getByTestId("add-client-modal-category")).toHaveTextContent(
      "inactive",
    );
  });

  it("debouncuje wyszukiwanie w aktywnym kafelku i zapisuje je w URL", async () => {
    const user = userEvent.setup();
    renderList();
    await screen.findAllByText("Nordea ABP");

    const input = screen.getByLabelText("Wyszukaj klienta");
    await user.type(input, "acme");
    expect(input).toHaveValue("acme");

    await waitFor(
      () => {
        expect(mocks.list).toHaveBeenCalledTimes(2);
        expect(requestedParams(1)).toMatchObject({
          category: "active",
          q: "acme",
          page: 1,
        });
      },
      { timeout: 2000 },
    );
    expect(mocks.replace).toHaveBeenCalledWith(
      "/clients?category=active&q=acme&page=1",
      { scroll: false },
    );
  });

  it("rozróżnia pusty wynik wyszukiwania od pustej kategorii", async () => {
    const user = userEvent.setup();
    mocks.list.mockImplementation((params: ClientDirectoryParams) =>
      Promise.resolve({
        data: response({
          items: params.q ? [] : BASE_RESPONSE.items,
          total_rows: params.q ? 0 : 2,
          total_clients: params.q ? 0 : 1,
        }),
      }),
    );
    renderList();
    await screen.findAllByText("Nordea ABP");

    await user.type(screen.getByLabelText("Wyszukaj klienta"), "brak");

    expect(
      await screen.findByText(/Brak wyników w kategorii/i),
    ).toBeVisible();
    expect(
      screen.getAllByRole("button", { name: "Wyczyść wyszukiwanie" }),
    ).toHaveLength(2);
  });

  it("pokazuje osobny stan pustej kategorii bez aktywnej frazy", async () => {
    mocks.list.mockResolvedValue({
      data: response({
        items: [],
        total_rows: 0,
        total_clients: 0,
      }),
    });

    renderList();

    expect(
      await screen.findByText(/Brak klientów w kategorii/i),
    ).toBeVisible();
    expect(screen.queryByText(/Brak wyników w kategorii/i)).not.toBeInTheDocument();
  });

  it("oznacza panel jako zajęty podczas pierwszego ładowania", async () => {
    let resolveRequest:
      | ((value: { data: ClientDirectoryResponse }) => void)
      | undefined;
    mocks.list.mockImplementationOnce(
      () =>
        new Promise<{ data: ClientDirectoryResponse }>((resolve) => {
          resolveRequest = resolve;
        }),
    );

    renderList();

    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Ładowanie portfela…")).toBeVisible();

    await act(async () => {
      resolveRequest?.({ data: BASE_RESPONSE });
    });
    await waitFor(() =>
      expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-busy", "false"),
    );
  });

  it("nie maskuje 403 jako pustej listy", async () => {
    mocks.list.mockRejectedValue({ response: { status: 403 } });
    renderList();

    expect(await screen.findByText("Brak uprawnień")).toBeVisible();
    expect(
      screen.getByText(/Dane nie są puste/i),
    ).toBeVisible();
    expect(
      screen.queryByText(/Brak klientów w kategorii/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/i }),
    ).not.toBeInTheDocument();
  });

  it("dla błędu sieci pokazuje instrukcję offline i akcję ponowienia", async () => {
    mocks.list.mockRejectedValue(new Error("Network Error"));
    renderList();

    expect(
      await screen.findByText(/Sprawdź internet lub VPN/i),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/i }),
    ).toBeVisible();
  });

  it("dla 5xx pokazuje błąd serwera, a nie komunikat pustej listy", async () => {
    mocks.list.mockRejectedValue({ response: { status: 500 } });
    renderList();

    expect(
      await screen.findByText(/Wystąpił błąd po stronie serwera/i),
    ).toBeVisible();
    expect(
      screen.queryByText(/Sprawdź internet lub VPN/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Brak klientów w kategorii/i),
    ).not.toBeInTheDocument();
  });

  it("zapisuje paginację w URL i pobiera wybraną stronę", async () => {
    const user = userEvent.setup();
    mocks.list.mockResolvedValue({
      data: response({
        total_rows: 51,
        total_clients: 50,
      }),
    });
    renderList();
    await screen.findAllByText("Nordea ABP");

    await user.click(screen.getByRole("button", { name: "Następna" }));

    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    expect(requestedParams(1)).toMatchObject({ page: 2 });
    expect(mocks.push).toHaveBeenCalledWith(
      "/clients?category=active&page=2",
      { scroll: false },
    );
  });

  it("utrzymuje fokus i nawigację podczas pobierania kolejnej strony", async () => {
    const user = userEvent.setup();
    let resolveNext:
      | ((value: { data: ClientDirectoryResponse }) => void)
      | undefined;
    mocks.list
      .mockResolvedValueOnce({
        data: response({ total_rows: 51, total_clients: 50 }),
      })
      .mockImplementationOnce(
        () =>
          new Promise<{ data: ClientDirectoryResponse }>((resolve) => {
            resolveNext = resolve;
          }),
      );
    renderList();
    await screen.findAllByText("Nordea ABP");

    const next = screen.getByRole("button", { name: "Następna" });
    await user.click(next);
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));

    expect(next).toHaveFocus();
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(next).not.toBeDisabled();
    expect(screen.getByRole("navigation", { name: "Paginacja klientów" }))
      .toBeVisible();
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-busy", "true");

    resolveNext?.({
      data: response({
        total_rows: 51,
        total_clients: 50,
        page: 2,
      }),
    });
    await waitFor(() =>
      expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-busy", "false"),
    );
  });

  it("odtwarza stan po zmianie URL odpowiadającej back/forward", async () => {
    const view = renderList();
    await screen.findAllByText("Nordea ABP");

    mocks.currentSearch = "category=relationship&q=bank&page=2";
    view.rerenderList();

    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          category: "relationship",
          q: "bank",
          page: 2,
        }),
        expect.anything(),
      ),
    );
    expect(screen.getByLabelText("Wyszukaj klienta")).toHaveValue("bank");
    expect(
      screen.getByRole("tab", { name: /^Klienci relacyjni/i }),
    ).toHaveAttribute("aria-selected", "true");

    mocks.currentSearch = "category=active&page=1";
    view.rerenderList();

    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          category: "active",
          q: undefined,
          page: 1,
        }),
        expect.anything(),
      ),
    );
  });
});
