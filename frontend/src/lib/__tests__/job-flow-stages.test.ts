/**
 * Podział kolumn na krok 07 („u klienta") i 08 („umowa").
 *
 * Ten podział jest łatwy do zepsucia w JEDEN sposób: etapy podpisu („Umowa
 * wysłana", „Umowa podpisana") NIE mają `legacy_enum_value`, więc backend
 * raportuje dla nich `stage: "new"` i kategorię `external`. Naiwna reguła
 * „external = rozmowy" wciąga je do kroku 07, a krok 08 zostaje pusty przy
 * kandydacie, który właśnie czeka na podpis. Nazwy są jedynym identyfikatorem,
 * jaki system dla nich ma — po obu stronach tak samo
 * (`services/signing/pipeline_hook.py`).
 */

import { describe, expect, it } from "vitest";

import {
  CONTRACT_STAGE_NAMES,
  isContractStage,
  isInterviewStage,
} from "@/lib/job-flow-stages";

const col = (
  stage: string,
  name: string,
  category?: "internal" | "external" | "terminal",
  terminal_type?: "hired" | "rejected" | "withdrawn" | null,
) => ({ stage, name, category, terminal_type });

describe("isInterviewStage", () => {
  it("łapie etapy zewnętrzne, na których kandydat jest u klienta", () => {
    expect(
      isInterviewStage(col("client_interview", "Interview Klient", "external")),
    ).toBe(true);
    expect(isInterviewStage(col("acceptance", "Akceptacja", "external"))).toBe(
      true,
    );
    expect(isInterviewStage(col("negotiation", "Negocjacje", "external"))).toBe(
      true,
    );
  });

  it("nie łapie etapów wewnętrznych ani terminalnych", () => {
    expect(isInterviewStage(col("cv_sent", "CV Wysłane", "internal"))).toBe(
      false,
    );
    expect(
      isInterviewStage(col("hired", "Zatrudniony", "terminal", "hired")),
    ).toBe(false);
    expect(
      isInterviewStage(col("rejected", "Odrzucony", "terminal", "rejected")),
    ).toBe(false);
  });

  it("NIE łapie etapów podpisu, mimo że są `external` i mają stage='new'", () => {
    // To jest ten defekt: bez wyłączenia po nazwie kandydat czekający na
    // podpis siedziałby w kroku „Rozmowy i decyzja", a krok „Umowa" byłby pusty.
    expect(isInterviewStage(col("new", "Umowa wysłana", "external"))).toBe(
      false,
    );
    expect(isInterviewStage(col("new", "Umowa podpisana", "external"))).toBe(
      false,
    );
  });

  it("onboarding należy do umowy, nie do rozmów", () => {
    expect(isInterviewStage(col("onboarding", "Onboarding", "external"))).toBe(
      false,
    );
  });
});

describe("isContractStage", () => {
  it("łapie etapy podpisu po nazwie", () => {
    for (const name of CONTRACT_STAGE_NAMES) {
      expect(isContractStage(col("new", name, "external"))).toBe(true);
    }
  });

  it("rozpoznaje zatrudnienie po `terminal_type`, nie po nazwie", () => {
    // Własny etap terminalny bez mapowania na legacy enum — dokładnie ten
    // przypadek, dla którego istnieje `terminalOf`.
    expect(
      isContractStage(col("new", "Zaakceptowany do pracy", "terminal", "hired")),
    ).toBe(true);
  });

  it("nie łapie odrzucenia ani wycofania", () => {
    expect(
      isContractStage(col("rejected", "Odrzucony", "terminal", "rejected")),
    ).toBe(false);
    expect(
      isContractStage(col("withdrawn", "Wycofany", "terminal", "withdrawn")),
    ).toBe(false);
  });

  it("nazwa etapu podpisu jest dopasowywana bez oglądania się na wielkość liter", () => {
    expect(isContractStage(col("new", "  UMOWA WYSŁANA  ", "external"))).toBe(
      true,
    );
  });

  it("dwa zbiory są rozłączne dla całego szablonu Default B2B", () => {
    const template = [
      col("new", "Nowi / Analiza CV", "internal"),
      col("prep_call", "Preparation Call", "internal"),
      col("screening", "Screening", "internal"),
      col("verified", "Zweryfikowany", "internal"),
      col("interview", "Interview Wewnętrzny", "internal"),
      col("cv_sent", "CV Wysłane", "internal"),
      col("client_interview", "Interview Klient", "external"),
      col("acceptance", "Akceptacja", "external"),
      col("negotiation", "Negocjacje", "external"),
      col("new", "Umowa wysłana", "external"),
      col("new", "Umowa podpisana", "external"),
      col("hired", "Zatrudniony", "terminal", "hired"),
      col("onboarding", "Onboarding", "external"),
      col("rejected", "Odrzucony", "terminal", "rejected"),
      col("withdrawn", "Wycofany", "terminal", "withdrawn"),
    ];
    expect(template.filter((c) => isInterviewStage(c) && isContractStage(c))).toEqual(
      [],
    );
    expect(template.filter(isInterviewStage).map((c) => c.name)).toEqual([
      "Interview Klient",
      "Akceptacja",
      "Negocjacje",
    ]);
    expect(template.filter(isContractStage).map((c) => c.name)).toEqual([
      "Umowa wysłana",
      "Umowa podpisana",
      "Zatrudniony",
      "Onboarding",
    ]);
  });
});
