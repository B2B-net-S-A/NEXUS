/**
 * Zakładka „Technologie” klienta: „Nowa rekrutacja z tej mapy” tylko dla
 * osób z `job.create` (strona `/jobs/new` odsyła resztę na listę, np. TCM),
 * a domyślny opiekun spoza listy opiekunów nie znika z pola wyboru.
 * Dane zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), canCreateJob: false }));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/capabilities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/capabilities")>()),
  hasCapability: (_user: unknown, capability: string) =>
    capability === "job.create" ? mocks.canCreateJob : false,
}));
vi.mock("@/components/care/UnlinkedCardsPanel", () => ({ UnlinkedCardsPanel: () => null }));

import { ClientTechnologiesTab } from "@/components/care/ClientTechnologiesTab";
import { clientTechMap } from "@/app/preview/hr-client-tech/fixtures";
import { useAuthStore, type User } from "@/store/auth";

const someone = { id: 5, email: "tcm@example.com", name: "Iga Próbna", role: "talent_community_manager", roles: ["talent_community_manager"] } as unknown as User;

function renderTab(owners: { id: number; name: string }[]) {
  mocks.get.mockImplementation(async (url: string) =>
    url === "/api/care/owners"
      ? { data: { items: owners } }
      : { data: { ...clientTechMap("2026-10-19"), default_owner: { id: 99, name: "Olga Wykluczona" } } },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientTechnologiesTab clientId={3} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  useAuthStore.setState({ user: someone, hydrated: true });
});

describe("ClientTechnologiesTab", () => {
  it("bez `job.create` nie ma przycisku nowej rekrutacji", async () => {
    mocks.canCreateJob = false;
    renderTab([]);
    expect(await screen.findByText("Dodaj notatkę o stacku")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nowa rekrutacja z tej mapy" })).toBeNull();
  });

  it("z `job.create` przycisk prowadzi do formularza z klientem", async () => {
    mocks.canCreateJob = true;
    renderTab([]);
    const link = await screen.findByRole("link", { name: "Nowa rekrutacja z tej mapy" });
    expect(link).toHaveAttribute("href", "/jobs/new?client=3");
  });

  it("domyślny opiekun spoza listy zostaje widoczny w polu", async () => {
    mocks.canCreateJob = false;
    renderTab([{ id: 7, name: "Natalia Opiekuńcza" }]);
    const field = await screen.findByRole("combobox", { name: "Domyślny opiekun konsultantów klienta" });
    expect(await screen.findByText(/Olga Wykluczona/, {}, { timeout: 2000 })).toBeInTheDocument();
    expect(field).toHaveTextContent("Olga Wykluczona");
  });

  it("mapa cieplna: dział × technologia z dymkiem źródeł i obramowaniem otwartej rekrutacji", async () => {
    mocks.canCreateJob = false;
    renderTab([]);
    const table = await screen.findByRole("table", { name: "Technologie klienta po działach" });
    const headers = within(table).getAllByRole("columnheader").map((th) => th.textContent ?? "");
    expect(headers.slice(1, 5).map((text) => text.split(/(?=brak|menedżer|Piotr|Michał|nasi)/)[0])).toEqual([
      "CI/CD i chmura",
      "Data",
      "Kredyty",
      "Płatności",
    ]);
    // Dział bez źródła z 18 miesięcy ma ostrzeżenie w nagłówku.
    expect(within(table).getByText("brak źródła 18 mies.")).toBeInTheDocument();
    const java = within(table).getByRole("row", { name: /Java 17/ });
    const payments = within(java).getByTitle(
      "Płatności · Java 17: 3 karty, 4 rekrutacje, 3 konsultantów · 1 otwarta rekrutacja",
    );
    expect(payments).toHaveClass("ring-warning");
    expect(payments).toHaveTextContent("TRK");
    // Notatka o stacku nie ma działu — stoi w „bez działu”.
    expect(within(java).getByTitle("Bez działu · Java 17: 2 konsultantów, 1 notatka")).toBeInTheDocument();
    expect(within(java).getByTitle("CI/CD i chmura · Java 17: brak źródeł")).not.toHaveClass("ring-warning");
    // Luki do dopytania mają akcję.
    expect(screen.getByRole("link", { name: "Ustaw w „Strukturze u klienta”" })).toHaveAttribute(
      "href",
      "/clients/3?tab=struktura",
    );
  });
});
