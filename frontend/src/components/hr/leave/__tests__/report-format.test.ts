import { describe, expect, it } from "vitest";

import {
  paySplitLabel,
  reportOutcome,
  statusLabel,
  submitLabel,
  submittedToast,
} from "../leave-format";

// Zgłoszenie z B2B i zlecenia (etap 2, D5) — słowa okna i list.

describe("zgłoszenie zamiast wniosku (D5)", () => {
  const preview = { paid_days: "4.0", unpaid_days: "1.0", approver: "Marta Fikcyjna" };

  it("„Co się stanie po zgłoszeniu” na B2B: kalendarz, koordynator bez decyzji, raport do faktury", () => {
    const lines = reportOutcome(preview, "b2b");
    expect(lines.map((line) => line.title)).toEqual([
      "Termin od razu w kalendarzu",
      "Koordynator dostaje informację",
      "Raport godzin",
    ]);
    expect(lines[1].text).toContain("Marta Fikcyjna może zgłosić kolizję");
    expect(lines[1].text).toContain("nie zatwierdza i nie odrzuca");
    expect(lines[2].text).toBe("dni z puli liczą się jak dni pracy do faktury, pozostałe są puste");
    expect(reportOutcome({ ...preview, paid_days: "0.0" }, "b2b")[2].text).toBe(
      "dni przerwy są puste — bez wynagrodzenia",
    );
    expect(reportOutcome({ ...preview, unpaid_days: "0.0" }, "b2b")[2].text).toBe(
      "dni z puli liczą się jak dni pracy do faktury",
    );
  });

  it("na zleceniu: potwierdzenie godzin bez godzin za te dni", () => {
    const lines = reportOutcome({ ...preview, paid_days: "0.0" }, "zlecenie");
    expect(lines[2]).toEqual({
      title: "Potwierdzenie godzin",
      text: "za te dni nie ma godzin — nieobecność jest bez wynagrodzenia",
    });
    expect(lines.some((line) => /urlop|wniosek|przełożon/i.test(`${line.title} ${line.text}`))).toBe(
      false,
    );
  });

  it("podział z puli i bez wynagrodzenia", () => {
    expect(paySplitLabel(preview)).toBe("Rozliczenie: z płatnej puli 4 dni · bez wynagrodzenia 1 dzień");
    expect(paySplitLabel({ paid_days: "0.0", unpaid_days: "2.0" })).toBe(
      "Rozliczenie: bez wynagrodzenia 2 dni",
    );
    expect(paySplitLabel({ paid_days: "0.0", unpaid_days: "0.0" })).toBeNull();
  });

  it("przycisk zapisu według formy i ścieżki", () => {
    expect(submitLabel({ onBehalf: false, form: "b2b", autoApproved: true })).toBe("Zgłoś przerwę");
    expect(submitLabel({ onBehalf: false, form: "zlecenie", autoApproved: true })).toBe(
      "Zgłoś nieobecność",
    );
    expect(submitLabel({ onBehalf: false, form: "uop", autoApproved: false })).toBe(
      "Wyślij do akceptacji",
    );
    expect(submitLabel({ onBehalf: false, form: "uop", autoApproved: true })).toBe("Zgłoś nieobecność");
    expect(submitLabel({ onBehalf: true, form: "b2b", autoApproved: true })).toBe("Wpisz nieobecność");
  });

  it("status i komunikat: zgłoszenie jest „zgłoszone”, wniosek UoP czeka na akceptację", () => {
    expect(statusLabel({ status: "approved", is_report: true })).toBe("Zgłoszone");
    expect(statusLabel({ status: "approved", is_report: false })).toBe("Zatwierdzony");
    expect(statusLabel({ status: "cancelled", is_report: true })).toBe("Anulowany");
    expect(submittedToast({ status: "approved", is_report: true, employment_type: "b2b" })).toBe(
      "Przerwa w świadczeniu usług zgłoszona",
    );
    expect(submittedToast({ status: "approved", is_report: true, employment_type: "zlecenie" })).toBe(
      "Nieobecność zgłoszona",
    );
    expect(submittedToast({ status: "pending", is_report: false, employment_type: "uop" })).toBe(
      "Wniosek wysłany do akceptacji",
    );
  });
});
