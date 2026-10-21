import { describe, expect, it } from "vitest";

import { notifyOnEditRecipients, recipientsLabel } from "@/lib/note-edit-notify";
import { buildUsersByEmail, mentionedEmails } from "@/lib/renderMentions";

const ANNA = { id: 7, name: "Anna Nowak", email: "anna@b2b.test", role: "delivery_lead" };
const PIOTR = { id: 8, name: "Piotr Lis", email: "piotr@b2b.test", role: "recruiter" };
const EWA = { id: 5, name: "Ewa Wiśniewska", email: "ewa@b2b.test", role: "recruiter" };
const users = buildUsersByEmail([ANNA, PIOTR, EWA]);

describe("mentionedEmails", () => {
  it("returns lower-cased unique addresses and skips plain e-mails", () => {
    expect(
      mentionedEmails("@Anna@b2b.test i @anna@b2b.test, kontakt: jan@x.pl @piotr@b2b.test"),
    ).toEqual(["anna@b2b.test", "piotr@b2b.test"]);
  });
});

describe("notifyOnEditRecipients", () => {
  it("lists people mentioned before and after the edit", () => {
    expect(
      notifyOnEditRecipients(
        "Prep 2 śr 10:00 @anna@b2b.test",
        "Prep 2 czw 14:00 @anna@b2b.test @piotr@b2b.test",
        users,
        5,
      ),
    ).toEqual([ANNA]);
  });

  it("is empty when the text did not change, the person was removed or it is the author", () => {
    expect(notifyOnEditRecipients("x @anna@b2b.test", " x @anna@b2b.test ", users, 5)).toEqual([]);
    expect(notifyOnEditRecipients("x @anna@b2b.test", "y bez oznaczenia", users, 5)).toEqual([]);
    expect(notifyOnEditRecipients("x @ewa@b2b.test", "y @ewa@b2b.test", users, 5)).toEqual([]);
    expect(notifyOnEditRecipients("x @obcy@b2b.test", "y @obcy@b2b.test", users, 5)).toEqual([]);
  });
});

describe("recipientsLabel", () => {
  it("names one or two people and counts the rest in Polish", () => {
    expect(recipientsLabel([ANNA])).toBe("Anna Nowak");
    expect(recipientsLabel([ANNA, PIOTR])).toBe("Anna Nowak i Piotr Lis");
    expect(recipientsLabel([ANNA, PIOTR, EWA])).toBe("Anna Nowak i 2 inne osoby");
    const many = Array.from({ length: 6 }, (_, i) => ({ ...ANNA, id: 100 + i }));
    expect(recipientsLabel(many)).toBe("Anna Nowak i 5 innych osób");
  });
});
