import { describe, expect, it } from "vitest";

import { readAdMailIntent, withoutAdMailParams } from "../job-ad-mail-intent";

const read = (search: string) => readAdMailIntent(new URLSearchParams(search));

describe("wejście z maila przypomnienia o ogłoszeniu", () => {
  it("kanał otwiera okno na kanale", () => {
    expect(read("?ogloszenie=jjit")).toEqual({ focus: "jjit", skip: false, remind: false });
    expect(read("?ogloszenie=kariera&przypomnij=rekruter")).toEqual({
      focus: "kariera",
      skip: false,
      remind: true,
    });
  });

  it("„pomin” otwiera „Nie publikujemy” bez kanału", () => {
    expect(read("?ogloszenie=pomin")).toEqual({ focus: null, skip: true, remind: false });
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
  });
});
