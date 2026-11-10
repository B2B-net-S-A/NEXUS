/** Podsumowanie spotkania na karcie szansy i okno maila do klienta. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientMailDraft, TimelineItem } from "@/lib/api/sales";

let draft: ClientMailDraft;
let draftState: { isLoading: boolean; error: Error | null; isSuccess: boolean } = {
  isLoading: false,
  error: null,
  isSuccess: true,
};
const send = vi.fn();
const askConfirm = vi.fn();
const toast = {
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
  showToast: vi.fn(),
  showActionToast: vi.fn(),
};

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useClientMailDraft: () => ({
    data: draftState.isSuccess ? draft : undefined,
    ...draftState,
    refetch: vi.fn(),
  }),
  useSendClientMail: () => ({ mutate: send, isPending: false }),
}));

import { MeetingClientMailDialog } from "../MeetingClientMailDialog";
import { MeetingSummary } from "../OpportunityTimeline";
import { initialRecipients, parseAddresses, riskyFragments } from "../client-mail";

beforeEach(() => {
  vi.clearAllMocks();
  askConfirm.mockResolvedValue(true);
  draftState = { isLoading: false, error: null, isSuccess: true };
  draft = {
    subject: "Podsumowanie spotkania: Wdrożenie",
    body: "Dziękujemy za spotkanie.\nUstalenia:\n- demo w piątek",
    model_failed: false,
    recipients: [
      { address: "klient@firma.pl", name: "Osoba Klienta", blocked: null },
      { address: "kandydat@firma.pl", name: "Osoba z bazy", blocked: "candidate" },
    ],
    mailbox: "ok",
    sender_address: "handlowiec@nasza.pl",
    sent_at: null,
  };
});

function open() {
  return render(<MeetingClientMailDialog activityId={5} opportunityId={9} onClose={vi.fn()} />);
}

describe("Pomocnicze reguły maila do klienta", () => {
  it("domyślnie bierze uczestników spoza firmy bez osób z bazy kandydatów", () => {
    expect(initialRecipients(draft)).toEqual(["klient@firma.pl"]);
  });

  it("rozdziela adresy i odrzuca to, co adresem nie jest", () => {
    expect(parseAddresses(" A@Firma.pl; b@firma.pl, a@firma.pl nie-adres ")).toEqual({
      valid: ["a@firma.pl", "b@firma.pl"],
      invalid: ["nie-adres"],
    });
  });

  it("ostrzega przed kwotami i stawkami, nie przed ogólnym „kandydatów”", () => {
    expect(riskyFragments("Stawka 150 zł/h, marża 20%, przedstawimy kandydatów")).toEqual([
      "150 zł",
      "Stawka",
      "marża",
    ]);
    expect(riskyFragments("Dziękujemy za spotkanie. Demo w piątek o 10:00.")).toEqual([]);
  });
});

describe("Okno „Podsumowanie dla klienta”", () => {
  it("wysyła poprawioną treść do wybranych adresatów po potwierdzeniu, z jednym kluczem", async () => {
    open();
    expect(screen.getByText("Osoba Klienta")).toBeInTheDocument();
    expect(screen.getByText(/Pominięci, bo są w bazie kandydatów: Osoba z bazy/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Dodaj adres"), {
      target: { value: "drugi@firma.pl" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    fireEvent.change(screen.getByLabelText("Treść"), { target: { value: "Dziękujemy. Demo w piątek." } });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));

    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    expect(askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ description: expect.stringContaining("klient@firma.pl, drugi@firma.pl") }),
    );
    const payload = send.mock.calls[0][0];
    expect(payload).toMatchObject({
      activityId: 5,
      opportunity_id: 9,
      to: ["klient@firma.pl", "drugi@firma.pl"],
      body: "Dziękujemy. Demo w piątek.",
      subject: "Podsumowanie spotkania: Wdrożenie",
    });
    expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("nie wysyła bez potwierdzenia", async () => {
    askConfirm.mockResolvedValue(false);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(send).not.toHaveBeenCalled();
  });

  it("nie dodaje ręcznie adresu z bazy kandydatów", () => {
    open();
    fireEvent.change(screen.getByPlaceholderText("Dodaj adres"), {
      target: { value: "kandydat@firma.pl" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    expect(screen.getByText(/Ten adres jest w bazie kandydatów/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuń kandydat@firma.pl" })).toBeNull();
  });

  it("po awarii modelu zostawia puste pole do napisania ręcznie", () => {
    draft = { ...draft, body: "", model_failed: true };
    open();
    expect(screen.getByText(/Szkic nie powstał/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Treść"), { target: { value: "Dziękujemy za spotkanie." } });
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeEnabled();
  });

  it("bez skrzynki z wysyłką mówi, co zrobić, i blokuje „Wyślij”", () => {
    draft = { ...draft, mailbox: "no_send_scope" };
    open();
    expect(screen.getByRole("alert")).toHaveTextContent("Połącz skrzynkę Outlook ponownie");
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
  });

  it("ostrzega o kwocie w treści i o poprzedniej wysyłce", () => {
    draft = { ...draft, body: "Stawka 150 zł/h", sent_at: "2026-11-09T10:00:00Z" };
    open();
    expect(screen.getByRole("status")).toHaveTextContent("150 zł");
    expect(screen.getByText(/wyszło już/)).toBeInTheDocument();
  });

  it("błąd szkicu nie wygląda jak puste okno", () => {
    draftState = { isLoading: false, error: Object.assign(new Error("boom"), { response: { status: 500 } }), isSuccess: false };
    open();
    expect(screen.queryByRole("button", { name: "Wyślij" })).toBeNull();
    expect(screen.getByRole("button", { name: /Spróbuj/ })).toBeInTheDocument();
  });
});

describe("Podsumowanie spotkania na osi szansy", () => {
  const meeting = {
    id: 3,
    kind: "meeting",
    transcript_activity_id: 5,
    transcript_summary: "Ustalono demo w piątek.",
    can_send_client_summary: true,
    client_mail_sent_at: null,
  } as unknown as TimelineItem;

  it("pokazuje podsumowanie i przyciski organizatorowi", () => {
    const onTranscript = vi.fn();
    const onClientMail = vi.fn();
    render(<MeetingSummary item={meeting} open={false} canEdit onTranscript={onTranscript} onClientMail={onClientMail} />);
    expect(screen.getByText("Ustalono demo w piątek.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Transkrypt" }));
    fireEvent.click(screen.getByRole("button", { name: "Podsumowanie dla klienta" }));
    expect(onTranscript).toHaveBeenCalledWith(5);
    expect(onClientMail).toHaveBeenCalledWith(5);
  });

  it("bez prawa wysyłki zostaje samo podsumowanie i transkrypt", () => {
    render(
      <MeetingSummary
        item={{ ...meeting, can_send_client_summary: false }}
        open={false}
        canEdit
        onTranscript={vi.fn()}
        onClientMail={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Transkrypt" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Podsumowanie dla klienta" })).toBeNull();
  });

  it("spotkanie bez transkryptu nie dostaje bloku", () => {
    const { container } = render(
      <MeetingSummary
        item={{ ...meeting, transcript_activity_id: null }}
        open={false}
        canEdit
        onTranscript={vi.fn()}
        onClientMail={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
