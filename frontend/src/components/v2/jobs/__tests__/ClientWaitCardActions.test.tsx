import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  responded: vi.fn(),
  ask: vi.fn(),
  showError: vi.fn(),
  showSuccess: vi.fn(),
}));

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: mocks.send, dialogs: null }),
}));
vi.mock("@/lib/api/clientWait", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/clientWait")>("@/lib/api/clientWait");
  return { ...actual, markClientResponded: mocks.responded, prepareClientReminder: vi.fn() };
});
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.ask, confirmDialog: null }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import { ClientWaitCardActions } from "@/components/v2/jobs/ClientWaitCardActions";

const REASONS = [
  { id: "5", label: "Klient nie odpowiedział", name: "client_no_response", applies_to: ["rejected" as const], disqualifies_person: false },
];

function setup(props: Partial<Parameters<typeof ClientWaitCardActions>[0]> = {}) {
  const onInterview = vi.fn();
  const onRejected = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ClientWaitCardActions
        jobId={7}
        candidateId={11}
        candidateName="Anna Nowak"
        workdays={8}
        rejectedStageDefId={90}
        reasons={REASONS}
        onInterview={onInterview}
        onRejected={onRejected}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onInterview, onRejected };
}

describe("ClientWaitCardActions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("„Zamknij — brak odpowiedzi” pyta i idzie ruchem z client_silent, bez maila", async () => {
    mocks.ask.mockResolvedValue(true);
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij — brak odpowiedzi" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.send.mock.calls[0][0]).toMatchObject({
      candidate_id: 11,
      job_id: 7,
      stage_def_id: 90,
      rejection_reason_id: "5",
      ended_by: "client_silent",
      send_rejection_email: false,
    });
  });

  it("anulowanie potwierdzenia nie rusza karty", async () => {
    mocks.ask.mockResolvedValue(false);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij — brak odpowiedzi" }));
    await waitFor(() => expect(mocks.ask).toHaveBeenCalled());
    expect(mocks.send).not.toHaveBeenCalled();
  });

  it("brak powodu w szablonie to komunikat, nie ruch", async () => {
    setup({ reasons: [] });
    fireEvent.click(screen.getByRole("button", { name: "Zamknij — brak odpowiedzi" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalled());
    expect(mocks.send).not.toHaveBeenCalled();
  });

  it("tylko do odczytu: bez przycisków", () => {
    setup({ readOnly: true });
    expect(screen.queryByTestId("client-wait-card-actions")).not.toBeInTheDocument();
  });
});
