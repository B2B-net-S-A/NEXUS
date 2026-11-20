// „Nowa umowa” B2B w Generatorze jako kroki z paskiem braków (wariant A
// z paskiem z wariantu B, makiety modułu Kontrakty, decyzja Artura 19.11.2026).
// Czyste funkcje — formularz (`components/v2/pages/B2BContractGeneratorV2.tsx`)
// ma ponad 6 tys. linii, a tę regułę trzeba sprawdzać bez montowania go.
//
// Braki to DOKŁADNIE to, co `validate()` formularza sprawdza przed „Pobierz
// DOCX” i „Podgląd” — ten sam wynik buduje komunikat „Uzupełnij wymagane
// pola: …” — plus „Szczegóły administracyjne” przy umowie z rekrutacją
// (osobny komunikat, serwer odpowiada 422). Pasek nie może być ostrzejszy niż
// dzisiejsza walidacja: format numeru i kolejność dat etapów stawki to nie
// braki, tylko błędy zgłaszane dopiero przy pobraniu.
import type { AgreementAdminValue } from "@/lib/agreement-admin-details";
import {
  companyVariantMissing,
  type CompanyVariantFields,
} from "@/lib/b2b-company-variant";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

// ── Kroki ───────────────────────────────────────────────────────────────────

export type GeneratorStep =
  | "zrodlo"
  | "admin"
  | "partner"
  | "klient"
  | "obszar"
  | "warunki"
  | "pobierz";

/** Kroki z polami formularza (bez podsumowania „Sprawdź i pobierz”). */
export type GeneratorFormStep = Exclude<GeneratorStep, "pobierz">;

export const GENERATOR_STEPS: readonly {
  key: GeneratorStep;
  label: string;
}[] = [
  { key: "zrodlo", label: "Źródło danych" },
  { key: "admin", label: "Szczegóły administracyjne" },
  { key: "partner", label: "Partner" },
  { key: "klient", label: "Klient i projekt" },
  { key: "obszar", label: "Obszar usług" },
  { key: "warunki", label: "Warunki umowy" },
  { key: "pobierz", label: "Sprawdź i pobierz" },
] as const;

const STEP_KEYS = GENERATOR_STEPS.map((s) => s.key);

export function stepLabel(step: GeneratorStep): string {
  return GENERATOR_STEPS.find((s) => s.key === step)?.label ?? step;
}

export function stepIndex(step: GeneratorStep): number {
  return STEP_KEYS.indexOf(step);
}

/** `?krok=` z adresu (link do kroku, np. z Nowości) → krok; nieznany → `null`. */
export function generatorStepFromParam(
  raw: string | null | undefined,
): GeneratorStep | null {
  const value = raw?.trim();
  if (!value) return null;
  return (STEP_KEYS as readonly string[]).includes(value)
    ? (value as GeneratorStep)
    : null;
}

export function nextStep(step: GeneratorStep): GeneratorStep | null {
  return STEP_KEYS[stepIndex(step) + 1] ?? null;
}

export function previousStep(step: GeneratorStep): GeneratorStep | null {
  const i = stepIndex(step);
  return i > 0 ? STEP_KEYS[i - 1] : null;
}

// ── Braki ───────────────────────────────────────────────────────────────────

export interface GeneratorMissing {
  step: GeneratorFormStep;
  /** Etykieta w komunikacie „Uzupełnij wymagane pola: …” i na pasku braków. */
  label: string;
  /** Wartość `data-gen-field` pola — klik w brak przenosi na nie fokus. */
  field: string;
  /**
   * Brak ze „Szczegółów administracyjnych” — formularz zgłasza go własnym
   * komunikatem po liście pól, tak jak przed przebudową.
   */
  admin?: true;
}

/** Jeden etap stawki z formularza („stawka progresywna”). */
export interface RateStageInput {
  rate: string;
  from: string;
  to: string;
}

/** Stan formularza umowy B2B potrzebny do policzenia braków. */
export interface B2BFormSnapshot {
  hasCandidate: boolean;
  hasRecruitment: boolean;
  hasRole: boolean;
  isCompany: boolean;
  partnerName: string;
  partnerInstrumental: string;
  partnerLegalName: string;
  partnerNip: string;
  partnerRegon: string;
  partnerBusinessAddress: string;
  partnerEmail: string;
  partnerPhone: string;
  company: CompanyVariantFields;
  clientName: string;
  projectCity: string;
  projectDescription: string;
  contractNumber: string;
  signingDate: string;
  startDate: string;
  rateStages: readonly RateStageInput[];
  admin: AgreementAdminValue;
}

/** Stawka bywa ułamkowa wpisana po polsku (135,5) — przecinek → kropka. */
export function parseRateInput(raw: string): number | null {
  const v = raw.trim();
  if (!v) return null;
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

// Etykieta z `companyVariantMissing` → pole formularza. Nieznana etykieta
// (nowe pole spółki) nadal trafia na listę, tylko bez przeniesienia fokusu.
const COMPANY_FIELD: Record<string, string> = {
  KRS: "krs",
  "Siedziba spółki": "seatLocative",
  "Sąd rejestrowy i wydział": "registryCourt",
  "Kapitał zakładowy": "shareCapital",
  "Osoba reprezentująca spółkę": "representativeName",
  "Funkcja osoby reprezentującej": "representativeFunction",
  "Reprezentacja w komparycji": "representation",
};

/**
 * Braki umowy B2B w kolejności dzisiejszego komunikatu walidacji; braki
 * „Szczegółów administracyjnych” na końcu (oznaczone `admin`). Pasek układa
 * je po krokach funkcją `missingInStepOrder`.
 */
export function b2bFormMissing(s: B2BFormSnapshot): GeneratorMissing[] {
  const out: GeneratorMissing[] = [];
  const need = (
    ok: boolean,
    step: GeneratorFormStep,
    label: string,
    field: string,
  ) => {
    if (!ok) out.push({ step, label, field });
  };
  need(s.hasCandidate, "zrodlo", "Kandydat", "candidate");
  need(s.hasRecruitment, "zrodlo", "Rekrutacja", "recruitment");
  need(s.hasRole, "obszar", "Obszar usług", "role");
  if (s.isCompany) {
    for (const label of companyVariantMissing(s.company)) {
      out.push({ step: "partner", label, field: COMPANY_FIELD[label] ?? "" });
    }
  } else {
    need(
      Boolean(s.partnerName.trim()),
      "partner",
      "Imię i nazwisko Partnera",
      "partnerName",
    );
    need(
      Boolean(s.partnerInstrumental.trim()),
      "partner",
      "Imię i nazwisko (narzędnik)",
      "partnerInstrumental",
    );
  }
  need(Boolean(s.partnerLegalName.trim()), "partner", "Nazwa Firmy", "legalName");
  need(Boolean(s.partnerNip.trim()), "partner", "NIP", "nip");
  need(Boolean(s.partnerRegon.trim()), "partner", "REGON", "regon");
  need(
    Boolean(s.partnerBusinessAddress.trim()),
    "partner",
    s.isCompany ? "Adres siedziby firmy" : "Adres z CEIDG",
    "address",
  );
  need(Boolean(s.partnerEmail.trim()), "partner", "E-mail", "email");
  need(Boolean(s.partnerPhone.trim()), "partner", "Telefon", "phone");
  need(Boolean(s.clientName.trim()), "klient", "Pełna nazwa Klienta", "client");
  need(Boolean(s.projectCity.trim()), "klient", "Miasto Klienta", "city");
  need(
    Boolean(s.projectDescription.trim()),
    "klient",
    "Opis projektu",
    "description",
  );
  need(Boolean(s.contractNumber.trim()), "warunki", "Numer umowy", "number");
  need(Boolean(s.signingDate), "warunki", "Data podpisania", "signingDate");
  need(Boolean(s.startDate), "warunki", "Data rozpoczęcia", "startDate");
  if (s.rateStages.length <= 1) {
    const rate = parseRateInput(s.rateStages[0]?.rate ?? "");
    need(Boolean(rate && rate > 0), "warunki", "Stawka godzinowa", "rate-0");
  } else {
    // Stawka progresywna: każdy etap z kwotą; etapy 2+ muszą mieć „od”.
    s.rateStages.forEach((stage, i) => {
      const rate = parseRateInput(stage.rate);
      need(
        Boolean(rate && rate > 0),
        "warunki",
        `Stawka godzinowa (etap ${i + 1})`,
        `rate-${i}`,
      );
      if (i > 0) {
        need(
          Boolean(stage.from),
          "warunki",
          `„Obowiązuje od” (etap ${i + 1})`,
          `rateFrom-${i}`,
        );
      }
    });
  }
  // Replacement i FTE są obowiązkowe przy umowie z rekrutacją (serwer: 422).
  if (s.hasRecruitment) {
    const a = s.admin;
    if (a.isReplacement === null) {
      out.push({ step: "admin", label: "Replacement", field: "replacement", admin: true });
    }
    if (a.fte === null) {
      out.push({ step: "admin", label: "Wymiar FTE", field: "fte", admin: true });
    }
    if (a.isReplacement === true && a.replaced === null) {
      out.push({
        step: "admin",
        label: "Replacement za kogo",
        field: "replaced",
        admin: true,
      });
    }
  }
  return out;
}

/** Etykiety do komunikatu „Uzupełnij wymagane pola: …” (bez braków admin). */
export function validationMissingLabels(
  missing: readonly GeneratorMissing[],
): string[] {
  return missing.filter((m) => !m.admin).map((m) => m.label);
}

/** Braki ułożone po krokach (kolejność wewnątrz kroku bez zmian). */
export function missingInStepOrder(
  missing: readonly GeneratorMissing[],
): GeneratorMissing[] {
  return missing
    .map((m, i) => ({ m, i }))
    .sort((a, b) => stepIndex(a.m.step) - stepIndex(b.m.step) || a.i - b.i)
    .map(({ m }) => m);
}

export function missingInStep(
  missing: readonly GeneratorMissing[],
  step: GeneratorStep,
): GeneratorMissing[] {
  return missing.filter((m) => m.step === step);
}

/** „Brakuje 1 pola” / „Brakuje 3 pól”. */
export function missingCountLabel(count: number): string {
  return `Brakuje ${countPl(count, "pola", "pól", "pól")}`;
}

/** „1 brak” / „3 braki” / „5 braków” — stan kroku na liście kroków. */
export function gapsLabel(count: number): string {
  return countPl(count, "brak", "braki", "braków");
}

// ── Podsumowanie kroku na liście kroków ─────────────────────────────────────

export interface StepSummaryInput {
  candidateName: string | null;
  jobTitle: string | null;
  language: "pl" | "en";
  admin: AgreementAdminValue;
  hasRecruitment: boolean;
  partnerLegalName: string;
  partnerName: string;
  clientName: string;
  projectCity: string;
  roleName: string | null;
  contractNumber: string;
  startDate: string;
  rateStages: readonly RateStageInput[];
  currency: string;
}

const FTE_TEXT: Record<string, string> = {
  "1": "1",
  "0.75": "0,75",
  "0.5": "0,5",
  "0.25": "0,25",
};

/**
 * Jedna linia pod nazwą kroku: braki, a przy komplecie to, co wpisano
 * („Jan Kowalski · Java Developer”). Krok bez braków i bez danych (np.
 * „Szczegóły administracyjne” przed wyborem rekrutacji) mówi, od czego zależy.
 */
export function stepSummary(
  step: GeneratorStep,
  input: StepSummaryInput,
  missing: readonly GeneratorMissing[],
): string {
  if (step === "pobierz") {
    return missing.length === 0
      ? "gotowe do pobrania"
      : missingCountLabel(missing.length).replace("Brakuje", "brakuje");
  }
  const gaps = missingInStep(missing, step).length;
  if (gaps > 0) return gapsLabel(gaps);
  switch (step) {
    case "zrodlo":
      return [
        input.candidateName,
        input.jobTitle,
        input.language === "en" ? "po angielsku" : null,
      ]
        .filter(Boolean)
        .join(" · ");
    case "admin": {
      if (!input.hasRecruitment) return "po wybraniu rekrutacji";
      const a = input.admin;
      return [
        a.isReplacement ? "replacement" : "bez replacementu",
        a.fte ? `${FTE_TEXT[a.fte] ?? a.fte} FTE` : null,
        a.isClientReferral ? "wskazany przez klienta" : null,
      ]
        .filter(Boolean)
        .join(" · ");
    }
    case "partner":
      return input.partnerLegalName.trim() || input.partnerName.trim();
    case "klient":
      return [input.clientName.trim(), input.projectCity.trim()]
        .filter(Boolean)
        .join(" · ");
    case "obszar":
      return input.roleName ?? "";
    case "warunki": {
      const stages = input.rateStages;
      const unit = input.currency === "PLN" ? "zł/h" : `${input.currency}/h`;
      const rate =
        stages.length > 1
          ? `stawka progresywna (${countPl(stages.length, "etap", "etapy", "etapów")})`
          : `${(stages[0]?.rate ?? "").trim().replace(".", ",")} ${unit}`;
      return [
        input.contractNumber.trim(),
        input.startDate ? `od ${formatIsoDatePl(input.startDate)}` : null,
        rate,
      ]
        .filter(Boolean)
        .join(" · ");
    }
  }
}
