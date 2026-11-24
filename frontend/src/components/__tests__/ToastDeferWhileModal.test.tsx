import { act, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFERRED_TOAST_MAX, DEFERRED_TOAST_MAX_AGE_MS, ToastProvider, useToast } from "@/components/Toast";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { isModalOpen } from "@/lib/modal-open";

/**
 * Dymki z gniazda (czat, tematy, rozmowy) wychodziły w dowolnej chwili w prawym
 * dolnym rogu i przy 1280 × 720 leżały na stopce szerokiego okna, czyli na
 * „Zapisz” (24.11.2026). Decyzja Artura: czekają, aż okno się zamknie.
 * Dymki „Cofnij” po własnej akcji użytkownika wychodzą od razu.
 */

let api: ReturnType<typeof useToast>;
let setModal: (open: boolean) => void;

function Harness() {
  api = useToast();
  const [open, setOpen] = useState(false);
  setModal = setOpen;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Debrief</DialogTitle>
        <button type="button">Zapisz debrief</button>
      </DialogContent>
    </Dialog>
  );
}

function renderHarness() {
  render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
}

const socketToast = (message: string, extra: { isStillRelevant?: () => boolean; key?: string } = {}) =>
  act(() =>
    api.showActionToast(message, { actionLabel: "Otwórz", onAction: vi.fn(), deferWhileModal: true, ...extra }),
  );

async function openModal() {
  act(() => setModal(true));
  await screen.findByRole("dialog");
}

async function closeModal() {
  act(() => setModal(false));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

afterEach(() => {
  vi.useRealTimers();
});

describe("dymki z gniazda przy otwartym oknie", () => {
  it("dymek z gniazda czeka, aż okno się zamknie, i wychodzi po zamknięciu", async () => {
    renderHarness();
    await openModal();

    socketToast("Anna: nowa wiadomość w czacie");
    expect(screen.queryByText("Anna: nowa wiadomość w czacie")).not.toBeInTheDocument();

    await closeModal();
    expect(await screen.findByText("Anna: nowa wiadomość w czacie")).toBeInTheDocument();
  });

  it("dymek „Cofnij” po własnej akcji wychodzi od razu, także przy otwartym oknie", async () => {
    renderHarness();
    await openModal();

    act(() => api.showActionToast("Przeniesiono kartę", { actionLabel: "Cofnij", onAction: vi.fn() }));
    expect(screen.getByText("Przeniesiono kartę")).toBeInTheDocument();
  });

  it("dymek z gniazda bez otwartego okna wychodzi od razu", () => {
    renderHarness();
    socketToast("Nowy temat");
    expect(screen.getByText("Nowy temat")).toBeInTheDocument();
  });

  it("informacja z gniazda (bez linku) też czeka na zamknięcie okna", async () => {
    renderHarness();
    await openModal();

    act(() => api.showInfo("Zmiana w rekrutacji", { deferWhileModal: true }));
    expect(screen.queryByText("Zmiana w rekrutacji")).not.toBeInTheDocument();

    await closeModal();
    expect(await screen.findByText("Zmiana w rekrutacji")).toBeInTheDocument();
  });

  it("po zamknięciu okna nie wychodzi dymek, który przestał być aktualny", async () => {
    renderHarness();
    await openModal();
    let relevant = true;
    socketToast("Czat, który już czytam", { isStillRelevant: () => relevant });
    relevant = false;

    await closeModal();
    await act(async () => {});
    expect(screen.queryByText("Czat, który już czytam")).not.toBeInTheDocument();
  });

  it("`dismissToast(key)` zdejmuje też dymek czekający na zamknięcie okna", async () => {
    renderHarness();
    await openModal();
    socketToast("Rozmowa za 15 minut", { key: "interview:7" });
    act(() => api.dismissToast("interview:7"));

    await closeModal();
    await act(async () => {});
    expect(screen.queryByText("Rozmowa za 15 minut")).not.toBeInTheDocument();
  });

  it("po długim oknie wychodzą tylko ostatnie dymki, nie starsze niż limit", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderHarness();
    await openModal();

    socketToast("Stary dymek");
    act(() => vi.advanceTimersByTime(DEFERRED_TOAST_MAX_AGE_MS + 1));
    for (let i = 1; i <= DEFERRED_TOAST_MAX + 1; i += 1) socketToast(`Świeży ${i}`);

    await closeModal();
    expect(await screen.findByText(`Świeży ${DEFERRED_TOAST_MAX + 1}`)).toBeInTheDocument();
    expect(screen.queryByText("Stary dymek")).not.toBeInTheDocument();
    expect(screen.queryByText("Świeży 1")).not.toBeInTheDocument();
    expect(screen.getAllByText(/^Świeży/)).toHaveLength(DEFERRED_TOAST_MAX);
  });
});

describe("isModalOpen", () => {
  it("lista Popover (też `role=\"dialog\"`) nie jest oknem modalnym", async () => {
    render(
      <Popover open>
        <PopoverTrigger>Czat</PopoverTrigger>
        <PopoverContent>Wątki</PopoverContent>
      </Popover>,
    );
    await screen.findByText("Wątki");
    expect(isModalOpen()).toBe(false);
  });

  it("własne okno z `aria-modal` jest oknem modalnym", () => {
    render(
      <div role="dialog" aria-modal="true">
        Przedłuż zamówienie
      </div>,
    );
    expect(isModalOpen()).toBe(true);
  });
});
