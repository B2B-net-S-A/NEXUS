/**
 * Jeden słownik powodów zamknięcia procesu (19.11.2026, wariant A): grupy
 * zależą od „Kto kończy?” i etapu, powód z szablonu wynika 1:1.
 */
import { describe, expect, it } from "vitest";

import { AUTOFILL_TEMPLATE_REASON } from "@/lib/autofill-feedback";
import {
  CLOSE_REASON_GROUPS,
  closeReasonGroups,
  closeTemplateOptions,
  closeTemplateReason,
  closeWhoFor,
} from "@/lib/close-reasons";

const keysOf = (groups: ReturnType<typeof closeReasonGroups>) =>
  groups.flatMap((g) => g.reasons.map((r) => r.key));

describe("closeReasonGroups", () => {
  it("my w „Nowych”: bez grupy klienta i bez powodów tylko kandydata", () => {
    const groups = closeReasonGroups("recruiter", true);
    expect(groups.map((g) => g.title)).toEqual([
      "Nie pasuje do wymagań",
      "Warunki",
      "Sprawa osoby",
      "Dane w bazie",
    ]);
    const keys = keysOf(groups);
    expect(keys).not.toContain("counter_offer");
    expect(keys).toContain("in_other_process");
  });

  it("„Dane w bazie” znikają od „Zweryfikowanego”", () => {
    const keys = keysOf(closeReasonGroups("recruiter", false));
    expect(keys).not.toContain("outdated_cv");
    expect(keys).not.toContain("wrong_phone");
  });

  it("klient: grupa „Klient” na początku, bez spraw tylko osoby", () => {
    const groups = closeReasonGroups("client", false);
    expect(groups[0].title).toBe("Klient");
    expect(groups[0].reasons.map((r) => r.label)).toContain("Projekt zamknięty / przetarg przegrany");
    const keys = keysOf(groups);
    expect(keys).not.toContain("not_looking");
    expect(keys).not.toContain("in_other_process");
    expect(keys).toContain("client_employed");
  });

  it("kandydat: tylko warunki i sprawy osoby", () => {
    const groups = closeReasonGroups("candidate", true);
    expect(groups.map((g) => g.title)).toEqual(["Warunki", "Sprawa osoby"]);
    expect(keysOf(groups)).toEqual(
      expect.arrayContaining(["counter_offer", "lost_interest", "personal_reasons", "too_expensive"]),
    );
    expect(keysOf(groups)).not.toContain("missing_skill");
  });

  it("Delivery Lead wybiera jak my", () => {
    expect(closeWhoFor("delivery_lead")).toBe("recruiter");
    expect(closeWhoFor("recruiter")).toBe("recruiter");
    expect(closeWhoFor("client")).toBe("client");
    expect(closeWhoFor("candidate")).toBe("candidate");
  });
});

describe("closeTemplateReason", () => {
  const rows = [
    { id: "1", name: "Brak doświadczenia", label: "Za mało doświadczenia" },
    { id: "2", name: "client_project_closed", label: "Klient zamknął projekt" },
    { id: "3", name: "salary_mismatch", label: "Za droga" },
    { id: "4", name: "Za wysokie oczekiwania finansowe", label: "Za droga" },
    { id: "9", name: "Inne (rejected)", label: "Inne" },
  ];

  it("powód idzie do własnego wiersza strony, która kończy", () => {
    expect(closeTemplateReason("too_junior", "recruiter", rows)?.id).toBe("1");
    expect(closeTemplateReason("client_project_closed", "client", rows)?.id).toBe("2");
    expect(closeTemplateReason("too_expensive", "recruiter", rows)?.id).toBe("4");
    expect(closeTemplateReason("too_expensive", "candidate", rows)?.id).toBe("3");
  });

  it("szablon bez wiersza wraca do „Inne”, a bez „Inne” — do niczego", () => {
    expect(closeTemplateReason("no_polish", "recruiter", rows)?.id).toBe("9");
    expect(closeTemplateReason("no_polish", "recruiter", rows.slice(0, 4))).toBeUndefined();
    expect(closeTemplateReason(null, "recruiter", rows)).toBeUndefined();
  });
});

describe("closeTemplateOptions", () => {
  it("kolejność i etykiety słownika, bez wierszy spoza niego, „Inne” na końcu", () => {
    const rows = [
      { id: "9", name: "Inne (rejected)", label: "Inne" },
      { id: "5", name: "Kandydat się wycofał", label: "Kandydat się wycofał" },
      { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia" },
      { id: "6", name: "client_chose_other", label: "Klient wybrał kogoś innego" },
      { id: "7", name: "not_looking_for_work", label: "Nie szuka pracy" },
    ];
    expect(closeTemplateOptions(rows, "client").map((r) => [r.id, r.label])).toEqual([
      ["6", "Wybrał innego kandydata"],
      ["1", "Za mało doświadczenia"],
      ["9", "Inne"],
    ]);
    expect(closeTemplateOptions(rows, "recruiter").map((r) => r.id)).toEqual(["1", "7", "9"]);
  });
});

describe("lustro mapy powodów dla systemu", () => {
  it("każdy powód odrzucenia słownika ma ten sam wiersz co mapa 1:1", () => {
    for (const reason of CLOSE_REASON_GROUPS.flatMap((g) => g.reasons)) {
      if (!reason.rejected) continue;
      expect(AUTOFILL_TEMPLATE_REASON[reason.key as keyof typeof AUTOFILL_TEMPLATE_REASON]).toBe(
        reason.rejected,
      );
    }
  });
});
