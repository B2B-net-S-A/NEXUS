/**
 * Dwa powody klienta z odczytu maili CPro (0740, 19.11.2026, sprawa B7). Od
 * jednego słownika (0745) inny dostawca to „Pracuje u klienta / zgłoszona przez
 * inną firmę” — wybieramy go też my; słaba rozmowa zostaje tylko przy kliencie.
 */
import { describe, expect, it } from "vitest";

import { closeReasonGroups, closeTemplateName, type CloseWho } from "@/lib/close-reasons";
import { CLIENT_INTERVIEW_WEAK_REASON, CLIENT_OTHER_VENDOR_REASON } from "@/lib/rejection-reasons";

const templateNames = (who: CloseWho, early: boolean) =>
  closeReasonGroups(who, early).flatMap((g) => g.reasons.map((r) => closeTemplateName(r.key, who)));

describe("powody klienta z CPro", () => {
  it("słabą rozmowę widać tylko przy „Odrzuca klient”", () => {
    expect(templateNames("client", false)).toContain(CLIENT_INTERVIEW_WEAK_REASON);
    expect(templateNames("recruiter", true)).not.toContain(CLIENT_INTERVIEW_WEAK_REASON);
    expect(templateNames("candidate", true)).not.toContain(CLIENT_INTERVIEW_WEAK_REASON);
  });

  it("„Pracuje u klienta / zgłoszona przez inną firmę” wybieramy też my", () => {
    expect(templateNames("client", false)).toContain(CLIENT_OTHER_VENDOR_REASON);
    expect(templateNames("recruiter", false)).toContain(CLIENT_OTHER_VENDOR_REASON);
  });

  it("dane w bazie tylko w „Nowych” i „Screeningu”", () => {
    for (const name of ["outdated_cv", "profile_mismatch", "wrong_phone"]) {
      expect(templateNames("recruiter", false)).not.toContain(name);
      expect(templateNames("recruiter", true)).toContain(name);
    }
  });
});
