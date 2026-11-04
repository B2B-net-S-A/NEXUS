import { describe, expect, it } from "vitest";

import {
  absenceShortText,
  insertAfterMention,
  mentionedEmails,
  substituteHint,
  substituteHintText,
} from "@/components/v2/forms/mention-absence";

const users = [
  { id: 1, name: "Ola Przykładowa", email: "ola@example.com", role: "recruiter" },
  { id: 2, name: "Kamil Testowy", email: "Kamil@example.com", role: "delivery_lead" },
];
const away = {
  user_id: 2,
  until: "2026-10-23",
  half_day: null,
  substitute_user_id: 1,
  substitute_name: "Ola Przykładowa",
};

describe("absenceShortText", () => {
  it("do kiedy z dniem tygodnia, dziś i pół dnia", () => {
    expect(absenceShortText(away, "2026-10-22")).toBe("nieobecność do pt 23.10");
    expect(absenceShortText(away, "2026-10-23")).toBe("nieobecność dziś");
    expect(absenceShortText({ ...away, half_day: "morning" }, "2026-10-23")).toBe(
      "nieobecność dziś (pół dnia)",
    );
  });
});

describe("mentionedEmails", () => {
  it("czyta adresy jak parser serwera, bez wielkości liter", () => {
    expect([...mentionedEmails("hej @Kamil@example.com, i @ola@example.com.")]).toEqual([
      "kamil@example.com",
      "ola@example.com",
    ]);
    expect(mentionedEmails("pisz na biuro@example.com").size).toBe(0);
  });
});

describe("substituteHint", () => {
  const absences = new Map([[2, away]]);

  it("osoba oznaczona, nieobecna, z zastępcą jeszcze nieoznaczonym", () => {
    const hint = substituteHint("@kamil@example.com prośba", 2, users, absences);
    expect(hint?.substitute.id).toBe(1);
    expect(substituteHintText(hint!, "2026-10-22")).toBe(
      "Kamil Testowy — nieobecność do pt 23.10. Oznaczyć też zastępcę (Ola Przykładowa)?",
    );
  });

  it("bez podpowiedzi: osoba usunięta z tekstu, zastępca już jest, zastępcy nie ma na liście", () => {
    expect(substituteHint("prośba", 2, users, absences)).toBeNull();
    expect(
      substituteHint("@kamil@example.com @ola@example.com", 2, users, absences),
    ).toBeNull();
    expect(substituteHint("@kamil@example.com", 2, users.slice(1), absences)).toBeNull();
    expect(substituteHint("@ola@example.com", 1, users, absences)).toBeNull();
  });
});

describe("insertAfterMention", () => {
  it("wstawia zastępcę zaraz po wzmiance osoby", () => {
    expect(
      insertAfterMention("@kamil@example.com klient prosi", "Kamil@example.com", "ola@example.com"),
    ).toEqual({ text: "@kamil@example.com @ola@example.com klient prosi", caret: 35 });
  });

  it("na końcu tekstu dopisuje spację; bez wzmianki — dopisuje na końcu", () => {
    expect(insertAfterMention("cc @kamil@example.com", "kamil@example.com", "ola@example.com")).toEqual({
      text: "cc @kamil@example.com @ola@example.com ",
      caret: 39,
    });
    expect(insertAfterMention("tekst", "kamil@example.com", "ola@example.com")).toEqual({
      text: "tekst @ola@example.com ",
      caret: 23,
    });
  });
});
