/**
 * Targ kandydatów: awaria ≠ pusty targ (audyt F-20).
 *
 * Przed naprawą 403/500 renderowało się jako „Brak kandydatów na targu” WRAZ
 * z instrukcją, jak kogoś dodać — czyli ekran namawiał do naprawiania stanu,
 * który był w porządku. Test odrzuca obietnicę `marketplaceApi.list`, więc
 * przechodzi tą samą ścieżką, którą szedł defekt.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  remove: vi.fn(),
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
  marketplaceApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    remove: (...args: unknown[]) => mocks.remove(...args),
  },
}));

vi.mock("@/components/marketplace/CandidateMatchesExpansion", () => ({
  CandidateMatchesExpansion: () => null,
}));

import { MarketplaceTable } from "@/components/marketplace/MarketplaceTable";

const EMPTY_TEXT = "Brak kandydatów na targu";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderTable() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MarketplaceTable />
    </QueryClientProvider>,
  );
}

describe("MarketplaceTable — stany zapytania", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("500 pokazuje awarię, a nie pusty targ z instrukcją dodawania", async () => {
    mocks.list.mockRejectedValue(httpError(500));

    renderTable();

    expect(
      await screen.findByText(/Nie udało się pobrać danych/),
    ).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByText(/Wrzuć na targ/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    ).toBeInTheDocument();
  });

  it("403 mówi o uprawnieniach i nie proponuje ponowienia", async () => {
    mocks.list.mockRejectedValue(httpError(403));

    renderTable();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/Targ NIE jest pusty/)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
  });

  it("licznik „Razem na targu” przy awarii pokazuje „—”, nie zero", async () => {
    mocks.list.mockRejectedValue(httpError(500));

    renderTable();

    const counter = await screen.findByText(/Razem na targu/);
    await waitFor(() => expect(counter).toHaveTextContent("—"));
    expect(counter).not.toHaveTextContent("0");
  });

  it("sukces z zerem kandydatów dalej pokazuje pusty stan z instrukcją", async () => {
    mocks.list.mockResolvedValue({ data: { items: [], total: 0 } });

    renderTable();

    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się pobrać danych/),
    ).not.toBeInTheDocument();
  });
});
