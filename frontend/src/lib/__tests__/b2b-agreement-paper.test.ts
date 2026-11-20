/**
 * „Kartka” Generatora — pierwszy akapit umowy B2B wypełniany na żywo.
 *
 * Kartka jest tylko podglądem, ale nie może mówić co innego niż umowa: każde
 * stałe zdanie (`PAPER_PHRASES`) musi stać dosłownie w szablonie HTML umowy
 * (`backend/app/templates/contract/umowa_b2b_{pl,en}.html`). Zmiana szablonu
 * bez zmiany kartki wywraca ten test.
 */
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  PAPER_PHRASES,
  agreementPaper,
  formatShareCapital,
  paperGapCount,
  representationEn,
  type PaperInput,
  type PaperParagraph,
} from "@/lib/b2b-agreement-paper";

const JDG: PaperInput = {
  language: "pl",
  variant: "jdg",
  gender: "m",
  contractNumber: "1500/2026",
  signingDate: "2026-11-20",
  partnerName: "Jan Testowy",
  partnerInstrumental: "Janem Testowym",
  partnerLegalName: "JT Software Jan Testowy",
  partnerBusinessAddress: "ul. Prosta 1, 00-001 Warszawa",
  addressForService: false,
  correspondenceAddress: "",
  partnerNip: "1234563218",
  partnerRegon: "123456785",
  phone: "+48 600 100 200",
  email: "jan@example.com",
  seat: "",
  seatLocative: "",
  registryCourt: "",
  krs: "",
  shareCapital: "",
  representation: "",
  representativeName: "",
  representativeFunction: "",
};

const COMPANY: PaperInput = {
  ...JDG,
  variant: "company",
  partnerLegalName: "Testowa Spółka z o.o.",
  seat: "Warszawa",
  seatLocative: "w Warszawie",
  registryCourt: "Sąd Rejonowy dla m.st. Warszawy w Warszawie, XII Wydział Gospodarczy KRS",
  krs: "0000123456",
  shareCapital: "5000",
  representation: "Pana Jana Testowego – Prezesa Zarządu",
  representativeName: "Jan Testowy",
  representativeFunction: "Prezes Zarządu",
};

/** Tekst akapitu tak, jak go widać (braki jako „[etykieta]”). */
function plain(paragraph: PaperParagraph): string {
  return paragraph.segments
    .map((s) => (s.kind === "gap" ? `[${s.label}]` : s.text))
    .join("");
}

const partyOf = (input: PaperInput) => plain(agreementPaper(input)[5]);

describe("agreementPaper — umowa PL", () => {
  it("JDG: komparycja jak w szablonie, z formami męskimi", () => {
    const paper = agreementPaper(JDG);
    expect(plain(paper[0])).toBe("Umowa o współpracę B2B");
    expect(plain(paper[1])).toBe("nr 1500/2026");
    expect(plain(paper[2])).toBe("zawarta w dniu 20.11.2026 roku w Warszawie pomiędzy:");
    expect(partyOf(JDG)).toBe(
      "Panem Janem Testowym prowadzącym działalność gospodarczą pod firmą: " +
        "JT Software Jan Testowy, zarejestrowaną w Centralnej Ewidencji " +
        "i Informacji o Działalności Gospodarczej pod adresem: " +
        "ul. Prosta 1, 00-001 Warszawa, NIP: 1234563218, REGON: 123456785,",
    );
    expect(plain(paper[7])).toBe("Tel. +48 600 100 200; Adres e-mail: jan@example.com");
    expect(plain(paper[8])).toBe("zwany w dalszej części umowy „Partnerem”");
    expect(paperGapCount(paper)).toBe(0);
  });

  it("kobieta, adres do doręczeń i adres do korespondencji", () => {
    const input: PaperInput = {
      ...JDG,
      gender: "k",
      partnerName: "Anna Testowa",
      partnerInstrumental: "Anną Testową",
      addressForService: true,
      correspondenceAddress: "ul. Krzywa 2, 00-002 Warszawa",
    };
    expect(partyOf(input)).toBe(
      "Panią Anną Testową prowadzącą działalność gospodarczą pod firmą: " +
        "JT Software Jan Testowy, zarejestrowaną w Centralnej Ewidencji " +
        "i Informacji o Działalności Gospodarczej pod adresem do doręczeń: " +
        "ul. Prosta 1, 00-001 Warszawa, NIP: 1234563218, REGON: 123456785, " +
        "adres do korespondencji: ul. Krzywa 2, 00-002 Warszawa,",
    );
    expect(plain(agreementPaper(input)[8])).toBe("zwana w dalszej części umowy „Partnerem”");
  });

  it("braki są w tekście jako „[…]” i prowadzą do pól", () => {
    const paper = agreementPaper({
      ...JDG,
      contractNumber: "",
      signingDate: "",
      partnerRegon: " ",
      partnerBusinessAddress: "",
      phone: "",
    });
    expect(plain(paper[1])).toBe("nr [numer]");
    expect(plain(paper[2])).toContain("w dniu [data podpisania] roku");
    expect(plain(paper[5])).toContain("pod adresem: [adres z CEIDG], NIP: 1234563218, REGON: [REGON],");
    expect(plain(paper[7])).toBe("Tel. [telefon]; Adres e-mail: jan@example.com");
    expect(paperGapCount(paper)).toBe(5);
    const gaps = paper.flatMap((p) => p.segments).filter((s) => s.kind === "gap");
    expect(gaps.map((g) => (g.kind === "gap" ? `${g.step}:${g.field}` : ""))).toEqual([
      "warunki:number",
      "warunki:signingDate",
      "partner:address",
      "partner:regon",
      "partner:phone",
    ]);
  });

  it("bez narzędnika bierze imię i nazwisko jak szablon, bez obu — brak", () => {
    expect(partyOf({ ...JDG, partnerInstrumental: "" })).toMatch(/^Panem Jan Testowy prowadzącym/);
    const party = agreementPaper({ ...JDG, partnerInstrumental: "", partnerName: "" })[5];
    expect(plain(party)).toMatch(/^Panem \[imię i nazwisko\] prowadzącym/);
    const gap = party.segments.find((s) => s.kind === "gap");
    expect(gap && gap.kind === "gap" ? gap.field : null).toBe("partnerName");
  });

  it("spółka: dane z KRS, kapitał po polsku i „zwaną”", () => {
    expect(partyOf(COMPANY)).toBe(
      "Testowa Spółka z o.o. z siedzibą w Warszawie, pod adresem ul. Prosta 1, " +
        "00-001 Warszawa, wpisaną do Rejestru Przedsiębiorców Krajowego Rejestru " +
        "Sądowego, prowadzonego przez Sąd Rejonowy dla m.st. Warszawy " +
        "w Warszawie, XII Wydział Gospodarczy KRS, pod numerem KRS: 0000123456, " +
        "NIP: 1234563218, REGON: 123456785, o kapitale zakładowym 5.000,00 zł, " +
        "reprezentowaną przez Pana Jana Testowego – Prezesa Zarządu,",
    );
    expect(plain(agreementPaper({ ...COMPANY, gender: "k" })[8])).toBe(
      "zwaną w dalszej części umowy „Partnerem”",
    );
  });
});

describe("agreementPaper — umowa EN", () => {
  it("JDG: Mr i imię w mianowniku, adres „for service”", () => {
    const input: PaperInput = { ...JDG, language: "en", addressForService: true };
    const paper = agreementPaper(input);
    expect(plain(paper[0])).toBe("B2B cooperation agreement");
    expect(plain(paper[1])).toBe("No. 1500/2026");
    expect(plain(paper[2])).toBe("concluded on 20.11.2026 in Warsaw between:");
    expect(partyOf(input)).toBe(
      "Mr Jan Testowy conducting business activity under the name: " +
        "JT Software Jan Testowy, registered in the Central Register and " +
        "Information on Economic Activity at the address for service: " +
        "ul. Prosta 1, 00-001 Warszawa, NIP: 1234563218, REGON: 123456785,",
    );
    expect(plain(paper[8])).toBe('hereinafter referred to as the "Partner"');
  });

  it("spółka: siedziba w mianowniku, kapitał i reprezentacja po angielsku", () => {
    expect(partyOf({ ...COMPANY, language: "en", gender: "k" })).toBe(
      "Testowa Spółka z o.o. with its registered office in Warszawa, at the " +
        "address: ul. Prosta 1, 00-001 Warszawa, entered in the Register of " +
        "Entrepreneurs of the National Court Register kept by Sąd Rejonowy dla " +
        "m.st. Warszawy w Warszawie, XII Wydział Gospodarczy KRS, under KRS " +
        "number: 0000123456, NIP: 1234563218, REGON: 123456785, with share " +
        "capital of PLN 5,000.00, represented by Ms Jan Testowy – President of " +
        "the Management Board,",
    );
  });
});

describe("pomocnicze lustra backendu", () => {
  it("formatShareCapital jak `format_share_capital`", () => {
    expect(formatShareCapital("5000", "pl")).toBe("5.000,00 zł");
    expect(formatShareCapital("1 360 000,5", "pl")).toBe("1.360.000,50 zł");
    expect(formatShareCapital("5.000,00 zł", "en")).toBe("PLN 5,000.00");
    expect(formatShareCapital("10 000 EUR", "pl")).toBe("10 000 EUR");
    expect(formatShareCapital("  ", "pl")).toBe("");
  });

  it("representationEn jak `representation_en`", () => {
    expect(representationEn("Jan Testowy", "Prezes Zarządu", "m")).toBe(
      "Mr Jan Testowy – President of the Management Board",
    );
    expect(representationEn("Anna Testowa", "Pełnomocnik", "k")).toBe(
      "Ms Anna Testowa – Pełnomocnik",
    );
    expect(representationEn("Jan Testowy", "", "m")).toBe("Mr Jan Testowy");
    expect(representationEn("", "Prezes Zarządu", "m")).toBe("");
  });
});

describe("lustro szablonu umowy (backend/app/templates/contract)", () => {
  const root = resolve(process.cwd(), "..");
  const template = (lang: "pl" | "en") =>
    readFileSync(join(root, `backend/app/templates/contract/umowa_b2b_${lang}.html`), "utf8")
      .replace(/<[^>]+>/g, "")
      .replace(/ /g, " ");

  for (const lang of ["pl", "en"] as const) {
    it(`każde stałe zdanie kartki (${lang}) stoi w szablonie`, () => {
      const text = template(lang);
      const missing = Object.entries(PAPER_PHRASES[lang]).filter(
        ([, phrase]) => !text.includes(phrase),
      );
      expect(missing).toEqual([]);
    });
  }
});
