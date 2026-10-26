import { describe, expect, it } from "vitest";

import {
  MANDATE_DPA_PURPOSE_DEFAULT,
  emptyMandateForm,
  mandateErrors,
  mandateLabel,
  mandatePayload,
  parseRate,
  peselValid,
  type MandateFormState,
} from "@/lib/b2b-mandate";

// Fikcyjny PESEL z poprawną cyfrą kontrolną.
const PESEL = "44051401458";

function filled(patch: Partial<MandateFormState> = {}): MandateFormState {
  return {
    ...emptyMandateForm("2026-10-27"),
    partnerName: "Anna Testowa",
    periodFrom: "2026-11-01",
    periodTo: "2027-01-31",
    tasks: ["administracja platformą"],
    rate: "45,50",
    ...patch,
  };
}

describe("umowa zlecenia — formularz", () => {
  it("nowy formularz ma DPA z celem ze wzoru i jedną pustą czynność", () => {
    const form = emptyMandateForm("2026-10-27");
    expect(form.withDpa).toBe(true);
    expect(form.dpaPurpose).toBe(MANDATE_DPA_PURPOSE_DEFAULT);
    expect(form.tasks).toEqual([""]);
    expect(form.signingDate).toBe("2026-10-27");
  });

  it("pusty formularz pokazuje błędy wymaganych pól", () => {
    const errors = mandateErrors({ ...emptyMandateForm("2026-10-27"), periodFrom: "" });
    expect(Object.keys(errors).sort()).toEqual(
      ["partnerName", "periodFrom", "periodTo", "rate", "tasks"].sort(),
    );
  });

  it("koniec przed początkiem i zły PESEL to błąd", () => {
    expect(mandateErrors(filled({ periodTo: "2026-10-31" })).periodTo).toMatch(
      /przed jego początkiem/,
    );
    expect(mandateErrors(filled({ pesel: "44051401459" })).pesel).toMatch(/PESEL/);
    expect(mandateErrors(filled({ pesel: PESEL }))).toEqual({});
  });

  it("PESEL: 11 cyfr i cyfra kontrolna", () => {
    expect(peselValid(PESEL)).toBe(true);
    expect(peselValid("4405140145")).toBe(false);
    expect(peselValid("4405140145a")).toBe(false);
  });

  it("stawka z przecinkiem", () => {
    expect(parseRate("45,50")).toBe(45.5);
    expect(parseRate(" 1 200 ")).toBe(1200);
    expect(parseRate("")).toBeNull();
  });

  it("ładunek: puste pola wrażliwe = null, czynności bez pustych", () => {
    const payload = mandatePayload(
      filled({ tasks: ["  a ", "", "b"], homeAddress: " ", pesel: "" }),
    );
    expect(payload.tasks).toEqual(["a", "b"]);
    expect(payload.home_address).toBeNull();
    expect(payload.pesel).toBeNull();
    expect(payload.gross_hourly_rate).toBe(45.5);
  });

  it("kandydat bez rekrutacji nie idzie do serwera (para albo nic)", () => {
    expect(mandatePayload(filled({ candidateId: 7, jobId: null }))).toMatchObject({
      candidate_id: null,
      job_id: null,
    });
    expect(mandatePayload(filled({ candidateId: 7, jobId: 9 }))).toMatchObject({
      candidate_id: 7,
      job_id: 9,
    });
  });

  it("bez DPA cel przetwarzania nie jest wysyłany", () => {
    expect(mandatePayload(filled({ withDpa: false })).dpa_purpose).toBeNull();
    expect(mandatePayload(filled()).dpa_purpose).toBe(MANDATE_DPA_PURPOSE_DEFAULT);
  });

  it("etykieta wiersza jak na serwerze", () => {
    expect(mandateLabel("2026-10-27")).toBe("Zlecenie z dnia 27.10.2026");
    expect(mandateLabel("")).toBe("Umowa zlecenia");
  });
});
