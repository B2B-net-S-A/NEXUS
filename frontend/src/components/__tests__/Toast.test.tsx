import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "@/components/Toast";

function ToastHarness({ onAction = vi.fn() }: { onAction?: () => void }) {
  const { showActionToast, showError, showSuccess } = useToast();

  return (
    <>
      <button type="button" onClick={() => showError("Nie udało się zapisać")}>
        Pokaż błąd
      </button>
      <button type="button" onClick={() => showSuccess("Zapisano zmiany")}>
        Pokaż sukces
      </button>
      <button
        type="button"
        onClick={() =>
          showActionToast("Wiadomość wysłana", {
            actionLabel: "Cofnij",
            onAction,
          })
        }
      >
        Pokaż akcję
      </button>
    </>
  );
}

describe("ToastProvider accessibility", () => {
  it("announces errors assertively and exposes a 44px close target", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Pokaż błąd" }));

    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
    expect(alert).toHaveAttribute("aria-atomic", "true");
    expect(alert).toHaveTextContent("Nie udało się zapisać");

    const close = within(alert).getByRole("button", {
      name: "Zamknij powiadomienie",
    });
    expect(close).toHaveClass("min-h-11", "min-w-11");

    await user.click(close);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("announces success and action toasts politely with 44px controls", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <ToastProvider>
        <ToastHarness onAction={onAction} />
      </ToastProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Pokaż sukces" }));

    const success = screen.getByRole("status");
    expect(success).toHaveAttribute("aria-live", "polite");
    expect(success).toHaveAttribute("aria-atomic", "true");
    await user.click(
      within(success).getByRole("button", {
        name: "Zamknij powiadomienie",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Pokaż akcję" }));

    const action = screen.getByRole("status");
    const actionButton = within(action).getByRole("button", { name: "Cofnij" });
    const close = within(action).getByRole("button", {
      name: "Zamknij powiadomienie",
    });
    expect(action).toHaveAttribute("aria-live", "polite");
    expect(action).toHaveAttribute("aria-atomic", "true");
    expect(actionButton).toHaveClass("min-h-11", "min-w-11");
    expect(close).toHaveClass("min-h-11", "min-w-11");

    await user.click(actionButton);
    expect(onAction).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});


it("cleans up success, error and action timers when unmounted", () => {
  vi.useFakeTimers();
  try {
    const view = render(<ToastProvider><ToastHarness /></ToastProvider>);
    for (const name of ["Pokaż sukces", "Pokaż błąd", "Pokaż akcję"]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }
    expect(vi.getTimerCount()).toBe(3);
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Zamknij powiadomienie" }));
    expect(vi.getTimerCount()).toBe(2);
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.queryByText("Zapisano zmiany")).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
  }
});

// Runda 13 (FRONTB): komunikat, który nie jest błędem („Brak rekrutacji do
// wysłania…”), nie może udawać awarii — osobny wariant informacyjny.
function InfoHarness() {
  const { showInfo } = useToast();
  return (
    <button type="button" onClick={() => showInfo("Brak rekrutacji do wysłania w shortliście.")}>
      Pokaż informację
    </button>
  );
}

describe("ToastProvider info variant", () => {
  it("announces info politely as status, never as alert, with token colours", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <InfoHarness />
      </ToastProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Pokaż informację" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const info = screen.getByRole("status");
    expect(info).toHaveAttribute("aria-live", "polite");
    expect(info).toHaveAttribute("aria-atomic", "true");
    expect(info).toHaveTextContent("Brak rekrutacji do wysłania w shortliście.");
    expect(info).toHaveClass("bg-info-muted", "text-info-muted-foreground");
    expect(info.className).not.toMatch(/destructive|red-|emerald-/);

    await user.click(within(info).getByRole("button", { name: "Zamknij powiadomienie" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps info on screen longer than success but shorter than an error", () => {
    vi.useFakeTimers();
    try {
      render(<ToastProvider><InfoHarness /></ToastProvider>);
      fireEvent.click(screen.getByRole("button", { name: "Pokaż informację" }));
      act(() => vi.advanceTimersByTime(3000));
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => vi.advanceTimersByTime(2000));
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
