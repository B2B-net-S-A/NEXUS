import { describe, expect, it } from "vitest";

import { invalidAttendeeEmails, splitAttendeeEmails } from "@/components/calendar/attendee-emails";

describe("splitAttendeeEmails", () => {
  it("dzieli po przecinku, średniku, spacji i nowej linii, bez duplikatów", () => {
    expect(
      splitAttendeeEmails("a@x.pl, b@x.pl;c@x.pl\nd@x.pl  A@x.pl"),
    ).toEqual(["a@x.pl", "b@x.pl", "c@x.pl", "d@x.pl"]);
  });

  it("pusty wpis = brak uczestników", () => {
    expect(splitAttendeeEmails("  ,; ")).toEqual([]);
  });

  it("wskazuje adresy, które nie wyglądają na e-mail", () => {
    expect(invalidAttendeeEmails(["a@x.pl", "jan.kowalski@", "anna"])).toEqual([
      "jan.kowalski@",
      "anna",
    ]);
  });
});
