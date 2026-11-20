/**
 * Parametr `aneks=` (wariant A, 19.11.2026): przycisk „Dodaj aneks”
 * w nagłówku kontraktu otwiera zakładkę z właściwym oknem.
 */
import { describe, expect, it } from "vitest";

import { B2B_EXTENSION_HINT } from "@/lib/contract-end-date";
import {
  annexIntentHref,
  annexRefusalText,
  hrefWithoutAnnexParam,
  parseAnnexIntent,
  resolveAnnexIntent,
  type AnnexIntentGates,
} from "@/components/contracts/amendments/annex-intent";

const OPEN: AnnexIntentGates = {
  readOnly: false,
  canAmendRates: true,
  extensionLocked: false,
  canTerminate: true,
};

describe("aneks= w adresie", () => {
  it("zna pięć okien, reszta to nic", () => {
    for (const value of ["rate_change", "scope_change", "extension", "early_termination", "document"]) {
      expect(parseAnnexIntent(value)).toBe(value);
    }
    expect(parseAnnexIntent("delete")).toBeNull();
    expect(parseAnnexIntent("")).toBeNull();
    expect(parseAnnexIntent(null)).toBeNull();
  });

  it("z uprawnieniami: formularz, zakończenie albo generator", () => {
    expect(resolveAnnexIntent("rate_change", OPEN)).toEqual({ kind: "form", type: "rate_change" });
    expect(resolveAnnexIntent("scope_change", OPEN)).toEqual({ kind: "form", type: "scope_change" });
    expect(resolveAnnexIntent("extension", OPEN)).toEqual({ kind: "form", type: "extension" });
    expect(resolveAnnexIntent("early_termination", OPEN)).toEqual({ kind: "terminate" });
    expect(resolveAnnexIntent("document", OPEN)).toEqual({ kind: "document" });
  });

  it("te same bramki co menu „Dodaj aneks” — odmowa mówi dlaczego", () => {
    const noRates = { ...OPEN, canAmendRates: false };
    expect(resolveAnnexIntent("rate_change", noRates)).toEqual({ kind: "refused" });
    expect(annexRefusalText("rate_change", noRates)).toContain("„Stawki i kwoty: zmiana”");

    const locked = { ...OPEN, extensionLocked: true };
    expect(resolveAnnexIntent("extension", locked)).toEqual({ kind: "refused" });
    expect(annexRefusalText("extension", locked)).toBe(B2B_EXTENSION_HINT);
    expect(annexRefusalText("extension", locked, "Konsultant wycofał wypowiedzenie?")).toBe(
      "Konsultant wycofał wypowiedzenie?",
    );

    const noStatus = { ...OPEN, canTerminate: false };
    expect(resolveAnnexIntent("early_termination", noStatus)).toEqual({ kind: "refused" });
    expect(annexRefusalText("early_termination", noStatus)).toContain("zmiana statusu kontraktu");

    const readOnly = { ...OPEN, readOnly: true };
    for (const intent of ["rate_change", "scope_change", "extension", "early_termination", "document"] as const) {
      expect(resolveAnnexIntent(intent, readOnly)).toEqual({ kind: "refused" });
    }
    expect(annexRefusalText("scope_change", readOnly)).toMatch(/trybie podglądu/);
  });

  it("adres dla przycisku w nagłówku: zakładka „Aneksy” z oknem, kontekst powrotu zostaje", () => {
    expect(annexIntentHref("/contracts/5", "?from=contracts&returnTo=%2Fcontracts", "rate_change")).toBe(
      "/contracts/5?from=contracts&returnTo=%2Fcontracts&tab=amendments&aneks=rate_change",
    );
    // Z innej zakładki (i dawny `note=` z notatek) — przejście na „Aneksy”.
    expect(annexIntentHref("/contracts/5", "?tab=care&note=4", "document")).toBe(
      "/contracts/5?tab=amendments&aneks=document",
    );
  });

  it("zdjęcie parametru zostawia ścieżkę, zakładkę, kontekst powrotu i kotwicę", () => {
    expect(hrefWithoutAnnexParam("/contracts/5?tab=amendments&aneks=rate_change&from=contracts#top")).toBe(
      "/contracts/5?tab=amendments&from=contracts#top",
    );
    expect(hrefWithoutAnnexParam("/contracts/5?aneks=document")).toBe("/contracts/5");
    expect(hrefWithoutAnnexParam("/contracts/5?tab=amendments")).toBe("/contracts/5?tab=amendments");
  });
});
