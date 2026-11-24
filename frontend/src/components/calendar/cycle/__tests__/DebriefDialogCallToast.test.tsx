/**
 * Dymek „rozmowa u klienta skończyła się … Zapisz debrief” nie może zasłaniać
 * stopki okna debriefu tej rozmowy (24.11.2026: przy 1280 × 720 dymek z prawego
 * dolnego rogu leżał na przycisku „Zapisz debrief” w oknie).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  },
}));

import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";
import { ToastProvider, useToast } from "@/components/Toast";
import { callToastKey, isDebriefOpen } from "@/lib/interview-notifications";

const START = "2026-11-24T11:00:00Z";
const NOW = new Date("2026-11-24T12:20:00Z");

let toastApi: ReturnType<typeof useToast> | null = null;
function ToastSpy() {
  toastApi = useToast();
  return null;
}

function Screen({ open, eventId = 44 }: { open: boolean; eventId?: number }) {
  return (
    <DebriefDialog
      open={open}
      onOpenChange={vi.fn()}
      eventId={eventId}
      title="Debrief po rozmowie u klienta"
      interviewStart={START}
      now={NOW}
    />
  );
}

function renderScreen(open: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (isOpen: boolean) => (
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <ToastSpy />
        <Screen open={isOpen} />
      </ToastProvider>
    </QueryClientProvider>
  );
  const view = render(ui(open));
  return { rerender: (isOpen: boolean) => view.rerender(ui(isOpen)) };
}

function showCallToast(eventId: number) {
  act(() =>
    toastApi!.showActionToast(`Anna (Klient Alfa): rozmowa u klienta skończyła się. Na telefon zostało 9 min.`, {
      actionLabel: "Zapisz debrief",
      onAction: vi.fn(),
      key: callToastKey(eventId),
    }),
  );
}

describe("DebriefDialog a dymek telefonu po rozmowie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: null });
  });

  it("otwarcie okna zamyka dymek tej rozmowy, inne dymki zostają", async () => {
    const { rerender } = renderScreen(false);
    showCallToast(44);
    showCallToast(45);
    act(() => toastApi!.showActionToast("Wiadomość wysłana", { actionLabel: "Cofnij", onAction: vi.fn() }));
    expect(screen.getAllByText(/rozmowa u klienta skończyła się/)).toHaveLength(2);

    rerender(true);
    await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });

    expect(screen.getAllByText(/rozmowa u klienta skończyła się/)).toHaveLength(1);
    expect(screen.getByText("Wiadomość wysłana")).toBeInTheDocument();
  });

  it("otwarte okno zgłasza się, więc dymek tej rozmowy już nie wychodzi; po zamknięciu znów może", async () => {
    const { rerender } = renderScreen(true);
    await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });
    expect(isDebriefOpen(44)).toBe(true);
    expect(isDebriefOpen(45)).toBe(false);

    rerender(false);
    expect(isDebriefOpen(44)).toBe(false);
  });
});
