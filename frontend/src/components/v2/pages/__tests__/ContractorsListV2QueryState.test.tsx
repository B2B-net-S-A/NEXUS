/**
 * Awaria listy kontraktorów NIE może renderować się jako pustka (audyt F-20).
 *
 * Test celowo idzie przez realnie zepsutą ścieżkę: odrzucamy obietnicę
 * `contractorsApi.list`, czyli dokładnie to, co robi axios przy 403/500 —
 * a nie mockujemy warstwy widoku, która była zepsuta.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  stats: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=active"),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  contractorsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    stats: (...args: unknown[]) => mocks.stats(...args),
  },
}));

vi.mock("@/components/v2/modals/DraftCompletionModal", () => ({
  DraftCompletionModal: () => null,
}));

import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";

const EMPTY_LIST = {
  data: { items: [], total: 0, page: 1, page_size: 50 },
};
const OK_STATS = {
  data: { draft: 3, drafts_incomplete: 0, active: 7, ending: 2 },
};

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status },
  });
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractorsListV2 />
    </QueryClientProvider>,
  );
}

describe("ContractorsListV2 — stany zapytania", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.stats.mockResolvedValue(OK_STATS);
  });

  it("500 pokazuje awarię z ponowieniem, a NIE „Brak aktywnych kontraktorów”", async () => {
    mocks.list.mockRejectedValue(httpError(500));

    renderList();

    expect(
      await screen.findByText(/Nie udało się pobrać danych/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak aktywnych kontraktorów."),
    ).not.toBeInTheDocument();
    // Stopka nie może twierdzić, że policzyliśmy i wyszło zero.
    expect(screen.queryByText(/0 wynik/)).not.toBeInTheDocument();
  });

  it("403 mówi o uprawnieniach i NIE proponuje ponowienia", async () => {
    mocks.list.mockRejectedValue(httpError(403));

    renderList();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/Lista NIE jest pusta/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Brak aktywnych kontraktorów."),
    ).not.toBeInTheDocument();
  });

  it("sukces z zerem wierszy dalej pokazuje uczciwy pusty stan", async () => {
    mocks.list.mockResolvedValue(EMPTY_LIST);

    renderList();

    expect(
      await screen.findByText("Brak aktywnych kontraktorów."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się pobrać danych/),
    ).not.toBeInTheDocument();
  });

  it("padnięte statystyki dają „—” w licznikach zakładek, nie zero", async () => {
    mocks.list.mockResolvedValue(EMPTY_LIST);
    mocks.stats.mockRejectedValue(httpError(500));

    renderList();

    const tabs = await screen.findAllByRole("tab");
    expect(tabs).toHaveLength(3);
    await waitFor(() => {
      for (const tab of tabs) {
        expect(tab).toHaveTextContent("—");
        expect(tab).not.toHaveTextContent("0");
      }
    });
  });

  it("dostępne statystyki dalej pokazują liczby", async () => {
    mocks.list.mockResolvedValue(EMPTY_LIST);

    renderList();

    const active = await screen.findByRole("tab", { name: /Aktywni/ });
    await waitFor(() => expect(active).toHaveTextContent("7"));
  });
});
