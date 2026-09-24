import { describe, expect, it } from "vitest";
import {
  agreementTerminationPayload,
  emptyTerminationForm,
  missingTerminationFields,
  statusEventDetailsText,
  suggestedLastDay,
  terminationFormError,
  terminationWarnings,
} from "@/lib/contract-termination";

describe("suggestedLastDay", () => {
  it("dodaje okres wypowiedzenia w miesiącach", () => {
    expect(suggestedLastDay("2026-09-10", 1)).toBe("2026-10-10");
    expect(suggestedLastDay("2026-11-15", 3)).toBe("2027-02-15");
  });

  it("przycina dzień do końca krótszego miesiąca", () => {
    expect(suggestedLastDay("2026-01-31", 1)).toBe("2026-02-28");
    expect(suggestedLastDay("2028-01-31", 1)).toBe("2028-02-29");
  });

  it("bez okresu albo daty nie podpowiada nic", () => {
    expect(suggestedLastDay("2026-09-10", null)).toBeNull();
    expect(suggestedLastDay("", 1)).toBeNull();
  });
});

describe("walidacja i ostrzeżenia", () => {
  const base = emptyTerminationForm({
    reason: "project_ended",
    projectEndDate: "2026-09-23",
  });

  it("samo zakończenie projektu jest kompletne z powodem i datą", () => {
    expect(missingTerminationFields(base)).toEqual([]);
    expect(agreementTerminationPayload(base)).toBeNull();
  });

  it("rozwiązanie umowy wymaga trybu, strony i obu dat", () => {
    const form = { ...base, agreementTerminated: true, mode: "mutual_agreement" as const };
    expect(missingTerminationFields(form)).toEqual([
      "Strona",
      "Data zawarcia porozumienia",
      "Ostatni dzień umowy",
    ]);
  });

  it("ostatni dzień przed datą złożenia blokuje zapis", () => {
    const form = {
      ...base,
      agreementTerminated: true,
      mode: "notice" as const,
      party: "company" as const,
      signedOn: "2026-09-10",
      lastDay: "2026-09-01",
    };
    expect(terminationFormError(form)).toMatch(/złożenia wypowiedzenia/);
  });

  it("projekt po końcu umowy i po końcu zamówienia = dwa ostrzeżenia", () => {
    const form = {
      ...base,
      agreementTerminated: true,
      mode: "notice" as const,
      party: "consultant" as const,
      signedOn: "2026-08-01",
      lastDay: "2026-09-15",
    };
    expect(terminationWarnings(form, "2026-09-20")).toEqual([
      "Konsultant pracowałby na projekcie bez obowiązującej umowy.",
      "Data zakończenia projektu wykracza poza okres zamówienia.",
    ]);
    // Przykład z ticketu: projekt 23.09, umowa do 30.09 — bez ostrzeżeń.
    expect(
      terminationWarnings({ ...form, lastDay: "2026-09-30" }, "2026-12-31"),
    ).toEqual([]);
  });
});

describe("statusEventDetailsText", () => {
  it("opisuje rozwiązanie umowy w historii Generatora", () => {
    expect(
      statusEventDetailsText({
        source: "contract_termination_synced",
        contract_id: 674,
        project_end_date: "2026-09-23",
        agreement_terminated: true,
        mode: "notice",
        party: "consultant",
        signed_on: "2026-08-31",
        agreement_last_day: "2026-09-30",
      }),
    ).toBe(
      "Zakończenie współpracy (kontrakt #674) · koniec zamówienia 23.09.2026 · " +
        "Wypowiedzenie · strona: Konsultant · data złożenia wypowiedzenia 31.08.2026 · " +
        "ostatni dzień umowy 30.09.2026",
    );
  });

  it("ręczna zmiana nie ma dodatkowej linii", () => {
    expect(statusEventDetailsText(null)).toBeNull();
  });
});
