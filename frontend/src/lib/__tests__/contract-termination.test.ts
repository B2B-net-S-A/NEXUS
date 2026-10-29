import { describe, expect, it } from "vitest";
import {
  agreementTerminationPayload,
  defaultNonCompetePlan,
  emptyTerminationForm,
  missingTerminationFields,
  statusEventDetailsText,
  suggestedLastDay,
  terminationFormError,
  terminationWarnings,
} from "@/lib/contract-termination";

describe("suggestedLastDay", () => {
  // Umowa 2026 (`notice_end_date` w backendzie): okres wypowiedzenia ze
  // skutkiem na koniec miesiąca kalendarzowego (audyt 24.09, N2).
  it("dodaje okres wypowiedzenia i kończy na ostatnim dniu miesiąca", () => {
    expect(suggestedLastDay("2026-09-15", 1)).toBe("2026-10-31");
    expect(suggestedLastDay("2026-09-10", 1)).toBe("2026-10-31");
    expect(suggestedLastDay("2026-11-15", 3)).toBe("2027-02-28");
  });

  it("koniec lutego zna rok przestępny", () => {
    expect(suggestedLastDay("2026-01-31", 1)).toBe("2026-02-28");
    expect(suggestedLastDay("2028-01-05", 1)).toBe("2028-02-29");
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

  it("przy jednej umowie brakuje odpowiedzi „Co z umową B2B?”, zbiorczo nie", () => {
    expect(missingTerminationFields(base, { requirePlan: true })).toEqual(["Co z umową B2B"]);
    expect(missingTerminationFields({ ...base, agreementPlan: "keep" }, { requirePlan: true })).toEqual([]);
    expect(missingTerminationFields(base)).toEqual([]);
  });

  it("zakaz konkurencji domyślnie zostaje, przy przejściu do klienta — zdjęty", () => {
    expect(defaultNonCompetePlan("poached_by_client")).toBe("release");
    expect(defaultNonCompetePlan("project_ended")).toBe("keep");
    expect(defaultNonCompetePlan("")).toBe("keep");
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

  it("koniec projektu przed startem kontraktu blokuje zapis (runda 10, F27)", () => {
    const form = { ...base, projectEndDate: "2026-09-27" };
    expect(terminationFormError(form, "2026-11-01")).toMatch(
      /wcześniejsza niż start kontraktu \(01\.11\.2026\)/,
    );
    expect(
      terminationFormError({ ...base, projectEndDate: "2026-11-01" }, "2026-11-01"),
    ).toBeNull();
    expect(terminationFormError(form, null)).toBeNull();
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

describe("statusEventDetailsText — rozwiązanie zapisane po zakończeniu", () => {
  it("opisuje porozumienie podpisane poza NEXUSEM", () => {
    expect(
      statusEventDetailsText({
        source: "agreement_termination_recorded",
        contract_id: 318,
        agreement_terminated: true,
        mode: "mutual_agreement",
        agreement_last_day: "2026-09-30",
      }),
    ).toBe(
      "Rozwiązanie umowy zapisane po zakończeniu (kontrakt #318) · Porozumienie stron · " +
        "ostatni dzień umowy 30.09.2026",
    );
  });
});

describe("statusEventDetailsText — powiązanie z kontraktem", () => {
  it("opisuje, z którym kontraktem powiązano umowę", () => {
    expect(
      statusEventDetailsText({ source: "linked_to_contract", contract_id: 341 }),
    ).toBe("Powiązano z kontraktem #341 — umowa miała znacznik „brak kontraktora”");
  });
});
