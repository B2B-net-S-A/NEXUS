/**
 * Pasek akcji zbiorczych: „Oznacz zakończone" wysyła powód i datę, a odmowa
 * serwera zostaje na ekranie.
 *
 * Do 09.2026 `bulkMarkEnded` nie miało `catch`, a `finally` zamykało okno
 * niezależnie od wyniku: odrzucona partia (umowa `void` w zaznaczeniu → 409)
 * kończyła się zamkniętym dialogiem i niezmienioną listą, bez słowa
 * wyjaśnienia. Operacja jest atomowa, więc odmowa MUSI być widoczna.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// `vi.mock` jest hoistowane ponad zmienne modułu, więc mock musi powstać
// wewnątrz `vi.hoisted` — inaczej fabryka sięga po niezainicjalizowaną stałą.
const { bulkMarkEnded } = vi.hoisted(() => ({ bulkMarkEnded: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    default: { post: vi.fn() },
    contractsApi: { ...actual.contractsApi, bulkMarkEnded },
  };
});

vi.mock("@/components/RequireRole", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { ContractsBulkActionsBarV2 } from "../ContractsBulkActionsBar";

function renderBar() {
  const onDone = vi.fn();
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
    <ContractsBulkActionsBarV2
      selectedIds={new Set([7, 9])}
      onClear={vi.fn()}
      onDone={onDone}
      onSelectAllVisible={vi.fn()}
      visibleCount={12}
    />
    </QueryClientProvider>,
  );
  return { onDone };
}

function fillAndSubmit() {
  fireEvent.click(screen.getByRole("button", { name: /Oznacz zakończone/ }));
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "project_ended" },
  });
  fireEvent.change(document.querySelector('input[type="date"]')!, {
    target: { value: "2026-10-31" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zakończ" }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => cleanup());

describe("ContractsBulkActionsBarV2 — Oznacz zakończone", () => {
  it("wysyła zaznaczone id wraz z powodem i datą", async () => {
    bulkMarkEnded.mockResolvedValue({ data: { requested: 2, changed: 2 } });
    const { onDone } = renderBar();

    fillAndSubmit();

    await waitFor(() =>
      expect(bulkMarkEnded).toHaveBeenCalledWith([7, 9], {
        termination_reason: "project_ended",
        terminated_at: "2026-10-31",
        termination_lessons: null,
        agreement_termination: null,
      }),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onDone.mock.calls[0][0]).toContain("2");
  });

  it("zostawia okno otwarte i pokazuje odmowę serwera", async () => {
    bulkMarkEnded.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: { message: "Illegal contract status transition" } },
      },
    });
    const { onDone } = renderBar();

    fillAndSubmit();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Illegal contract status transition",
      ),
    );
    // Okno zostaje otwarte — użytkownik widzi, czego dyspozycja dotyczyła.
    expect(screen.getByRole("button", { name: "Zakończ" })).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });
});
