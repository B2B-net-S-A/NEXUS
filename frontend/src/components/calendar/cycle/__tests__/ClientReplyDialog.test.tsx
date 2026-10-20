/**
 * „Odpisz klientowi” (0487): gotowy tekst, „Wysłane klientowi” i „Klient
 * wybrał inny termin” (przestawienie rozmowy na inny termin z wniosku).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientReplyDialog } from "@/components/calendar/cycle/ClientReplyDialog";
import { clientReplyText } from "@/lib/client-reply";
import type { PairInfo, SlotRequest } from "@/lib/interview-cycle";

const mocks = vi.hoisted(() => ({
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
  clientReplied: vi.fn(),
  changeSlot: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/lib/api/interviewCycle", () => ({
  interviewCycleApi: { clientReplied: mocks.clientReplied, changeSlot: mocks.changeSlot },
}));
vi.mock("@/store/auth", async (orig) => {
  const real = await orig<typeof import("@/store/auth")>();
  return {
    ...real,
    useAuthStore: (sel: (s: { user: unknown }) => unknown) => sel({ user: { id: 2, name: "Ewa DL" } }),
  };
});

const pair: PairInfo = {
  candidate_id: 5,
  candidate_name: "Anna Test",
  candidate_email: null,
  job_id: 9,
  job_title: "Java Dev",
  client_id: 3,
  client_name: "Klient",
};

const request: SlotRequest = {
  id: 11,
  status: "confirmed",
  slots: [
    { start: "2031-06-12T12:30:00Z", end: "2031-06-12T13:15:00Z" },
    {
      start: new Date(2031, 5, 13, 9, 0).toISOString(),
      end: new Date(2031, 5, 13, 9, 45).toISOString(),
      window_end: new Date(2031, 5, 13, 12, 0).toISOString(),
    },
  ],
  chosen_index: 0,
  respond_by: null,
  recruiter_id: 7,
  created_by: 2,
  duration_minutes: 45,
  note: null,
  event_id: 99,
  client_reply_pending: true,
};

function renderDialog(onInvalidate = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ClientReplyDialog open onOpenChange={() => {}} pair={pair} request={request} onInvalidate={onInvalidate} />
    </QueryClientProvider>,
  );
  return screen.getByRole("dialog", { name: "Odpisz klientowi" });
}

describe("ClientReplyDialog", () => {
  beforeEach(() => {
    mocks.clientReplied.mockReset().mockResolvedValue({});
    mocks.changeSlot.mockReset().mockResolvedValue({});
  });

  it("tekst z terminem i podpisem; „Wysłane klientowi” odhacza odpowiedź", async () => {
    const onInvalidate = vi.fn();
    const dialog = renderDialog(onInvalidate);
    const text = within(dialog).getByLabelText("Odpowiedź do klienta") as HTMLTextAreaElement;
    expect(text.value).toContain("(kandydat: Anna Test)");
    expect(text.value).toContain(", 45 min.");
    expect(text.value.trim().endsWith("Ewa DL")).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Wysłane klientowi" }));
    await waitFor(() => expect(mocks.clientReplied).toHaveBeenCalledWith(11));
    expect(onInvalidate).toHaveBeenCalled();
  });

  it("„Klient wybrał inny termin” przestawia rozmowę na godzinę w oknie", async () => {
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Klient wybrał inny termin…" }));
    fireEvent.click(within(dialog).getByRole("radio"));
    fireEvent.change(within(dialog).getByLabelText("Godzina"), { target: { value: "10:15" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Przestaw rozmowę" }));
    await waitFor(() =>
      expect(mocks.changeSlot).toHaveBeenCalledWith(11, {
        index: 1,
        start: new Date(2031, 5, 13, 10, 15).toISOString(),
      }),
    );
    expect(mocks.clientReplied).not.toHaveBeenCalled();
  });
});

describe("clientReplyText", () => {
  it("dzień i godzina w czasie firmy, bez podpisu gdy go nie ma", () => {
    const text = clientReplyText({
      candidateName: "Jan Test",
      start: "2031-06-12T12:30:00Z",
      durationMinutes: 60,
      signature: null,
    });
    expect(text).toContain("14:30");
    expect(text).toContain(", 60 min.");
    expect(text.trim().endsWith("Pozdrawiam")).toBe(true);
  });
});
