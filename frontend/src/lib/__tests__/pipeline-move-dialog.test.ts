/**
 * Które ruchy wymagają dialogu — jedna reguła dla tablicy i dla doku „Decyzja".
 *
 * Cichy tryb awarii, przed którym to broni: dok kroku 07 wysyła
 * `POST /api/pipeline/move` sam. Gdyby nie znał gałęzi „CV Wysłane", ruch
 * PRZESZEDŁBY — tyle że bez zapytania o stawkę do klienta, czyli bez danych,
 * które tamten modal istnieje po to, żeby zebrać. Nic by się nie wywaliło;
 * po prostu stawka byłaby pusta.
 */

import { describe, expect, it } from "vitest";

import {
  dialogUnavailableReason,
  moveDialogFor,
} from "@/lib/pipeline-move-dialog";

describe("moveDialogFor", () => {
  it("rozpoznaje cztery gałęzie `requestMove`", () => {
    expect(moveDialogFor({ stage: "verified" })).toBe("verified_rate");
    expect(moveDialogFor({ stage: "cv_sent" })).toBe("client_rate");
    expect(moveDialogFor({ stage: "hired" })).toBe("hired_confirm");
    expect(moveDialogFor({ stage: "rejected" })).toBe("rejection");
    expect(moveDialogFor({ stage: "withdrawn" })).toBe("rejection");
  });

  it("zwykły etap idzie bez dialogu", () => {
    expect(moveDialogFor({ stage: "client_interview" })).toBe("none");
    expect(moveDialogFor({ stage: "acceptance" })).toBe("none");
    expect(moveDialogFor({ stage: "new", terminal_type: null })).toBe("none");
  });

  it("własny etap terminalny rozpoznaje po `terminal_type`, nie po `stage`", () => {
    // Kolumna bez mapowania na legacy enum raportuje `stage: "new"`.
    expect(moveDialogFor({ stage: "new", terminal_type: "hired" })).toBe(
      "hired_confirm",
    );
    expect(moveDialogFor({ stage: "new", terminal_type: "rejected" })).toBe(
      "rejection",
    );
  });
});

describe("dialogUnavailableReason", () => {
  it("dialogi hostowane tylko na tablicy mają polski powód wyszarzenia", () => {
    expect(dialogUnavailableReason("verified_rate")).toMatch(/stawkę kandydata/);
    expect(dialogUnavailableReason("client_rate")).toMatch(/stawkę do klienta/);
    expect(dialogUnavailableReason("hired_confirm")).toMatch(/tablicy/);
  });

  it("ruch bez dialogu i odrzucenie NIE są blokowane w doku", () => {
    // `RejectionV2` dok hostuje sam, a terminalne muszą zawsze przechodzić —
    // inaczej nie dałoby się zamknąć kandydata z poziomu kroku 07.
    expect(dialogUnavailableReason("none")).toBeNull();
    expect(dialogUnavailableReason("rejection")).toBeNull();
  });
});
