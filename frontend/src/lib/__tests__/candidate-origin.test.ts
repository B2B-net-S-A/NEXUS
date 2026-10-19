import { describe, expect, it } from "vitest";

import { candidateOrigin, originSummary } from "@/lib/candidate-origin";

const INVITE = {
  label: "Post na LinkedIn",
  created_by_name: "Jan Kowalski",
  applied_at: "2026-10-18T12:32:00Z",
  previous_created_by_name: null,
  link_kind: "recruiter" as const,
  utm_source: "linkedin",
};

describe("candidateOrigin — skąd osoba jest w bazie", () => {
  it("stały link rekrutera: sposób, właściciel linku, nazwa linku i wejście z utm", () => {
    const origin = candidateOrigin({
      added_via: "Formularz aplikacyjny",
      created_by_user: { id: 7, name: "Jan Kowalski" },
      invite_source: INVITE,
    });
    expect(origin).toEqual({
      how: "Link rekrutera",
      by: "Jan Kowalski",
      viaLink: true,
      linkLabel: "Post na LinkedIn",
      entryFrom: "LinkedIn",
      previousBy: null,
    });
    expect(originSummary(origin)).toBe("Link rekrutera · Jan Kowalski");
  });

  it("link do rekrutacji i link bez zapisanego rodzaju", () => {
    expect(
      candidateOrigin({ invite_source: { ...INVITE, link_kind: "job", utm_source: null } }).how,
    ).toBe("Link do rekrutacji");
    const legacy = candidateOrigin({ invite_source: { ...INVITE, link_kind: null } });
    expect(legacy.how).toBe("Formularz aplikacyjny");
    expect(legacy.viaLink).toBe(true);
  });

  it("dodany w NEXUSIE: sposób z `added_via` i „dodał(a)” z twórcy", () => {
    const origin = candidateOrigin({
      added_via: "Wtyczka LinkedIn",
      created_by_user: { id: 3, name: "Anna Test" },
    });
    expect(origin.how).toBe("Wtyczka LinkedIn");
    expect(origin.viaLink).toBe(false);
    expect(originSummary(origin)).toBe("Wtyczka LinkedIn · dodał(a) Anna Test");
  });

  it("nie zgaduje: bez twórcy mówi tylko sposób, bez niczego — null", () => {
    const traffit = candidateOrigin({ added_via: "Traffit", created_by_user: null });
    expect(originSummary(traffit)).toBe("Traffit");
    const nothing = candidateOrigin({});
    expect(nothing.how).toBeNull();
    expect(originSummary(nothing)).toBeNull();
  });

  it("myślnik zamiast nazwiska z API to brak osoby, nie „dodał(a) —”", () => {
    const origin = candidateOrigin({
      invite_source: { ...INVITE, created_by_name: "—" },
      created_by_user: null,
    });
    expect(origin.by).toBeNull();
    expect(originSummary(origin)).toBe("Link rekrutera");
  });

  it("przejęcie przez link i utm, którego nie znamy z nazwy", () => {
    const origin = candidateOrigin({
      invite_source: { ...INVITE, previous_created_by_name: "Ewa Test", utm_source: " newsletter_10 " },
    });
    expect(origin.previousBy).toBe("Ewa Test");
    expect(origin.entryFrom).toBe("newsletter_10");
  });
});
