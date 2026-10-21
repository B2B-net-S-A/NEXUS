/**
 * „Zamknij rekrutację” w profilu klienta — to samo ostrzeżenie o osobach
 * w toku co w oknie rekrutacji (13.10.2026), bo woła tę samą trasę; od
 * 21.10.2026 te same trzy grupy powodów (start: „Przegraliśmy”).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ post: vi.fn(), showError: vi.fn(), showSuccess: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: vi.fn() },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
  jobsApi: {
    close: (...a: unknown[]) => mocks.post(...a),
    list: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import { CloseJobAsLostModal } from "@/components/client-profile/actions/CloseJobAsLostModal";

describe("CloseJobAsLostModal — osoby w toku", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pokazuje osoby w toku i zamyka dopiero z potwierdzeniem", async () => {
    mocks.post
      .mockRejectedValueOnce(
        Object.assign(new Error("HTTP 409"), {
          response: {
            status: 409,
            data: {
              detail: {
                code: "active_cards_warning",
                message: "W tej rekrutacji są 2 osoby w toku (ostatni ruch karty 12.10.2026). Zamknięcie nie zamyka kart — zostaną w zamkniętej rekrutacji.",
                active_cards: 2,
                columns: { cv_sent: 2 },
              },
            },
          },
        }),
      )
      .mockResolvedValueOnce({ data: {} });
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CloseJobAsLostModal jobId={7} jobTitle="Analityk" clientId={3} onClose={onClose} />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("W tej rekrutacji są 2 osoby w toku");
    expect(alert).toHaveTextContent("CV wysłane 2");
    expect(mocks.post).toHaveBeenCalledWith(7, "competitor", "", false, null);
    expect(onClose).not.toHaveBeenCalled();
    expect(mocks.showError).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Zamknij mimo to" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mocks.post).toHaveBeenLastCalledWith(7, "competitor", "", true, null);
  });
});

describe("CloseJobAsLostModal — powód poza hit ratio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("„Nie liczy się” bez uzasadnienia nie zamyka", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CloseJobAsLostModal jobId={7} jobTitle="Analityk" clientId={3} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByTestId("close-group-neutral"));
    expect(screen.getByRole("button", { name: "Zamknij rekrutację" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Uzasadnienie *"), { target: { value: "Duplikat" } });
    expect(screen.getByRole("button", { name: "Zamknij rekrutację" })).toBeEnabled();
  });
});
