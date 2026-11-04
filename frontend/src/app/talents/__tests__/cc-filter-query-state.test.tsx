/**
 * Filtr kategorii na liście pul talentów czytał słownik z zapytania bez stanu
 * awarii — błąd pobrania pokazywał „Brak opcji.”, czyli słownik bez kategorii.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  ccList: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  talentPoolsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    getCandidates: vi.fn(),
    removeCandidate: vi.fn(),
    deletePool: vi.fn(),
    create: vi.fn(),
  },
  competenceCategoriesApi: { list: (...args: unknown[]) => mocks.ccList(...args) },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number; role: string } }) => unknown) =>
    selector({ user: { id: 7, role: "admin" } }),
  hasRole: () => true,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import TalentsPage from "@/app/talents/page";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TalentsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({ data: [] });
});

describe("Pule talentów — filtr kategorii", () => {
  it("awaria słownika kategorii to błąd z „Ponów”, nie „Brak opcji.”", async () => {
    const user = userEvent.setup();
    mocks.ccList.mockRejectedValueOnce(new Error("500"));
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Wszystkie kategorie/ }));
    expect(await screen.findByText("Nie udało się pobrać kategorii.")).toBeInTheDocument();
    expect(screen.queryByText("Brak opcji.")).not.toBeInTheDocument();

    mocks.ccList.mockResolvedValueOnce([
      {
        id: 1,
        slug: "software_development",
        name_pl: "Development",
        name_en: "Development",
        description: "",
        keywords: [],
        display_order: 1,
      },
    ]);
    await user.click(screen.getByRole("button", { name: /Ponów/ }));
    expect(await screen.findByText("Development")).toBeInTheDocument();
  });

  it("pusty słownik nadal mówi „Brak opcji.”", async () => {
    const user = userEvent.setup();
    mocks.ccList.mockResolvedValueOnce([]);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Wszystkie kategorie/ }));
    expect(await screen.findByText("Brak opcji.")).toBeInTheDocument();
  });
});
