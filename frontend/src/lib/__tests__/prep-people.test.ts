import { describe, expect, it } from "vitest";

import type { PrepPersonOption } from "@/lib/api/prepMeetings";
import {
  MAX_INVITEES,
  NO_INVITEES,
  addEmail,
  addUser,
  foldText,
  inviteesFromAttendees,
  invitablePeople,
  isEmailAddress,
  recommendedPeople,
  removeEmail,
  removeUser,
  sameInvitees,
  searchPeople,
} from "@/lib/prep-people";

const PEOPLE: PrepPersonOption[] = [
  { id: 1, name: "Ewa Nowicka", role: "delivery_lead", in_team: true },
  { id: 2, name: "Kasia Wrona", role: "recruiter", in_team: true },
  { id: 3, name: "Łukasz Zając", role: "recruiter", in_team: false },
  { id: 4, name: "Marcin Pająk", role: "delivery_lead", in_team: false },
];

describe("prep-people", () => {
  it("szuka po początku każdego słowa, bez polskich znaków", () => {
    expect(searchPeople(PEOPLE, "luk", new Set()).map((p) => p.id)).toEqual([3]);
    expect(searchPeople(PEOPLE, "ewa no", new Set()).map((p) => p.id)).toEqual([1]);
    expect(searchPeople(PEOPLE, "paja", new Set()).map((p) => p.id)).toEqual([4]);
    expect(searchPeople(PEOPLE, "wa", new Set())).toEqual([]);
    expect(searchPeople(PEOPLE, "   ", new Set())).toEqual([]);
  });

  it("pomija osoby już zaproszone i prowadzącego", () => {
    expect(searchPeople(PEOPLE, "ma", new Set([4]))).toEqual([]);
  });

  it("starszy serwer bez `people` — zostaje zespół", () => {
    expect(invitablePeople({ team: [{ id: 9, name: "Ola" }] })).toEqual([
      { id: 9, name: "Ola", role: null, in_team: true },
    ]);
    expect(invitablePeople({ team: [], people: PEOPLE })).toBe(PEOPLE);
  });

  it("adres e-mail: tylko poprawny, bez powtórzeń, z limitem", () => {
    expect(isEmailAddress("ola.wit@partner.pl")).toBe(true);
    expect(isEmailAddress("ola.wit@partner")).toBe(false);
    expect(isEmailAddress("ola wit@partner.pl")).toBe(false);
    let v = addEmail(NO_INVITEES, " Ola@Partner.pl ");
    expect(v.emails).toEqual(["Ola@Partner.pl"]);
    expect(addEmail(v, "ola@partner.pl")).toBe(v);
    expect(addEmail(v, "nie-adres")).toBe(v);
    for (let i = 0; i < MAX_INVITEES; i += 1) v = addEmail(v, `osoba${i}@example.com`);
    expect(v.emails).toHaveLength(MAX_INVITEES);
    expect(removeEmail(v, "Ola@Partner.pl").emails).not.toContain("Ola@Partner.pl");
  });

  it("osoby: bez powtórzeń, usuwanie", () => {
    const v = addUser(addUser(NO_INVITEES, 2), 2);
    expect(v.userIds).toEqual([2]);
    expect(removeUser(v, 2).userIds).toEqual([]);
  });

  it("podpowiedzi to DL i rekruter z serwera, bez już dodanych", () => {
    const suggested = { "1": { id: 1, name: "Ewa Nowicka" }, "2": { id: 2, name: "Kasia Wrona" } };
    expect(recommendedPeople(suggested, PEOPLE, new Set([2])).map((p) => p.id)).toEqual([1]);
    expect(recommendedPeople({ "1": suggested["1"], "2": suggested["1"] }, PEOPLE, new Set()).map((p) => p.id)).toEqual([1]);
  });

  it("porównanie list nie zależy od kolejności ani wielkości liter", () => {
    expect(
      sameInvitees({ userIds: [2, 1], emails: ["A@x.pl"] }, { userIds: [1, 2], emails: ["a@x.pl"] }),
    ).toBe(true);
    expect(sameInvitees({ userIds: [1], emails: [] }, { userIds: [1, 2], emails: [] })).toBe(false);
  });

  it("zaproszeni prepu → osoby po id, reszta po adresie", () => {
    expect(
      inviteesFromAttendees([
        { email: "ewa@firma.pl", user_id: 1 },
        { email: "gosc@partner.pl", user_id: null },
        { email: "GOSC@partner.pl", user_id: null },
      ]),
    ).toEqual({ userIds: [1], emails: ["gosc@partner.pl"] });
  });

  it("foldText", () => {
    expect(foldText("Łódź Żółć")).toBe("lodz zolc");
  });
});
