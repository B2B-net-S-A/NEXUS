import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ContractThreadList } from "@/lib/api/contractTopic";

const push = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 5, authorization_version: 1 } }),
}));

import { ContractsNotificationsDropdown } from "../ContractsNotificationsDropdown";

const THREADS: ContractThreadList = {
  unread_contracts: 1,
  items: [
    {
      key: "b2b_signing_request:2",
      title: "Umowa 1555/2026 czeka na Twój podpis",
      message: "Jan Kowalski podpisał(a) umowę 1555/2026 podpisem kwalifikowanym.",
      unread_count: 2,
      unread_ids: [31, 32],
      last_at: new Date().toISOString(),
      link: "/contracts/b2b-generator?tab=generated",
    },
    {
      key: "b2b_signing_request:1",
      title: "Link do umowy 1554/2026 wygasł",
      message: "Anna Nowak nie podpisał(a) umowy w terminie.",
      unread_count: 0,
      unread_ids: [],
      last_at: new Date().toISOString(),
      link: "/contracts/b2b-generator?tab=generated",
    },
  ],
};

function renderDropdown() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractsNotificationsDropdown />
    </QueryClientProvider>,
  );
}

function findTrigger(name: string | RegExp = /^Umowy/) {
  return screen.findByRole("button", { name }, { timeout: 5_000 });
}

beforeEach(() => {
  push.mockReset();
  apiMock.get.mockReset();
  apiMock.put.mockReset();
  apiMock.get.mockResolvedValue({ data: THREADS });
  apiMock.put.mockResolvedValue({ data: { success: true, updated: 2 } });
});

describe("ContractsNotificationsDropdown — ikona „Umowy” (26.10.2026)", () => {
  it("liczba na ikonie to umowy z nowościami", async () => {
    renderDropdown();
    const button = await findTrigger("Umowy — z nowościami: 1");
    expect(button).toHaveTextContent("1");
    expect(apiMock.get).toHaveBeenCalledWith("/api/notifications/contracts");
  });

  it("jedna pozycja na umowę: ostatnie zdarzenie i jego opis", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    const waiting = await screen.findByRole("button", {
      name: "Umowa: Umowa 1555/2026 czeka na Twój podpis — nowe: 2",
    });
    expect(waiting).toHaveTextContent("podpisem kwalifikowanym");
    expect(
      screen.getByRole("button", { name: "Umowa: Link do umowy 1554/2026 wygasł" }),
    ).toBeInTheDocument();
  });

  it("klik gasi nowe zdarzenia tej umowy i otwiera ekran", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(await screen.findByRole("button", { name: /czeka na Twój podpis/ }));
    expect(push).toHaveBeenCalledWith("/contracts/b2b-generator?tab=generated");
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/topics/read", {
        topic: "contracts",
        ids: [31, 32],
      }),
    );
  });

  it("przeczytana pozycja tylko otwiera ekran, bez gaszenia", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(await screen.findByRole("button", { name: /wygasł/ }));
    expect(push).toHaveBeenCalled();
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it("„Oznacz wszystkie” gasi cały temat", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(
      await screen.findByRole("button", { name: "Oznacz wszystkie jako przeczytane" }),
    );
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/topics/read", {
        topic: "contracts",
      }),
    );
  });

  it("awaria zapytania to stan błędu, nie pusta lista", async () => {
    apiMock.get.mockRejectedValue(new Error("500"));
    renderDropdown();
    fireEvent.click(await findTrigger("Umowy"));
    expect(await screen.findByText("Nie udało się wczytać umów.")).toBeInTheDocument();
    expect(screen.queryByText(/nic nowego/)).toBeNull();
  });
});
