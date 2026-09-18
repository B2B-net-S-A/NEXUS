import { describe, expect, it } from "vitest";
import {
  b2bEndDateLocked,
  b2bExtensionLocked,
  terminationSeedDate,
} from "@/lib/contract-end-date";

// Lustro `backend/app/services/b2b_contract_end_date.py::end_date_allowed`.
describe("b2bEndDateLocked", () => {
  it("blokuje datę umowy B2B, której nikt nie zakończył", () => {
    expect(b2bEndDateLocked({ contract_type: "b2b", status: "active" })).toBe(true);
    expect(b2bEndDateLocked({ contract_type: "b2b", status: "ending" })).toBe(true);
    expect(b2bEndDateLocked({ contract_type: "b2b", status: "draft" })).toBe(true);
    // Brak typu = domyślny typ kontraktu, czyli B2B.
    expect(b2bEndDateLocked({ status: "active" })).toBe(true);
  });

  it("odblokowuje datę po ręcznym zakończeniu i dla umowy zakończonej", () => {
    expect(
      b2bEndDateLocked({
        contract_type: "b2b",
        status: "ending",
        terminated_at: "2026-10-02",
      }),
    ).toBe(false);
    expect(
      b2bEndDateLocked({
        contract_type: "b2b",
        status: "active",
        termination_reason: "client_budget_cut",
      }),
    ).toBe(false);
    expect(b2bEndDateLocked({ contract_type: "b2b", status: "ended" })).toBe(false);
    expect(b2bEndDateLocked({ contract_type: "b2b", status: "void" })).toBe(false);
  });

  it("nie dotyczy umów zlecenie ani umów o pracę", () => {
    expect(b2bEndDateLocked({ contract_type: "uzlecenie", status: "active" })).toBe(
      false,
    );
    expect(b2bEndDateLocked({ contract_type: "uop", status: "active" })).toBe(false);
  });
});

describe("b2bExtensionLocked", () => {
  it("przedłużenie umowy B2B wymaga ręcznego zakończenia, niezależnie od statusu", () => {
    expect(b2bExtensionLocked({ contract_type: "b2b", status: "active" })).toBe(true);
    expect(b2bExtensionLocked({ contract_type: "b2b", status: "ended" })).toBe(true);
    expect(
      b2bExtensionLocked({
        contract_type: "b2b",
        status: "ending",
        terminated_at: "2026-10-02",
      }),
    ).toBe(false);
    expect(b2bExtensionLocked({ contract_type: "uzlecenie", status: "active" })).toBe(
      false,
    );
  });
});

describe("terminationSeedDate", () => {
  it("bierze datę z formularza edycji, nie tę zapisaną na umowie", () => {
    // Sedno zgłoszenia: operator wpisał datę obok statusu „Zakończony", więc
    // dialog „Zakończ współpracę" nie może pytać o nią drugi raz.
    expect(terminationSeedDate("2026-11-30", "2026-06-30")).toBe("2026-11-30");
    expect(terminationSeedDate("2026-11-30", null)).toBe("2026-11-30");
  });

  it("cofa się do daty umowy, gdy pole formularza było puste", () => {
    // Bezterminowa B2B ma pole zablokowane, więc formularz nie niesie daty.
    expect(terminationSeedDate("", "2026-06-30")).toBe("2026-06-30");
    expect(terminationSeedDate(undefined, "2026-06-30")).toBe("2026-06-30");
  });

  it("bez obu dat zostawia dialogowi jego własną wartość domyślną", () => {
    expect(terminationSeedDate("", null)).toBeUndefined();
    expect(terminationSeedDate(undefined, undefined)).toBeUndefined();
  });
});
