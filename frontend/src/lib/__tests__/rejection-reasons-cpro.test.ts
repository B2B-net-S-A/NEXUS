/**
 * Dwa powody klienta z odczytu maili CPro (0740, 19.11.2026, sprawa B7). Od
 * jednego słownika (0745) inny dostawca to „Pracuje u klienta / zgłoszona przez
 * inną firmę” — wybieramy go też my; słaba rozmowa zostaje tylko przy kliencie.
 */
import { describe, expect, it } from "vitest";

import {
  CLIENT_INTERVIEW_WEAK_REASON,
  CLIENT_OTHER_VENDOR_REASON,
  reasonFitsEndedBy,
} from "@/lib/rejection-reasons";

describe("powody klienta z CPro", () => {
  it("słabą rozmowę widać tylko przy „Odrzuca klient”", () => {
    const name = CLIENT_INTERVIEW_WEAK_REASON;
    expect(reasonFitsEndedBy({ name }, "client")).toBe(true);
    expect(reasonFitsEndedBy({ name }, "recruiter")).toBe(false);
    expect(reasonFitsEndedBy({ name }, "delivery_lead")).toBe(false);
    expect(reasonFitsEndedBy({ name }, "candidate")).toBe(false);
  });

  it("„Pracuje u klienta / zgłoszona przez inną firmę” wybieramy też my", () => {
    const name = CLIENT_OTHER_VENDOR_REASON;
    expect(reasonFitsEndedBy({ name }, "client")).toBe(true);
    expect(reasonFitsEndedBy({ name }, "recruiter")).toBe(true);
  });

  it("dane w bazie nie pojawiają się na liście z szablonu", () => {
    for (const name of ["outdated_cv", "profile_mismatch", "wrong_phone"]) {
      expect(reasonFitsEndedBy({ name }, "recruiter")).toBe(false);
    }
  });
});
