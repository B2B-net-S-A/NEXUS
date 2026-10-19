/**
 * Reguły okna „Nowa umowa albo aneks” — te same co serwer: minimum zlecenia
 * roku umowy (tylko w złotych), art. 8b, aneks od 1. dnia miesiąca, koniec po
 * początku. Dane fikcyjne.
 */
import { describe, expect, it } from "vitest";

import { celinaAgreements, olaAgreements, TEMPLATES } from "@/app/preview/hr-agreements/fixtures";

import {
  afterSigning,
  attention,
  draftInput,
  draftProblem,
  formatAmount,
  rateFrom,
  rateLabel,
  statusNote,
  templateChoices,
  type DraftForm,
} from "../agreement-format";

const MINIMUM = { "2026": "31.40", "2027": "31.40" };

function form(values: Partial<DraftForm> = {}): DraftForm {
  return {
    templateId: "31",
    baseAgreementId: "",
    rate: "32,00",
    currency: "PLN",
    startDate: "2026-11-01",
    endDate: "",
    indefinite: true,
    agreementDate: "2026-10-25",
    hoursConfirmation: true,
    payoutDay: "10",
    coordinatorId: "105",
    ...values,
  };
}

const mandate = { kind: "agreement" as const, employmentType: "zlecenie" as const, minimumRates: MINIMUM };

describe("draftProblem", () => {
  it("przepuszcza poprawną umowę zlecenia", () => {
    expect(draftProblem(form(), mandate)).toBeNull();
  });

  it("zlecenie poniżej minimum roku umowy — z kwotą minimum", () => {
    expect(draftProblem(form({ rate: "31,39" }), mandate)).toBe(
      "Minimalna stawka na zleceniu w 2026 to 31,40 zł/h brutto.",
    );
    // Rok bez minimum w Ustawieniach i inna waluta — bez blokady (serwer ostrzeże).
    expect(draftProblem(form({ rate: "20", startDate: "2030-01-01" }), mandate)).toBeNull();
    expect(draftProblem(form({ rate: "20", currency: "EUR" }), mandate)).toBeNull();
  });

  it("minimum nie dotyczy B2B", () => {
    expect(
      draftProblem(form({ rate: "20" }), { ...mandate, employmentType: "b2b" }),
    ).toBeNull();
  });

  it("zlecenie bez potwierdzania godzin — art. 8b", () => {
    expect(draftProblem(form({ hoursConfirmation: false }), mandate)).toContain("art. 8b");
  });

  it("aneks tylko od 1. dnia miesiąca", () => {
    const annex = { ...mandate, kind: "annex" as const };
    expect(draftProblem(form({ startDate: "2026-11-15" }), annex)).toContain("1. dnia miesiąca");
    expect(draftProblem(form({ startDate: "2026-12-01" }), annex)).toBeNull();
  });

  it("odrzuca brak wzoru, złą stawkę i koniec przed początkiem", () => {
    expect(draftProblem(form({ templateId: "" }), mandate)).toBe("Wybierz wzór umowy.");
    for (const rate of ["", "0", "abc", "32,001"]) {
      expect(draftProblem(form({ rate }), mandate)).toContain("Stawka");
    }
    expect(
      draftProblem(form({ indefinite: false, endDate: "2026-10-31" }), mandate),
    ).toContain("przed datą początku");
    expect(draftProblem(form({ indefinite: false, endDate: "" }), mandate)).toContain("datę końca");
    expect(draftProblem(form({ payoutDay: "32" }), mandate)).toContain("Dzień wypłaty");
  });
});

describe("draftInput", () => {
  it("B2B bez dnia wypłaty, umowa bez końca = end_date null, stawka z kropką", () => {
    const input = draftInput(form({ rate: "1 234,5" }), { kind: "agreement", employmentType: "b2b" });
    expect(input).toMatchObject({
      template_id: 31,
      hourly_rate: "1234.50",
      end_date: null,
      payout_day: null,
      base_agreement_id: null,
      coordinator_user_id: 105,
    });
  });

  it("aneks niesie zmienianą umowę", () => {
    const input = draftInput(form({ baseAgreementId: "41" }), { kind: "annex", employmentType: "zlecenie" });
    expect(input.base_agreement_id).toBe(41);
    expect(input.payout_day).toBe(10);
  });
});

describe("afterSigning", () => {
  it("umowa zlecenia: stawka od 1. dnia miesiąca, forma, dokument, Symfonia", () => {
    expect(afterSigning({ kind: "agreement", employmentType: "zlecenie" }, "2026-11-15")).toEqual([
      "zapisze stawkę od 01.11.2026 w historii stawek",
      "ustawi formę „zlecenie” i potwierdzanie godzin w kartotece",
      "doda umowę do dokumentów osoby",
      "przekaże dane do Symfonii przy najbliższym eksporcie",
    ]);
  });

  it("aneks B2B: bez formy i bez Symfonii", () => {
    expect(afterSigning({ kind: "annex", employmentType: "b2b" }, "2026-12-01")).toEqual([
      "zapisze stawkę od 01.12.2026 w historii stawek",
      "doda aneks do dokumentów osoby",
    ]);
  });

  it("podpis bez Płac: stawki nie zapisze, przepisze ją osoba z Płac (19.10.2026)", () => {
    expect(
      afterSigning({ kind: "agreement", employmentType: "b2b" }, "2026-11-01", { appliesRate: false }),
    ).toEqual([
      "przekaże Płacom stawkę od 01.11.2026 — Stawkę przepisze osoba z Płac",
      "ustawi formę „B2B” i potwierdzanie godzin w kartotece",
      "doda umowę do dokumentów osoby",
    ]);
  });

  it("rateFrom: umowa od 1. dnia miesiąca, aneks od swojej daty", () => {
    expect(rateFrom("agreement", "2026-11-15")).toBe("2026-11-01");
    expect(rateFrom("annex", "2026-12-01")).toBe("2026-12-01");
  });
});

describe("wiersz umowy", () => {
  it("stan, stawka i uwagi z danych harnessu", () => {
    const [sent, manual, autenti] = celinaAgreements().agreements;
    expect(statusNote(sent)).toMatch(/^Autenti · \d{2}\.\d{2}\.\d{4}$/);
    expect(statusNote(manual)).toMatch(/ręcznie, ze skanem$/);
    expect(statusNote(autenti)).toMatch(/· Autenti$/);
    expect(rateLabel(autenti)).toBe("31,40 zł brutto za godzinę");
    const [draft, unapplied] = olaAgreements().agreements;
    expect(statusNote(draft)).toContain("Autenti nie przyjęło");
    expect(attention(unapplied)).toContain("nie przeszła do kartoteki");
    expect(rateLabel(unapplied)).toBe("95,00 zł netto za godzinę");
  });

  it("formatAmount i lista wzorów bez wycofanych", () => {
    expect(formatAmount("1234.5")).toBe("1 234,50");
    const choices = templateChoices(TEMPLATES.items);
    expect(choices.map((choice) => choice.templateId)).toEqual([31, 32, 33]);
    expect(choices[0].label).toBe("Umowa zlecenia · Zlecenie — recepcja · wersja 3");
    expect(choices[2]).toMatchObject({ kind: "annex", employmentType: null });
  });
});
