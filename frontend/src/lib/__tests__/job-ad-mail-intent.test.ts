import { describe, expect, it } from "vitest";

import { pracujMailHref, readAdMailIntent, withoutAdMailParams } from "../job-ad-mail-intent";

const read = (search: string) => readAdMailIntent(new URLSearchParams(search));

describe("wejście z maila przypomnienia o ogłoszeniu", () => {
  it("kanał otwiera okno na kanale", () => {
    expect(read("?ogloszenie=jjit")).toEqual({
      focus: "jjit",
      skip: false,
      remind: false,
      send: false,
    });
    expect(read("?ogloszenie=kariera&przypomnij=rekruter")).toEqual({
      focus: "kariera",
      skip: false,
      remind: true,
      send: false,
    });
  });

  it("„pomin” otwiera „Nie publikujemy” bez kanału", () => {
    expect(read("?ogloszenie=pomin")).toEqual({
      focus: null,
      skip: true,
      remind: false,
      send: false,
    });
  });

  it("„wyslij=opiekun” przy Pracuj.pl otwiera mail do opiekuna, przy innym kanale nic", () => {
    expect(read("?ogloszenie=pracuj&wyslij=opiekun")).toEqual({
      focus: "pracuj",
      skip: false,
      remind: false,
      send: true,
    });
    expect(read("?ogloszenie=jjit&wyslij=opiekun")?.send).toBe(false);
    expect(read("?ogloszenie=pracuj&wyslij=wszystkim")?.send).toBe(false);
  });

  it("adres po utworzeniu rekrutacji czyta się jak przycisk z maila", () => {
    const href = pracujMailHref(789151);
    expect(href).toBe("/jobs/789151?ogloszenie=pracuj&wyslij=opiekun");
    expect(read(href.split("?")[1])?.send).toBe(true);
  });

  it("obce wartości nic nie otwierają", () => {
    expect(read("?ogloszenie=facebook")).toBeNull();
    expect(read("?przypomnij=wszystkich")).toBeNull();
    expect(read("?candidate=12")).toBeNull();
    expect(readAdMailIntent(null)).toBeNull();
  });

  it("po obsłużeniu parametry znikają, reszta adresu zostaje", () => {
    expect(withoutAdMailParams("?candidate=12&ogloszenie=jjit&przypomnij=rekruter")).toBe(
      "?candidate=12",
    );
    expect(withoutAdMailParams("?ogloszenie=pomin")).toBe("");
    expect(withoutAdMailParams("?ogloszenie=pracuj&wyslij=opiekun&tab=tablica")).toBe(
      "?tab=tablica",
    );
  });
});
