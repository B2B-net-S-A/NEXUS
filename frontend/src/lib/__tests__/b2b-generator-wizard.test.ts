/**
 * Kroki „Nowej umowy” i braki do paska (Generator umów, etap 3b przebudowy
 * modułu Kontrakty). Sedno: pasek pokazuje DOKŁADNIE to, co blokuje dziś
 * walidacja przed „Pobierz DOCX” — ani pola więcej (nie zaostrzamy), ani mniej.
 */
import { describe, expect, it } from "vitest";

import { EMPTY_ADMIN_VALUE } from "@/lib/agreement-admin-details";
import {
  b2bFormMissing,
  gapsLabel,
  generatorStepFromParam,
  missingCountLabel,
  missingInStepOrder,
  nextStep,
  parseRateInput,
  previousStep,
  stepSummary,
  validationMissingLabels,
  type B2BFormSnapshot,
  type StepSummaryInput,
} from "@/lib/b2b-generator-wizard";

const COMPLETE: B2BFormSnapshot = {
  hasCandidate: true,
  hasRecruitment: true,
  hasRole: true,
  isCompany: false,
  partnerName: "Jan Testowy",
  partnerInstrumental: "Janem Testowym",
  partnerLegalName: "JT Software Jan Testowy",
  partnerNip: "1234563218",
  partnerRegon: "123456785",
  partnerBusinessAddress: "ul. Prosta 1, 00-001 Warszawa",
  partnerEmail: "jan@example.com",
  partnerPhone: "600100200",
  company: {
    krs: "",
    seatLocative: "",
    registryCourt: "",
    shareCapital: "",
    representativeName: "",
    representativeFunction: "",
    representation: "",
  },
  clientName: "Przykładowy Bank S.A.",
  projectCity: "Warszawa",
  projectDescription: "Rozwój systemu.",
  contractNumber: "1500/2026",
  signingDate: "2026-11-20",
  startDate: "2026-12-01",
  rateStages: [{ rate: "150", from: "", to: "" }],
  admin: { isReplacement: false, replaced: null, fte: "1", isClientReferral: false },
};

const snap = (patch: Partial<B2BFormSnapshot>): B2BFormSnapshot => ({
  ...COMPLETE,
  ...patch,
});

describe("b2bFormMissing — lustro walidacji formularza", () => {
  it("komplet nie ma braków", () => {
    expect(b2bFormMissing(COMPLETE)).toEqual([]);
  });

  it("pusty formularz: etykiety w kolejności dzisiejszego komunikatu", () => {
    const empty = snap({
      hasCandidate: false,
      hasRecruitment: false,
      hasRole: false,
      partnerName: "",
      partnerInstrumental: "",
      partnerLegalName: "",
      partnerNip: "",
      partnerRegon: "",
      partnerBusinessAddress: "",
      partnerEmail: "",
      partnerPhone: "",
      clientName: "",
      projectCity: "",
      projectDescription: "",
      contractNumber: "",
      signingDate: "",
      startDate: "",
      rateStages: [{ rate: "", from: "", to: "" }],
      admin: EMPTY_ADMIN_VALUE,
    });
    expect(validationMissingLabels(b2bFormMissing(empty))).toEqual([
      "Kandydat",
      "Rekrutacja",
      "Obszar usług",
      "Imię i nazwisko Partnera",
      "Imię i nazwisko (narzędnik)",
      "Nazwa Firmy",
      "NIP",
      "REGON",
      "Adres z CEIDG",
      "E-mail",
      "Telefon",
      "Pełna nazwa Klienta",
      "Miasto Klienta",
      "Opis projektu",
      "Numer umowy",
      "Data podpisania",
      "Data rozpoczęcia",
      "Stawka godzinowa",
    ]);
  });

  it("same spacje to brak, a NIP nie musi mieć 10 cyfr (bez zaostrzania)", () => {
    const missing = b2bFormMissing(
      snap({ partnerEmail: "   ", partnerNip: "123" }),
    );
    expect(missing.map((m) => m.label)).toEqual(["E-mail"]);
  });

  it("stawka zero, ujemna albo nieczytelna to brak; przecinek jest dozwolony", () => {
    for (const rate of ["0", "-5", "abc", ""]) {
      expect(
        b2bFormMissing(snap({ rateStages: [{ rate, from: "", to: "" }] })).map(
          (m) => m.label,
        ),
      ).toEqual(["Stawka godzinowa"]);
    }
    expect(
      b2bFormMissing(snap({ rateStages: [{ rate: "135,5", from: "", to: "" }] })),
    ).toEqual([]);
  });

  it("stawka progresywna: kwota każdego etapu i „od” od drugiego etapu", () => {
    const missing = b2bFormMissing(
      snap({
        rateStages: [
          { rate: "120", from: "", to: "2026-12-31" },
          { rate: "", from: "", to: "" },
          { rate: "140", from: "2027-06-01", to: "" },
        ],
      }),
    );
    expect(missing.map((m) => [m.label, m.field])).toEqual([
      ["Stawka godzinowa (etap 2)", "rate-1"],
      ["„Obowiązuje od” (etap 2)", "rateFrom-1"],
    ]);
  });

  it("odwrócone daty etapu to nie brak — zgłasza je dopiero pobranie", () => {
    expect(
      b2bFormMissing(
        snap({
          rateStages: [
            { rate: "120", from: "2027-01-10", to: "2027-01-01" },
            { rate: "130", from: "2027-02-01", to: "" },
          ],
        }),
      ),
    ).toEqual([]);
  });

  it("spółka: pola z KRS zamiast imienia i narzędnika, adres siedziby", () => {
    const missing = b2bFormMissing(
      snap({
        isCompany: true,
        partnerName: "",
        partnerInstrumental: "",
        partnerBusinessAddress: "",
      }),
    );
    expect(missing.map((m) => m.label)).toEqual([
      "KRS",
      "Siedziba spółki",
      "Sąd rejestrowy i wydział",
      "Kapitał zakładowy",
      "Osoba reprezentująca spółkę",
      "Funkcja osoby reprezentującej",
      "Reprezentacja w komparycji",
      "Adres siedziby firmy",
    ]);
    expect(missing.every((m) => m.step === "partner")).toBe(true);
    expect(missing.map((m) => m.field)).toContain("seatLocative");
  });

  it("szczegóły administracyjne: tylko przy umowie z rekrutacją, osobno od komunikatu", () => {
    const withJob = b2bFormMissing(snap({ admin: EMPTY_ADMIN_VALUE }));
    expect(withJob.map((m) => [m.label, m.step, m.admin])).toEqual([
      ["Replacement", "admin", true],
      ["Wymiar FTE", "admin", true],
    ]);
    expect(validationMissingLabels(withJob)).toEqual([]);

    const withoutJob = b2bFormMissing(
      snap({ hasRecruitment: false, admin: EMPTY_ADMIN_VALUE }),
    );
    expect(withoutJob.map((m) => m.label)).toEqual(["Rekrutacja"]);
  });

  it("replacement „Tak” bez osoby to brak „Replacement za kogo”", () => {
    const missing = b2bFormMissing(
      snap({
        admin: { isReplacement: true, replaced: null, fte: "1", isClientReferral: false },
      }),
    );
    expect(missing.map((m) => m.label)).toEqual(["Replacement za kogo"]);
  });
});

describe("kolejność i etykiety paska", () => {
  it("pasek układa braki po krokach, w kroku — bez zmian", () => {
    const missing = b2bFormMissing(
      snap({
        hasRole: false,
        partnerRegon: "",
        partnerNip: "",
        admin: { ...EMPTY_ADMIN_VALUE, isReplacement: false },
        startDate: "",
      }),
    );
    expect(missingInStepOrder(missing).map((m) => m.label)).toEqual([
      "Wymiar FTE",
      "NIP",
      "REGON",
      "Obszar usług",
      "Data rozpoczęcia",
    ]);
  });

  it("odmiana liczebników", () => {
    expect(missingCountLabel(1)).toBe("Brakuje 1 pola");
    expect(missingCountLabel(3)).toBe("Brakuje 3 pól");
    expect(missingCountLabel(12)).toBe("Brakuje 12 pól");
    expect(gapsLabel(1)).toBe("1 brak");
    expect(gapsLabel(4)).toBe("4 braki");
    expect(gapsLabel(5)).toBe("5 braków");
    expect(gapsLabel(22)).toBe("22 braki");
  });
});

describe("krok z adresu i nawigacja", () => {
  it("zna tylko swoje kroki", () => {
    expect(generatorStepFromParam("admin")).toBe("admin");
    expect(generatorStepFromParam(" pobierz ")).toBe("pobierz");
    expect(generatorStepFromParam("partners")).toBeNull();
    expect(generatorStepFromParam("")).toBeNull();
    expect(generatorStepFromParam(null)).toBeNull();
  });

  it("dalej i wstecz zatrzymują się na końcach", () => {
    expect(nextStep("zrodlo")).toBe("admin");
    expect(nextStep("warunki")).toBe("pobierz");
    expect(nextStep("pobierz")).toBeNull();
    expect(previousStep("zrodlo")).toBeNull();
    expect(previousStep("admin")).toBe("zrodlo");
  });
});

describe("stepSummary", () => {
  const input: StepSummaryInput = {
    candidateName: "Jan Testowy",
    jobTitle: "Java Developer",
    language: "pl",
    admin: COMPLETE.admin,
    hasRecruitment: true,
    partnerLegalName: "JT Software Jan Testowy",
    partnerName: "Jan Testowy",
    clientName: "Przykładowy Bank S.A.",
    projectCity: "Warszawa",
    roleName: "Programista Java",
    contractNumber: "1500/2026",
    startDate: "2026-12-01",
    rateStages: [{ rate: "135.5", from: "", to: "" }],
    currency: "PLN",
  };

  it("przy komplecie mówi, co wpisano", () => {
    expect(stepSummary("zrodlo", input, [])).toBe("Jan Testowy · Java Developer");
    expect(stepSummary("zrodlo", { ...input, language: "en" }, [])).toBe(
      "Jan Testowy · Java Developer · po angielsku",
    );
    expect(stepSummary("admin", input, [])).toBe("bez replacementu · 1 FTE");
    expect(
      stepSummary(
        "admin",
        {
          ...input,
          admin: { isReplacement: true, replaced: null, fte: "0.5", isClientReferral: true },
        },
        [],
      ),
    ).toBe("replacement · 0,5 FTE · wskazany przez klienta");
    expect(stepSummary("partner", input, [])).toBe("JT Software Jan Testowy");
    expect(stepSummary("klient", input, [])).toBe("Przykładowy Bank S.A. · Warszawa");
    expect(stepSummary("obszar", input, [])).toBe("Programista Java");
    expect(stepSummary("warunki", input, [])).toBe(
      "1500/2026 · od 01.12.2026 · 135,5 zł/h",
    );
    expect(stepSummary("pobierz", input, [])).toBe("gotowe do pobrania");
  });

  it("braki wygrywają z podsumowaniem", () => {
    const missing = b2bFormMissing(snap({ partnerNip: "", partnerRegon: "" }));
    expect(stepSummary("partner", input, missing)).toBe("2 braki");
    expect(stepSummary("pobierz", input, missing)).toBe("brakuje 2 pól");
  });

  it("szczegóły administracyjne bez rekrutacji czekają na nią", () => {
    expect(stepSummary("admin", { ...input, hasRecruitment: false }, [])).toBe(
      "po wybraniu rekrutacji",
    );
  });

  it("stawka progresywna i waluta obca", () => {
    expect(
      stepSummary(
        "warunki",
        {
          ...input,
          currency: "EUR",
          rateStages: [
            { rate: "40", from: "", to: "" },
            { rate: "45", from: "2027-01-01", to: "" },
          ],
        },
        [],
      ),
    ).toBe("1500/2026 · od 01.12.2026 · stawka progresywna (2 etapy)");
    expect(stepSummary("warunki", { ...input, currency: "EUR" }, [])).toBe(
      "1500/2026 · od 01.12.2026 · 135,5 EUR/h",
    );
  });
});

describe("parseRateInput", () => {
  it("przecinek, kropka, puste", () => {
    expect(parseRateInput("135,5")).toBe(135.5);
    expect(parseRateInput(" 150 ")).toBe(150);
    expect(parseRateInput("")).toBeNull();
    expect(parseRateInput("abc")).toBeNull();
  });
});
