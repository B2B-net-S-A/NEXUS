import { describe, expect, it } from "vitest";

import { detectNotePersonMismatch } from "../note-person-mismatch";

const JARZAB_PASTE =
  "Imię i nazwisko: Marek Szczegodziński\n\nStawka: 107 PLN/h Netto\n\nDostępność: ASAP";

describe("detectNotePersonMismatch", () => {
  it("ostrzega przy pełnym mismatchu (sprawa Jarząb/Szczegodziński)", () => {
    expect(detectNotePersonMismatch(JARZAB_PASTE, "Tomasz", "Jarząb")).toBe(
      "Marek Szczegodziński",
    );
  });

  it("nie ostrzega, gdy osoba z pola pasuje do kandydata", () => {
    expect(
      detectNotePersonMismatch(
        "Imię i nazwisko: Jan Kowalski\nStawka: 100",
        "Jan",
        "Kowalski",
      ),
    ).toBeNull();
  });

  it("porównuje bez diakrytyków i wielkości liter", () => {
    expect(
      detectNotePersonMismatch(
        "imię i nazwisko: LUKASZ WDOWKA",
        "Łukasz",
        "Wdówka",
      ),
    ).toBeNull();
  });

  it("nie ostrzega przy literówce nazwiska, gdy imię pasuje (Treper vs Teper)", () => {
    expect(
      detectNotePersonMismatch(
        "Imię i nazwisko: Konrad Treper",
        "Konrad",
        "Teper",
      ),
    ).toBeNull();
  });

  it("ignoruje tagi i encje HTML wokół pola", () => {
    expect(
      detectNotePersonMismatch(
        '<p>&nbsp;</strong>Imię i nazwisko: <strong>Anna&nbsp;Nowak</strong></p>',
        "Anna",
        "Nowak",
      ),
    ).toBeNull();
  });

  it("nie ostrzega przy samym imieniu w polu (za mało, by wskazać inną osobę)", () => {
    expect(
      detectNotePersonMismatch(
        "<li>Imię i nazwisko: Kateryna</li><li>Stawka: 60 zł/h</li>",
        "Kateryna",
        "Vynova",
      ),
    ).toBeNull();
    expect(
      detectNotePersonMismatch("Imię i nazwisko: Marek", "Tomasz", "Jarząb"),
    ).toBeNull();
  });

  it("nie ostrzega bez pola 'Imię i nazwisko:'", () => {
    expect(
      detectNotePersonMismatch("Zwykła notatka o kandydacie", "Jan", "Kowalski"),
    ).toBeNull();
  });

  it("nie ostrzega, gdy dane kandydata to placeholdery importu", () => {
    expect(detectNotePersonMismatch(JARZAB_PASTE, "?", "?")).toBeNull();
    expect(detectNotePersonMismatch(JARZAB_PASTE, null, undefined)).toBeNull();
    expect(detectNotePersonMismatch(JARZAB_PASTE, "Nieznane", "")).toBeNull();
  });

  it("wystarczy zgodność samego nazwiska (imię zdrobniałe/inne)", () => {
    expect(
      detectNotePersonMismatch(
        "Imię i nazwisko: Tomek Jarząb",
        "Tomasz",
        "Jarząb",
      ),
    ).toBeNull();
  });

  it("przycina zwracaną osobę do 80 znaków", () => {
    const long = `Imię i nazwisko: ${"X".repeat(200)} Ygrek`;
    const result = detectNotePersonMismatch(long, "Jan", "Kowalski");
    expect(result).not.toBeNull();
    expect(result!.length).toBeLessThanOrEqual(80);
  });
});
