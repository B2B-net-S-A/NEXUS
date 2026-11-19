/**
 * Dwa powody klienta z odczytu maili CPro (0741, 19.11.2026, sprawa B7): tylko
 * przy „Odrzuca klient”, w grupie „Klient” okna odrzucenia.
 */
import { describe, expect, it } from "vitest";

import {
  CLIENT_INTERVIEW_WEAK_REASON,
  CLIENT_OTHER_VENDOR_REASON,
  groupRejectedReasons,
  reasonFitsEndedBy,
} from "@/lib/rejection-reasons";

const NEW = [CLIENT_OTHER_VENDOR_REASON, CLIENT_INTERVIEW_WEAK_REASON];

describe("powody klienta z CPro", () => {
  it.each(NEW)("%s widać tylko przy „Odrzuca klient”", (name) => {
    expect(reasonFitsEndedBy({ name }, "client")).toBe(true);
    expect(reasonFitsEndedBy({ name }, "recruiter")).toBe(false);
    expect(reasonFitsEndedBy({ name }, "delivery_lead")).toBe(false);
    expect(reasonFitsEndedBy({ name }, "candidate")).toBe(false);
  });

  it("stoją w grupie „Klient” po dwóch dotychczasowych", () => {
    const groups = groupRejectedReasons(
      ["client_no_reason", "client_chose_other", ...NEW, "Inne (rejected)"].map((name) => ({ name })),
    );
    expect(groups[0]).toEqual({
      title: "Klient",
      reasons: [
        { name: "client_no_reason" },
        { name: "client_chose_other" },
        { name: CLIENT_OTHER_VENDOR_REASON },
        { name: CLIENT_INTERVIEW_WEAK_REASON },
      ],
    });
    expect(groups.at(-1)).toEqual({ title: "Pozostałe", reasons: [{ name: "Inne (rejected)" }] });
  });
});
