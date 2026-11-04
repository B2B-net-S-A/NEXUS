import { describe, expect, it } from "vitest";

import {
  contributionsBadge,
  contributionsReminder,
  contributionsStart,
  dayLabel,
  poolAllowed,
  statutoryEntitlement,
} from "../form-rules";
import { EMPTY_PROFILE_FORM, profileFormToPayload } from "../ProfileFieldsForm";

// Reguły kartoteki według formy (etap 2, D6, D8, D9) — lustro serwera.

describe("uczeń/student na zleceniu (D8)", () => {
  it("składki od dnia po końcu zwolnienia, przypomnienie 30 dni wcześniej", () => {
    expect(contributionsStart("2027-06-30")).toBe("2027-07-01");
    expect(contributionsStart("2027-12-31")).toBe("2028-01-01");
    expect(contributionsReminder("2027-06-30")).toBe("2027-05-31");
    expect(contributionsReminder("2028-03-30")).toBe("2028-02-29");
    expect(contributionsStart(null)).toBeNull();
    expect(contributionsStart("zła data")).toBeNull();
    expect(dayLabel("2027-07-01")).toBe("01.07.2027");
  });

  it("plakietka „składki od MM.RRRR”", () => {
    expect(contributionsBadge("2027-07-01")).toBe("składki od 07.2027");
    expect(contributionsBadge(null)).toBeNull();
  });
});

describe("pula i staż (D6, D9)", () => {
  it("zlecenie bez puli płatnych dni", () => {
    expect(poolAllowed("zlecenie")).toBe(false);
    expect(poolAllowed("b2b")).toBe(true);
    expect(poolAllowed("uop")).toBe(true);
  });

  it("wymiar 20 albo 26 dni tylko na umowie o pracę ze stażem", () => {
    expect(statutoryEntitlement("uop", 9)).toBe(20);
    expect(statutoryEntitlement("uop", 10)).toBe(26);
    expect(statutoryEntitlement("uop", null)).toBeNull();
    expect(statutoryEntitlement("b2b", 15)).toBeNull();
  });
});

describe("zapis kartoteki: pola formy tylko przy tej formie", () => {
  const base = { ...EMPTY_PROFILE_FORM, student: true, exempt_until: "2027-06-30", seniority: "12", zus_certificate: "2026-05-04" };

  it("zlecenie wysyła znacznik i datę, bez stażu", () => {
    const payload = profileFormToPayload({ ...base, employment_type: "zlecenie" });
    expect(payload.student_contribution_exempt).toBe(true);
    expect(payload.contribution_exempt_until).toBe("2027-06-30");
    expect(payload).not.toHaveProperty("leave_seniority_years");
    const off = profileFormToPayload({ ...base, employment_type: "zlecenie", student: false });
    expect(off.contribution_exempt_until).toBeNull();
  });

  it("umowa o pracę wysyła staż i zaświadczenie, bez znacznika studenta", () => {
    const payload = profileFormToPayload({ ...base, employment_type: "uop" });
    expect(payload.leave_seniority_years).toBe(12);
    expect(payload.zus_certificate_received_on).toBe("2026-05-04");
    expect(payload).not.toHaveProperty("student_contribution_exempt");
    expect(profileFormToPayload({ ...base, employment_type: "uop", seniority: " " }).leave_seniority_years).toBeNull();
  });

  it("B2B i formularze bez tych pól (Dodaj osobę) nie wysyłają ich wcale", () => {
    const b2b = profileFormToPayload({ ...base, employment_type: "b2b" });
    expect(b2b).not.toHaveProperty("student_contribution_exempt");
    expect(b2b).not.toHaveProperty("leave_seniority_years");
    const plain = profileFormToPayload({ ...EMPTY_PROFILE_FORM, employment_type: "zlecenie" });
    expect(plain).not.toHaveProperty("student_contribution_exempt");
  });
});
