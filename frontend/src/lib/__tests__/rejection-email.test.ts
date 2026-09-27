/**
 * Runda 9 (R9-N11-2): jedna reguła dostępności maila odrzucenia — lustro
 * `rejection_email_scheduler.previous_is_client_visible` (kod etapu albo
 * kolumna Tablicy), a nie kategoria kolumny.
 */
import { describe, expect, it } from "vitest";

import {
  rejectionEmailAvailableFrom,
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
