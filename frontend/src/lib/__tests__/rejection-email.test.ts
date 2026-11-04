/**
 * Runda 9 (R9-N11-2): jedna reguła dostępności maila odrzucenia — lustro
 * `rejection_email_scheduler.previous_is_client_visible` (kod etapu albo
 * kolumna Tablicy), a nie kategoria kolumny.
 */
import { describe, expect, it, vi } from "vitest";

import {
  announceRejectionEmail,
  rejectionEmailAvailableFrom,
  rejectionEmailBlockedMessage,
  rejectionEmailBulkSkipMessage,
  rejectionEmailDefaultBody,
  rejectionEmailPendingTime,
  rejectionEmailPreviewKey,
  rejectionEmailSkipMessage,
  rejectionEmailSkipShort,
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

  it("od „Zweryfikowany” mail jest możliwy także przed klientem (17.10.2026, D1)", () => {
    expect(
      rejectionEmailAvailableFrom({ stage: "verified", category: "internal" })
    ).toBe(true);
    expect(
      rejectionEmailAvailableFrom({
        stage: "interview",
        category: "internal",
        name: "QC CV",
      })
    ).toBe(true);
    expect(
      rejectionEmailAvailableFrom({
        stage: "new",
        category: "internal",
        name: "Wysłać do Cpro",
      })
    ).toBe(true);
  });

  it("przed weryfikacją i bez etapu mail nie jest proponowany", () => {
    expect(
      rejectionEmailAvailableFrom({ stage: "screening", category: "internal" })
    ).toBe(false);
    expect(
      rejectionEmailAvailableFrom({ stage: "new", category: "internal", name: "Nowi" })
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
      "Mail odrzucenia nie został zaplanowany dla 3 osób — przed weryfikacją (2), brak adresu e-mail kandydata (1).",
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

describe("podgląd w oknie odrzucenia (13.10.2026)", () => {
  it("powód przed potwierdzeniem mówi, że mail nie wyjdzie, i co zrobić", () => {
    expect(rejectionEmailBlockedMessage("no_mailbox")).toBe(
      "Mail nie wyjdzie — nie masz podłączonej skrzynki Microsoft 365. " +
        "Podłączysz ją w Ustawieniach → Integracje."
    );
    expect(rejectionEmailBlockedMessage("no_candidate_email")).toBe(
      "Mail nie wyjdzie — kandydat nie ma adresu e-mail."
    );
    expect(rejectionEmailBlockedMessage("coś_nowego")).toBe("Mail nie wyjdzie.");
  });

  it("krótki powód przy osobie na liście", () => {
    expect(rejectionEmailSkipShort("not_client_visible")).toBe("przed weryfikacją");
    expect(rejectionEmailSkipShort("coś_nowego")).toBe("inny powód");
  });

  it("klucz podglądu zależy od rekrutacji i listy osób", () => {
    expect(rejectionEmailPreviewKey(3, [5, 6])).toEqual(["rejection-email-preview", 3, "5,6"]);
  });
});

describe("rejectionEmailDefaultBody", () => {
  it("zakończenie idzie do pola, chyba że zamiast niego jest dopisek", () => {
    expect(rejectionEmailDefaultBody("Cześć", "Powodzenia!", false)).toBe(
      "Cześć\n\nPowodzenia!",
    );
    expect(rejectionEmailDefaultBody("Cześć", "Powodzenia!", true)).toBe("Cześć");
    // Starszy serwer bez `closing` — treść w całości w `body`.
    expect(rejectionEmailDefaultBody("Cześć i powodzenia", undefined, false)).toBe(
      "Cześć i powodzenia",
    );
  });
});

describe("rejectionEmailPendingTime", () => {
  it("godzina wysyłki czekającego maila w czasie Warszawy", () => {
    expect(rejectionEmailPendingTime("2026-10-17T09:42:00Z")).toBe("11:42");
    expect(rejectionEmailPendingTime("2026-12-01T09:05:00Z")).toBe("10:05");
  });
});
