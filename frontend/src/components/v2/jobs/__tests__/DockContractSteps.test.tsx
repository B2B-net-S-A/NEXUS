/**
 * Krok „Umowa” w panelu osoby (PR 6 ścieżki kandydata, 04.10.2026): stan
 * umowy, podpisu i zamówienia bez przechodzenia do warsztatu.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const generated = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  b2bGeneratorApi: { generated: (...a: unknown[]) => generated(...a) },
}));

import { DockContractSteps } from "@/components/v2/jobs/DockContractSteps";

function renderSteps(props: Partial<React.ComponentProps<typeof DockContractSteps>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DockContractSteps
        candidateId={42}
        jobId={10}
        clientId={7}
        orderStatus={null}
        readOnly={false}
        {...props}
      />
    </QueryClientProvider>,
  );
}

const ROW = {
  id: 501,
  candidate_id: 42,
  contract_number: "1506/2026",
  contract_status: "in_progress",
  signature_status: "unsigned",
};

beforeEach(() => generated.mockReset());

describe("DockContractSteps", () => {
  it("bez umowy prowadzi do Generatora z wybraną osobą i rekrutacją", async () => {
    generated.mockResolvedValue([]);
    renderSteps();
    const link = await screen.findByRole("link", { name: "Otwórz Generator umów" });
    expect(link.getAttribute("href")).toContain("candidate=42");
    expect(link.getAttribute("href")).toContain("job=10");
    expect(generated).toHaveBeenCalledWith(50, { jobId: 10 });
  });

  it("umowa niepodpisana: numer i przejście do rejestru po potwierdzenie podpisu", async () => {
    generated.mockResolvedValue([ROW]);
    renderSteps();
    expect(await screen.findByText("Nr 1506/2026")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Oznacz jako podpisaną w rejestrze" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Otwórz Generator umów" })).toBeNull();
  });

  it("zatrudniony bez zamówienia: zdanie o sprawie i link do zamówień klienta", async () => {
    generated.mockResolvedValue([{ ...ROW, signature_status: "signed_both" }]);
    renderSteps({ orderStatus: "missing" });
    expect(await screen.findByRole("link", { name: "Zamówienia klienta" })).toHaveAttribute(
      "href",
      "/clients/7?tab=zamowienia",
    );
    expect(screen.queryByRole("link", { name: "Oznacz jako podpisaną w rejestrze" })).toBeNull();
  });

  it("anulowana umowa nie liczy się — panel znów prowadzi do Generatora", async () => {
    generated.mockResolvedValue([{ ...ROW, contract_status: "cancelled" }]);
    renderSteps();
    expect(await screen.findByRole("link", { name: "Otwórz Generator umów" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Oznacz jako podpisaną w rejestrze" })).toBeNull();
  });

  it("tylko do odczytu: stan bez przycisków", async () => {
    generated.mockResolvedValue([]);
    renderSteps({ readOnly: true });
    await screen.findByText("Umowa wygenerowana");
    expect(screen.queryByRole("link", { name: "Otwórz Generator umów" })).toBeNull();
  });
});
