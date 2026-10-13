/**
 * Zamknięcie rekrutacji z osobami w toku (13.10.2026).
 *
 * Zamknięcie nie rusza kart. 12.10.2026 duplikat requestu zamknięto z pięcioma
 * kartami w toku i okno nic o nich nie mówiło — serwer zatrzymuje teraz
 * pierwsze zamknięcie ostrzeżeniem, a okno pokazuje liczby i pyta drugi raz.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ close: vi.fn(), showError: vi.fn(), showSuccess: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
  jobsApi: { close: (...a: unknown[]) => mocks.close(...a) },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";

const WARNING = Object.assign(new Error("HTTP 409"), {
  response: {
    status: 409,
    data: {
      detail: {
        code: "active_cards_warning",
        message:
          "W tej rekrutacji jest 5 osób w toku (ostatni ruch karty 12.10.2026). Zamknięcie nie zamyka kart — zostaną w zamkniętej rekrutacji.",
        active_cards: 5,
        columns: { screening: 2, new: 3 },
        last_moved_at: "2026-10-12T12:05:25+00:00",
      },
    },
  },
});

function renderDialog() {
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <JobCloseWithReasonDialog open onOpenChange={onOpenChange} jobId={7} jobTitle="Analityk" defaultReason="other" />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

describe("JobCloseWithReasonDialog — osoby w toku", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ostrzeżenie zostawia okno otwarte z liczbami, a drugie kliknięcie zamyka z potwierdzeniem", async () => {
    mocks.close.mockRejectedValueOnce(WARNING).mockResolvedValueOnce({ data: {} });
    const { onOpenChange } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("W tej rekrutacji jest 5 osób w toku");
    // Kolejność kolumn Tablicy, nie kolejność z odpowiedzi.
    expect(alert).toHaveTextContent("Nowi 3 · Screening 2");
    expect(mocks.close).toHaveBeenCalledWith(7, "other", "");
    expect(mocks.showError).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);

    fireEvent.click(screen.getByRole("button", { name: "Zamknij mimo to" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.close).toHaveBeenLastCalledWith(7, "other", "", true);
  });

  it("bez osób w toku zamyka od razu", async () => {
    mocks.close.mockResolvedValue({ data: {} });
    const { onOpenChange } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.close).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("inna odmowa idzie toastem z treścią serwera", async () => {
    mocks.close.mockRejectedValue(new Error("Rekrutacja jest już zamknięta."));
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Rekrutacja jest już zamknięta."));
    expect(screen.queryByRole("button", { name: "Zamknij mimo to" })).not.toBeInTheDocument();
  });
});
