/**
 * „Karty z Compassa do połączenia” w zakładce „Technologie” klienta:
 * bez kart nic się nie pokazuje, awaria nie udaje pustki, propozycja jest
 * zaznaczona domyślnie i „Połącz” wysyła wybrany kontrakt; czytelnik bez
 * prawa zapisu nie widzi „Połącz…”. Dane zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), showToast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { UnlinkedCardsPanel, contractLabel } from "@/components/care/UnlinkedCardsPanel";
import type { UnlinkedTechCards } from "@/lib/api/care";

const suggestion = {
  id: 41,
  candidate_name: "Anna Przykładowa",
  start_date: "2026-01-01",
  end_date: null,
  status: "active",
};
const other = {
  id: 42,
  candidate_name: "Jan Testowy",
  start_date: "2025-02-01",
  end_date: "2025-12-31",
  status: "ended",
};

function payload(overrides: Partial<UnlinkedTechCards> = {}): UnlinkedTechCards {
  return {
    items: [
      {
        id: 7,
        interview_on: "2026-08-10",
        person_name: "Anna Przykładowa",
        area: "Płatności",
        author: "Opiekun Testowy",
        is_draft: false,
        skills: ["Kotlin"],
        unrecognized_skills: ["platforma x"],
        suggestions: [suggestion],
      },
      {
        id: 8,
        interview_on: "2026-07-01",
        person_name: "Nikt Taki",
        area: null,
        author: null,
        is_draft: true,
        skills: [],
        unrecognized_skills: [],
        suggestions: [],
      },
    ],
    contracts: [suggestion, other],
    can_link: true,
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <UnlinkedCardsPanel clientId={3} />
    </QueryClientProvider>,
  );
}

describe("UnlinkedCardsPanel", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.showToast.mockReset();
  });

  it("nie pokazuje niczego, gdy wszystkie karty są połączone", async () => {
    mocks.get.mockResolvedValue({ data: payload({ items: [] }) });
    const { container } = renderPanel();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria odczytu mówi o sobie zamiast pustki", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać kart do połączenia.",
    );
  });

  it("łączy kartę z zaznaczoną propozycją", async () => {
    mocks.get.mockResolvedValue({ data: payload() });
    mocks.post.mockResolvedValue({ data: { id: 7, contract_id: 41 } });
    renderPanel();
    const user = userEvent.setup();
    expect(await screen.findByText("Karty z Compassa do połączenia (2)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pokaż karty" }));
    expect(screen.getByText("Brak kontraktu z tym nazwiskiem u klienta")).toBeInTheDocument();
    expect(screen.getByText(`Propozycja: ${contractLabel(suggestion)}`)).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Połącz…" })[0]);
    expect(screen.getByRole("radio", { name: contractLabel(suggestion) })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Połącz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/care/tech-cards/7/link", { contract_id: 41 }),
    );
    expect(mocks.showToast).toHaveBeenCalledWith("Karta połączona z kontraktem", "success");
  });

  it("czytelnik bez prawa zapisu widzi listę bez „Połącz…”", async () => {
    mocks.get.mockResolvedValue({ data: payload({ can_link: false }) });
    renderPanel();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Pokaż karty" }));
    expect(screen.getByText("Nikt Taki")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Połącz…" })).not.toBeInTheDocument();
  });

  it("etykieta kontraktu: osoba, okres i status, bez stawek", () => {
    expect(contractLabel(other)).toBe("Jan Testowy · 01.02.2025 – 31.12.2025 · Zakończony");
    expect(contractLabel({ ...suggestion, candidate_name: null })).toContain("bezterminowo");
  });
});
