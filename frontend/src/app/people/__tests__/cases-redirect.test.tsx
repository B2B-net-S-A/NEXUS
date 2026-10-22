/**
 * `/people/cases` (dawna zakładka „Sprawy” w „Ludziach”) prowadzi od 22.10.2026
 * do Opieki → „Do zrobienia”. Przy wyłączonym module opieki tablica spraw
 * zostaje pod starym adresem, żeby sprawy nie zniknęły.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/people/cases",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/admin-cases/CasesBoard", () => ({
  CasesBoard: () => <div data-testid="cases-board" />,
}));

import { hrConfig } from "@/app/preview/hr-fixtures";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { useAuthStore, type User } from "@/store/auth";

import PeopleCasesPage from "../cases/page";

function renderWith(config: HrConfig) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(hrKeys.config, config);
  useAuthStore.setState({ hydrated: true, user: { id: 108, role: "user" } as User });
  render(
    <QueryClientProvider client={client}>
      <PeopleCasesPage />
    </QueryClientProvider>,
  );
}

describe("/people/cases → /care", () => {
  beforeEach(() => router.replace.mockClear());

  it("moduł opieki włączony: przekierowanie na „Do zrobienia”", async () => {
    renderWith(hrConfig({ cases: true }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/care"));
    expect(screen.queryByTestId("cases-board")).toBeNull();
  });

  it("moduł opieki wyłączony: tablica spraw zostaje tutaj", async () => {
    const config = hrConfig({ cases: true });
    renderWith({ ...config, open_modules: { ...config.open_modules, care: false } });
    expect(await screen.findByTestId("cases-board")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });
});
