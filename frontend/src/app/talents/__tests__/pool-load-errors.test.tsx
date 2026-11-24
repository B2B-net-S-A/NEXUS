/**
 * Audyt 24.11.2026: awaria zapytań pul talentów wyglądała jak pustka —
 * „Brak pul firmowych”, licznik 0 i „Brak kandydatów w tej puli” obok
 * przycisku „Usuń pulę”. Awaria to komunikat z ponowieniem, pusty stan
 * tylko po udanym pobraniu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  getCandidates: vi.fn(),
  ccList: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  talentPoolsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    getCandidates: (...args: unknown[]) => mocks.getCandidates(...args),
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

const POOL = {
  id: 3,
  name: "Java",
  description: null,
  candidate_count: 3,
  created_at: "2026-01-01T00:00:00Z",
  criteria: null,
  competence_category_id: null,
  competence_category_slug: null,
  is_personal: false,
  owner_id: null,
  owner_name: null,
};

function httpError(detail: string) {
  return Object.assign(new Error("Request failed with status code 500"), {
    isAxiosError: true,
    response: { status: 500, data: { detail } },
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TalentsPage />
    </QueryClientProvider>,
  );
}

describe("pule talentów — awaria ≠ pustka", () => {
  beforeEach(() => {
    mocks.list.mockReset();
    mocks.getCandidates.mockReset();
    mocks.ccList.mockResolvedValue([]);
  });

  it("awaria listy pul: komunikat z ponowieniem zamiast „Brak pul firmowych” i licznika 0", async () => {
    mocks.list.mockRejectedValueOnce(httpError("Baza chwilowo niedostępna"));
    const user = userEvent.setup({ delay: null });
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać pul talentów");
    expect(screen.queryByText("Brak pul firmowych")).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("button", { name: /Firmowe/ })).queryByText("0"),
    ).not.toBeInTheDocument();

    mocks.list.mockResolvedValue({ data: [POOL] });
    await user.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByRole("button", { name: /Java/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("pusta lista pul po udanym pobraniu nadal mówi „Brak pul firmowych”", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByText("Brak pul firmowych")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("awaria członków puli: komunikat, bez „Brak kandydatów”, licznika 0 i „Usuń pulę”", async () => {
    mocks.list.mockResolvedValue({ data: [POOL] });
    mocks.getCandidates.mockRejectedValueOnce(httpError("Przekroczono czas"));
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Java/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać kandydatów tej puli");
    expect(screen.queryByText("Brak kandydatów w tej puli")).not.toBeInTheDocument();
    expect(screen.queryByText("Kandydaci w puli (0)")).not.toBeInTheDocument();
    expect(screen.queryByText("kandydatów")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń pulę/ })).not.toBeInTheDocument();

    mocks.getCandidates.mockResolvedValue({
      data: { candidates: [], total: 0, returned: 0, limit: 500, offset: 0 },
    });
    await user.click(within(alert).getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByText("Brak kandydatów w tej puli")).toBeInTheDocument();
    expect(screen.getByText("Kandydaci w puli (0)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Usuń pulę/ })).toBeInTheDocument();
  });
});
