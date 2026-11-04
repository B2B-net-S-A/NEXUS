import { describe, expect, it } from "vitest";
import { eligibilityWarningBadges } from "@/lib/eligibility-reason-labels";
import type { EmploymentMarker } from "@/lib/employment-marker";

const AT_THIS_CLIENT: EmploymentMarker = {
  phase: "working",
  source: "contract",
  elsewhere: false,
  clients: [{ client_id: 1, client_name: "Bank Przykładowy", contract_id: 10, phase: "working" }],
};

describe("eligibilityWarningBadges", () => {
  it("rysuje konflikty z klientem, pomija kody z własnymi odznakami", () => {
    expect(
      eligibilityWarningBadges(["hm_veto", "budget_exceeded", "client_nda", "client_competitor"]).map((b) => [
        b.code,
        b.label,
        b.tone,
      ]),
    ).toEqual([
      ["client_nda", "NDA z klientem", "warning"],
      ["client_competitor", "konkurent klienta", "warning"],
    ]);
  });

  it("konflikt to ostrzeżenie z możliwym ruchem, czarna lista — nie", () => {
    const [nda] = eligibilityWarningBadges(["client_nda"]);
    expect(nda.title).toBe("Konflikt: NDA z klientem. Ostrzeżenie — ruch jest możliwy po potwierdzeniu.");
    const [banned] = eligibilityWarningBadges(["blacklisted"]);
    expect(banned).toMatchObject({ tone: "danger", title: "Kandydat na globalnej czarnej liście" });
  });

  it("„pracuje u tego klienta” nie dubluje znacznika zatrudnienia", () => {
    expect(eligibilityWarningBadges(["client_current_employment"], AT_THIS_CLIENT)).toEqual([]);
    // Bez znacznika (albo gdy mówi o innym kliencie) odznaka zostaje.
    expect(eligibilityWarningBadges(["client_current_employment"]).map((b) => b.label)).toEqual([
      "pracuje u tego klienta",
    ]);
    expect(
      eligibilityWarningBadges(["client_current_employment"], { ...AT_THIS_CLIENT, elsewhere: true }),
    ).toHaveLength(1);
  });

  it("nieznany kod nie znika — dostaje ogólną etykietę", () => {
    expect(eligibilityWarningBadges(["nowy_kod"])).toEqual([
      {
        code: "nowy_kod",
        label: "ostrzeżenie",
        title: "Ostrzeżenie: nowy_kod. Ostrzeżenie — ruch jest możliwy po potwierdzeniu.",
        tone: "warning",
      },
    ]);
  });

  it("brak listy to brak odznak", () => {
    expect(eligibilityWarningBadges(undefined)).toEqual([]);
    expect(eligibilityWarningBadges(null)).toEqual([]);
  });
});
