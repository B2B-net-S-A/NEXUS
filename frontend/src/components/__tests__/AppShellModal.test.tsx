import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  AddClientModal,
  EditCandidateModal,
} from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

/**
 * Kontrakt dostępności shella modali z `AppShell.tsx`. `AddClientModal` jest tu
 * tylko najtańszym reprezentantem — wszystkie 8 modali dzieli ten sam `<Modal>`,
 * więc te asercje pilnują ich wszystkich naraz.
 */

/** Trigger + warunkowo montowany modal — jak u realnych konsumentów. */
function Harness({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Otwórz
      </button>
      {open && (
        <AddClientModal
          onClose={() => {
            setOpen(false);
            onClose?.();
          }}
          onSuccess={() => {}}
        />
      )}
    </>
  );
}

describe("AppShell <Modal> — a11y", () => {
  it("wystawia role=dialog + aria-modal i nazwę dostępną z nagłówka", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // aria-labelledby spięte z tytułem — wcześniej <h2> nie było z niczym powiązane.
    expect(dialog).toHaveAccessibleName("Dodaj firmę");
  });

  it("daje przyciskowi zamknięcia nazwę dostępną (nie samą ikonę)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));
    await screen.findByRole("dialog");

    expect(screen.getByRole("button", { name: "Zamknij" })).toBeInTheDocument();
  });

  it("przenosi fokus do modala i trzyma go w środku (pułapka fokusu)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Otwórz" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog");
    const focused = () => document.activeElement as HTMLElement | null;
    await waitFor(() => expect(dialog).toContainElement(focused()));

    // Kilkanaście tabów nie może wyprowadzić fokusu poza dialog.
    for (let i = 0; i < 15; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(focused());
    }
    expect(document.activeElement).not.toBe(trigger);
  });

  it("zamyka na Escape i przywraca fokus na element wyzwalający", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const trigger = screen.getByRole("button", { name: "Otwórz" });
    await user.click(trigger);
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    // Bez przywrócenia fokusu użytkownik klawiatury lądował na <body>.
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("zamyka po kliknięciu „Zamknij”", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Zamknij" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("zachowuje układ sprzed migracji (brak regresji wizualnej)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));

    const panel = await screen.findByRole("dialog");
    const overlay = panel.parentElement as HTMLElement;

    // Tylko klasy niosące układ — reszta wyglądu może się zmieniać bez
    // rozbijania testu. Overlay musi zostać kontenerem przewijania, bo to on
    // (a nie panel) trzyma wysokie modale w kadrze.
    for (const cls of [
      "fixed",
      "inset-0",
      "bg-black/50",
      "z-100",
      "overflow-y-auto",
      "items-end", // sheet na mobile…
      "sm:items-center", // …wyśrodkowany na desktopie
    ]) {
      expect(overlay.classList.contains(cls), `overlay: ${cls}`).toBe(true);
    }

    for (const cls of [
      "rounded-b-none", // dolne rogi tylko na mobile (sheet)
      "sm:rounded-b-2xl",
      "sm:max-w-2xl", // `wide` → szerszy panel
      // Treść radixa jest fokusowalna (tabindex=-1); bez tego przeglądarka
      // rysowałaby ring wokół całego panelu zaraz po otwarciu.
      "focus:outline-hidden",
    ]) {
      expect(panel.classList.contains(cls), `panel: ${cls}`).toBe(true);
    }
  });

  it("NIE zamyka się po kliknięciu w tło (zachowanie sprzed migracji na radix)", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));

    const dialog = await screen.findByRole("dialog");
    const overlay = dialog.parentElement as HTMLElement;
    await user.click(overlay);

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("EditCandidateModal — profile rate boundary", () => {
  it("does not expose or submit the OCC-managed profile rate", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({
      data: [],
    } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={{
            id: 7,
            name: "Jan",
            lastname: "Kowalski",
            expected_rate_hourly: "160.00",
            expected_rate_currency: "PLN",
          }}
          onClose={() => {}}
          onSuccess={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(
      screen.queryByText(/Stawka B2B.*PLN netto\/h/i),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.patch).mock.calls[0]?.[1] as Record<
      string,
      unknown
    >;
    expect(payload).not.toHaveProperty("expected_rate_hourly");
    expect(payload).not.toHaveProperty("expected_rate_currency");
  });
});
