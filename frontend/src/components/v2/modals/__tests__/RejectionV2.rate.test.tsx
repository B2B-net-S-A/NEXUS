/**
 * „Za wysokie oczekiwania finansowe” w oknie odrzucenia (prośba Marka,
 * 26.10.2026): pole „Ile teraz chce?” pod powodem, nowe minimum domyślnie
 * zaznaczone (D2), kwota opcjonalna (D1). Wybór idzie w 11. argumencie.
 */

import type * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { mockPost } = vi.hoisted(() => ({ mockPost: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  default: { post: mockPost },
}));

import { rejectionRateMoveFields } from "@/components/v2/modals/RejectionRateField";
import { RejectionV2 } from "@/components/v2/modals/RejectionV2";

const RATE = "Za wysokie oczekiwania finansowe";

const reasons = [
  { id: "3", name: RATE, label: RATE, applies_to: ["rejected" as const] },
  { id: "4", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "5", name: "salary_mismatch", label: "Rozbieżność oczekiwań finansowych", applies_to: ["withdrawn" as const] },
];

function renderRate(props: Partial<React.ComponentProps<typeof RejectionV2>> = {}) {
  const onConfirm = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="internal"
      onConfirm={onConfirm}
      {...props}
    />,
    {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return onConfirm;
}

function typeRate(value: string) {
  fireEvent.change(screen.getByLabelText("Ile teraz chce w złotych na godzinę"), {
    target: { value },
  });
}

describe("RejectionV2 — „Za wysokie oczekiwania finansowe” (26.10.2026)", () => {
  it("pyta o kwotę dopiero po wybraniu tego powodu", () => {
    renderRate();
    expect(screen.queryByTestId("rejection-rate")).toBeNull();
    fireEvent.click(screen.getByText("Brak doświadczenia"));
    expect(screen.queryByTestId("rejection-rate")).toBeNull();
    fireEvent.click(screen.getByText(RATE));
    expect(screen.getByTestId("rejection-rate")).toBeInTheDocument();
  });

  it("wpisana kwota idzie jako nowe minimum, z podglądem zmiany w profilu", () => {
    const onConfirm = renderRate({
      profileRate: { rateFromHourly: 129, rateFromAt: "2026-04-16T10:00:00Z" },
    });
    fireEvent.click(screen.getByText(RATE));
    expect(screen.getByText(/Teraz w profilu: od 129 zł\/h \(04\.2026\)/)).toBeInTheDocument();
    typeRate("150");
    expect(screen.getByText(/Stawka od 129 zł\/h → 150 zł\/h/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][0]).toBe("3");
    expect(onConfirm.mock.calls[0][10]).toEqual({ rateHourly: 150, isMinimum: true });
  });

  it("odznaczone minimum i przecinek w kwocie", () => {
    const onConfirm = renderRate();
    fireEvent.click(screen.getByText(RATE));
    typeRate("152,5");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][10]).toEqual({ rateHourly: 152.5, isMinimum: false });
  });

  it("bez kwoty odrzucenie przechodzi i nic nie zapisuje (D1)", () => {
    const onConfirm = renderRate();
    fireEvent.click(screen.getByText(RATE));
    expect(screen.getByRole("checkbox")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][10]).toBeNull();
  });

  it("kwota niższa niż „Stawka od” ostrzega, ale nie blokuje", () => {
    const onConfirm = renderRate({ profileRate: { rateFromHourly: 130, rateFromAt: null } });
    fireEvent.click(screen.getByText(RATE));
    typeRate("120");
    expect(screen.getByText(/To mniej niż obecna „Stawka od” \(130 zł\/h\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][10]).toEqual({ rateHourly: 120, isMinimum: true });
  });

  it("rezygnacja z „Rozbieżność oczekiwań finansowych” też pyta", () => {
    renderRate({ terminalType: "withdrawn" });
    fireEvent.click(screen.getByText("Rozbieżność oczekiwań finansowych"));
    expect(screen.getByTestId("rejection-rate")).toBeInTheDocument();
  });

  it("przy kilku osobach naraz nie pyta o kwotę", () => {
    mockPost.mockResolvedValue({ data: { people: [] } });
    const onConfirm = renderRate({
      emailPreview: {
        jobId: 1,
        people: [
          { candidateId: 1, name: "Anna Przykładowa" },
          { candidateId: 2, name: "Jan Testowy" },
        ],
      },
    });
    fireEvent.click(screen.getByText(RATE));
    expect(screen.queryByTestId("rejection-rate")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][10]).toBeNull();
  });

  it("osoba od systemu: przy tym powodzie bez drugiego „Ile chce?”", () => {
    renderRate({ autofill: { rateKnown: false, several: false } });
    fireEvent.click(screen.getByText(RATE));
    fireEvent.click(screen.getByText("Za droga"));
    expect(screen.queryByLabelText("Ile chce w złotych na godzinę")).toBeNull();
    expect(screen.getByLabelText("Ile teraz chce w złotych na godzinę")).toBeInTheDocument();
  });
});

describe("rejectionRateMoveFields", () => {
  it("mapuje wybór na pola ruchu, a brak wyboru na nic", () => {
    expect(rejectionRateMoveFields({ rateHourly: 150, isMinimum: true })).toEqual({
      rejection_rate_hourly: 150,
      rejection_rate_is_minimum: true,
    });
    expect(rejectionRateMoveFields(null)).toEqual({});
  });
});
