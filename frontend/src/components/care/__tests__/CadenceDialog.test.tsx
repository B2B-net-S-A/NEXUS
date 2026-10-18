/**
 * „Rytm kontaktu” (M2): zapis wymaga poziomu i powodu, „do kiedy” jest
 * opcjonalne, podgląd zmiany przychodzi z serwera, czytelnik bez prawa
 * zmiany nie ma „Zapisz rytm”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

// Lista wyboru Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { CadenceDialog } from "@/components/care/CadenceDialog";
import type { ContractCadence } from "@/lib/api/care";

function cadence(overrides: Partial<ContractCadence> = {}): ContractCadence {
  return {
    contract_id: 5,
    candidate_name: "Adam Przykładowy",
    client_name: "Bank Przykładowy",
    start_date: "2023-03-01",
    end_date: "2027-01-31",
    is_live: true,
    owner: { id: 7, name: "Natalia Opiekuńcza" },
    manager: { id: 4, name: "Katarzyna Kierownicza", position: null, area: null },
    current: {
      level: "monthly",
      source: "default",
      starts_on: null,
      until_on: null,
      returns_to: null,
      reason: null,
      note: null,
      author: null,
    },
    history: [
      { on: "2023-03-01", kind: "start", level: "biweekly", reason: null, note: null, until_on: null, author: null, future: false },
      { on: "2023-05-30", kind: "program_end", level: "monthly", reason: null, note: null, until_on: null, author: null, future: false },
    ],
    upcoming: [{ due_on: "2026-10-29", kind: "cadence", label: "Rozmowa według rytmu" }],
    signals: [{ kind: "weak_feedback", average: 2.7, on: "2026-10-15" }],
    suggested_level: "biweekly",
    preview: null,
    can_edit: true,
    ...overrides,
  };
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CadenceDialog contractId={5} open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
});

describe("CadenceDialog", () => {
  it("bez powodu nie zapisuje; z powodem wysyła rytm bez daty końca", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockImplementation((_url: string, config?: { params?: Record<string, string> }) =>
      Promise.resolve({
        data: config?.params?.level
          ? cadence({
              preview: {
                level: "biweekly",
                until_on: null,
                returns_to: null,
                upcoming: [
                  { due_on: "2026-10-31", kind: "cadence", label: "Rozmowa według rytmu" },
                  { due_on: "2026-11-14", kind: "cadence", label: "Rozmowa według rytmu" },
                ],
                owner_month: {
                  owner: { id: 7, name: "Natalia Opiekuńcza" },
                  month: "2026-11-01",
                  before: 47,
                  after: 49,
                },
              },
            })
          : cadence(),
      }),
    );
    mocks.post.mockResolvedValue({ data: cadence() });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/opinia 2,7 \/ 5 — podpowiedź: co 2 tygodnie/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Co miesiąc · automatycznie po 90 dniach")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Zapisz rytm" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz, jak często rozmawiamy.");

    await user.click(within(dialog).getByRole("radio", { name: "Co 2 tygodnie" }));
    expect(await within(dialog).findByText("49 rozmów zamiast 47")).toBeInTheDocument();
    expect(within(dialog).getByText(/Natalia Opiekuńcza\) · listopad 2026/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenLastCalledWith("/api/care/contracts/5/cadence", {
      params: { level: "biweekly" },
    });
    await user.click(within(dialog).getByRole("button", { name: "Zapisz rytm" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz powód zmiany.");
    expect(mocks.post).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("combobox", { name: /Powód/ }));
    await user.click(await screen.findByRole("option", { name: "Słaba opinia menedżera u klienta" }));
    await user.type(within(dialog).getByLabelText(/Notatka/), "Przez dwa miesiące częściej.");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz rytm" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0]).toEqual([
      "/api/care/contracts/5/cadence",
      {
        level: "biweekly",
        reason: "weak_feedback",
        note: "Przez dwa miesiące częściej.",
        until_on: null,
      },
    ]);
  });

  it("czytelnik bez prawa zmiany widzi rytm i historię, bez „Zapisz rytm”", async () => {
    mocks.get.mockResolvedValue({ data: cadence({ can_edit: false }) });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Rytm zmienia opiekun kontraktu/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Zapisz rytm" })).not.toBeInTheDocument();
  });
});
