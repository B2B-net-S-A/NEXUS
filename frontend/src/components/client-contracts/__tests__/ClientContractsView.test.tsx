import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientContractsView } from "../ClientContractsView";
import { clientContractDocumentsApi } from "@/lib/api/clientContractDocuments";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast }) }));
vi.mock("@/lib/authenticated-files", () => ({ downloadAuthenticatedFile: vi.fn() }));

const CONTRACTS = [
  {
    id: 1,
    client_id: 10,
    client_name: "Alfa Testowa",
    name: "Umowa ramowa Alfa",
    status: "active" as const,
    effective_date: "2026-01-01",
    expiry_date: null,
    filename: "alfa.pdf",
    has_file: true,
    amendments: [
      {
        id: 7,
        name: "Aneks numer 1",
        effective_date: "2026-06-01",
        filename: "aneks.pdf",
        has_file: true,
      },
    ],
  },
  {
    id: 2,
    client_id: 20,
    client_name: "Beta Testowa",
    name: "Umowa ramowa Beta",
    status: "expired" as const,
    effective_date: null,
    expiry_date: "2025-12-31",
    filename: null,
    has_file: false,
    amendments: [],
  },
];

function renderView() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ClientContractsView />
    </QueryClientProvider>,
  );
}

describe("ClientContractsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pokazuje umowy z aneksami, a brak pliku nazywa wprost", async () => {
    vi.spyOn(clientContractDocumentsApi, "list").mockResolvedValue(CONTRACTS);
    renderView();

    expect(await screen.findByText("Umowa ramowa Alfa")).toBeInTheDocument();
    expect(screen.getByText("Aneks: Aneks numer 1")).toBeInTheDocument();
    expect(screen.getByText("Brak pliku")).toBeInTheDocument();
    expect(screen.getByText("Aktywna")).toBeInTheDocument();
  });

  it("pobiera plik aneksu z trasy tego ekranu", async () => {
    vi.spyOn(clientContractDocumentsApi, "list").mockResolvedValue(CONTRACTS);
    renderView();

    await userEvent.click(
      await screen.findByRole("button", { name: "Pobierz: Aneks numer 1" }),
    );

    expect(downloadAuthenticatedFile).toHaveBeenCalledWith(
      "/api/client-contract-documents/1/amendments/7/file",
      "aneks.pdf",
    );
  });

  it("szuka także po nazwie aneksu i mówi, gdy nic nie pasuje", async () => {
    vi.spyOn(clientContractDocumentsApi, "list").mockResolvedValue(CONTRACTS);
    renderView();
    const search = await screen.findByRole("searchbox", {
      name: "Szukaj w umowach klientów",
    });

    await userEvent.type(search, "numer 1");
    expect(screen.getByText("Umowa ramowa Alfa")).toBeInTheDocument();
    expect(screen.queryByText("Umowa ramowa Beta")).not.toBeInTheDocument();

    await userEvent.type(search, " nieistniejący");
    expect(
      screen.getByText("Żadna umowa nie pasuje do wyszukiwania."),
    ).toBeInTheDocument();
  });

  it("awaria nie wygląda jak pusta lista", async () => {
    vi.spyOn(clientContractDocumentsApi, "list").mockRejectedValue(new Error("boom"));
    renderView();

    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(
      screen.queryByText("Nie ma jeszcze żadnych umów klientów."),
    ).not.toBeInTheDocument();
  });
});
