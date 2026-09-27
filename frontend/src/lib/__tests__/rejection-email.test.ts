/**
 * Runda 9 (R9-N11-2): jedna reguła dostępności maila odrzucenia — lustro
 * `rejection_email_scheduler.previous_is_client_visible` (kod etapu albo
 * kolumna Tablicy), a nie kategoria kolumny.
 */
import { describe, expect, it, vi } from "vitest";

import {
  announceRejectionEmail,
  rejectionEmailAvailableFrom,
  rejectionEmailBulkSkipMessage,
  rejectionEmailSkipMessage,
} from "@/lib/rejection-email";

describe("rejectionEmailAvailableFrom", () => {
  it("„CV wysłane” (kategoria internal) proponuje mail — klient widział CV", () => {
    expect(
      rejectionEmailAvailableFrom({
        stage: "cv_sent",
        category: "internal",
        name: "CV Wysłane",
      })
    ).toBe(true);
  });

  it("etapy rozpoznane po nazwie liczą się kolumną Tablicy", () => {
    expect(
      rejectionEmailAvailableFrom({
        stage: "interview",
        category: "external",
        name: "Po Interview",
      })
    ).toBe(true);
    expect(
      rejectionEmailAvailableFrom({
        stage: "new",
        category: "external",
        name: "Umowa wysłana",
      })
    ).toBe(true);
  });

  it("wewnętrzne etapy i brak etapu nie proponują maila", () => {
    expect(
      rejectionEmailAvailableFrom({ stage: "screening", category: "internal" })
    ).toBe(false);
    expect(
      rejectionEmailAvailableFrom({
        stage: "interview",
        category: "internal",
        name: "QC CV",
      })
    ).toBe(false);
    expect(rejectionEmailAvailableFrom(null)).toBe(false);
  });
});

describe("rejectionEmailSkipMessage", () => {
  it("brak skrzynki mówi, skąd wychodzi mail", () => {
    expect(rejectionEmailSkipMessage("no_mailbox")).toContain("Microsoft 365");
  });

  it("zaplanowany mail i brak statusu nie dają komunikatu", () => {
    expect(rejectionEmailSkipMessage("scheduled")).toBeNull();
    expect(rejectionEmailSkipMessage(null)).toBeNull();
  });

  it("nieznany powód daje ogólne zdanie, nie ciszę", () => {
    expect(rejectionEmailSkipMessage("something_new")).toBe(
      "Mail odrzucenia nie został zaplanowany."
    );
  });
});

// Runda 10 (R10-V2-1): odrzucenie zbiorcze i warsztat rozmów mówią o mailu,
// którego serwer nie zaplanował.
describe("rejectionEmailBulkSkipMessage", () => {
  it("wszystkie zaplanowane albo brak statusu — cisza", () => {
    expect(rejectionEmailBulkSkipMessage(["scheduled", null, undefined])).toBeNull();
  });

  it("jedna osoba — pełne zdanie jak przy ruchu pojedynczym", () => {
    expect(rejectionEmailBulkSkipMessage(["scheduled", "no_mailbox"])).toBe(
      rejectionEmailSkipMessage("no_mailbox"),
    );
  });

  it("kilka osób z jednym powodem — jedno zdanie z liczbą", () => {
    expect(rejectionEmailBulkSkipMessage(["no_mailbox", "no_mailbox", "no_mailbox"])).toBe(
      "Mail odrzucenia nie został zaplanowany dla 3 osób — brak podłączonej skrzynki Microsoft 365.",
    );
  });

  it("różne powody — każdy z liczbą", () => {
    expect(
      rejectionEmailBulkSkipMessage(["not_client_visible", "no_candidate_email", "not_client_visible"]),
    ).toBe(
      "Mail odrzucenia nie został zaplanowany dla 3 osób — CV nie trafiło do klienta (2), brak adresu e-mail kandydata (1).",
    );
  });
});

describe("announceRejectionEmail", () => {
  const toasts = () => ({
    showActionToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
  });

  it("zaplanowany mail daje „Cofnij wysyłkę”", async () => {
    const toast = toasts();
    const cancel = vi.fn().mockResolvedValue(undefined);
    announceRejectionEmail({ scheduled_rejection_email_id: 9 }, { requested: true, toast, cancel });
    expect(toast.showActionToast).toHaveBeenCalledTimes(1);
    await toast.showActionToast.mock.calls[0][1].onAction();
    expect(cancel).toHaveBeenCalledWith(9);
    expect(toast.showSuccess).toHaveBeenCalledWith("Anulowano wysyłkę emaila.");
  });

  it("zaznaczony, niezaplanowany mail — zdanie z powodem", () => {
    const toast = toasts();
    announceRejectionEmail(
      { scheduled_rejection_email_id: null, rejection_email_status: "no_mailbox" },
      { requested: true, toast, cancel: vi.fn() },
    );
    expect(toast.showError).toHaveBeenCalledWith(rejectionEmailSkipMessage("no_mailbox"));
  });

  it("niezaznaczony mail albo reportSkip=false — cisza", () => {
    const toast = toasts();
    const data = { rejection_email_status: "no_mailbox" };
    announceRejectionEmail(data, { requested: false, toast, cancel: vi.fn() });
    announceRejectionEmail(data, { requested: true, reportSkip: false, toast, cancel: vi.fn() });
    expect(toast.showError).not.toHaveBeenCalled();
  });
});
