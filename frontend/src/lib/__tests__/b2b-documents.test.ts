import { describe, expect, it } from "vitest";

import type {
  DocumentFieldDef,
  DocumentTypeDef,
} from "@/lib/api/b2bDocuments";
import {
  annexesHref,
  buildDocumentRequest,
  cleanRateItems,
  cleanValues,
  documentStatusLabel,
  documentsHref,
  fieldKeysForLabels,
  findRegisterRowForContract,
  groupedFields,
  intentOpensWizard,
  invalidListFields,
  invalidMoneyFields,
  isFieldVisible,
  missingRequired,
  paragraphAfterVariantChange,
  parseDocumentsIntent,
  parseMoney,
  rateItemsProblems,
  readDocumentError,
  redownloadNeedsInput,
  registryLookupValues,
  typesByFamily,
} from "@/lib/b2b-documents";

function field(key: string, label: string, extra: Partial<DocumentFieldDef> = {}): DocumentFieldDef {
  return {
    key,
    label,
    kind: "text",
    required: false,
    sensitive: false,
    help: null,
    options: [],
    show_if: null,
    group: "document",
    lookup: null,
    lookup_fills: [],
    ...extra,
  };
}

const TERMINATION: DocumentTypeDef = {
  key: "termination_agreement",
  label: "Porozumienie o rozwiązaniu umowy",
  family: "termination",
  languages: ["pl", "en"],
  parent: "b2b",
  description: "",
  effect_label: "",
  signatories: "both",
  uses_refs: true,
  allows_external: false,
  legacy_languages: [],
  fields: [
    field("document_date", "Data dokumentu", { kind: "date", required: true }),
    field("gender", "Płeć Partnera", { kind: "gender", required: true, group: "partner" }),
    field("partner_name", "Imię i nazwisko", { required: true, group: "partner" }),
    field("release_non_compete", "Zwolnienie z zakazu konkurencji", { kind: "bool" }),
    field("non_compete_client_name", "Klient, którego dotyczy zwolnienie", {
      required: true,
      show_if: ["release_non_compete", true],
    }),
  ],
};

const RATE: DocumentTypeDef = {
  ...TERMINATION,
  key: "annex_rate_change",
  family: "annex",
  fields: [
    field("new_rate", "Nowa stawka godzinowa netto", { kind: "money", required: true }),
    field("pesel", "PESEL", { required: true, sensitive: true, group: "partner" }),
  ],
};

describe("widoczność pól (show_if)", () => {
  it("pole z show_if widać dopiero przy dokładnie tej wartości — jak serwer", () => {
    const client = TERMINATION.fields[4];
    expect(isFieldVisible(client, {})).toBe(false);
    expect(isFieldVisible(client, { release_non_compete: false })).toBe(false);
    expect(isFieldVisible(client, { release_non_compete: true })).toBe(true);
  });

  it("grupuje widoczne pola: Dokument → Partner, bez pustych grup", () => {
    const groups = groupedFields(TERMINATION, {});
    expect(groups.map((g) => g.label)).toEqual(["Dokument", "Partner"]);
    expect(groups[0].fields.map((f) => f.key)).not.toContain("non_compete_client_name");
  });
});

describe("wymagane pola", () => {
  it("ukryte pole wymagane nie jest brakiem, widoczne — jest", () => {
    const base = { document_date: "2026-09-23", gender: "m", partner_name: "Jan" };
    expect(missingRequired(TERMINATION, base)).toEqual([]);
    expect(missingRequired(TERMINATION, { ...base, release_non_compete: true })).toEqual([
      "Klient, którego dotyczy zwolnienie",
    ]);
  });

  it("sama spacja to brak", () => {
    expect(missingRequired(TERMINATION, { document_date: "2026-09-23", gender: "m", partner_name: "  " })).toEqual([
      "Imię i nazwisko",
    ]);
  });

  it("etykiety z 422 zamienia na klucze pól", () => {
    expect(fieldKeysForLabels(TERMINATION, ["Imię i nazwisko", "Numery paragrafów umowy bazowej"])).toEqual([
      "partner_name",
    ]);
  });
});

describe("kwoty", () => {
  it("przecinek dziesiętny i spacja tysięcy dają liczbę", () => {
    expect(parseMoney("135,50")).toBe(135.5);
    expect(parseMoney("1 234,5")).toBe(1234.5);
    expect(parseMoney(150)).toBe(150);
  });

  it("tekst nie jest kwotą — i jest zgłaszany", () => {
    expect(parseMoney("sto")).toBeNull();
    expect(parseMoney("12,345")).toBeNull();
    expect(invalidMoneyFields(RATE, { new_rate: "sto" })).toEqual(["Nowa stawka godzinowa netto"]);
    expect(invalidMoneyFields(RATE, { new_rate: "" })).toEqual([]);
  });
});

describe("ciało żądania", () => {
  it("zdejmuje puste, ukryte i nieznane pola; kwoty jako liczby; tekst przycięty", () => {
    const values = cleanValues(
      { ...TERMINATION, fields: [...TERMINATION.fields, field("new_rate", "Stawka", { kind: "money" })] },
      {
        document_date: "2026-09-23",
        partner_name: "  Anna  ",
        gender: "",
        release_non_compete: false,
        non_compete_client_name: "Stara wartość",
        new_rate: "150,5",
        unknown_key: "x",
      },
    );
    expect(values).toEqual({
      document_date: "2026-09-23",
      partner_name: "Anna",
      new_rate: 150.5,
    });
  });

  it("pole ze zwolnieniem idzie, gdy zwolnienie zaznaczone", () => {
    expect(
      cleanValues(TERMINATION, { release_non_compete: true, non_compete_client_name: "Bank S.A." }),
    ).toEqual({ release_non_compete: true, non_compete_client_name: "Bank S.A." });
  });

  it("paragrafy tylko, gdy serwer o nie prosi; puste numery odpadają", () => {
    const common = {
      type: TERMINATION,
      language: "en",
      subject: { parentGeneratedContractId: 12 },
      values: { partner_name: "Anna" },
      refs: { rate_paragraph: "§ 5", notice_paragraph: " " },
    };
    expect(buildDocumentRequest({ ...common, needsRefs: false })).toEqual({
      document_type: "termination_agreement",
      language: "en",
      parent_generated_contract_id: 12,
      values: { partner_name: "Anna" },
    });
    expect(buildDocumentRequest({ ...common, needsRefs: true }).refs).toEqual({
      rate_paragraph: "§ 5",
    });
  });

  it("język spoza typu spada na pierwszy; kandydat i rekrutacja przechodzą", () => {
    const body = buildDocumentRequest({
      type: { ...TERMINATION, languages: ["pl"], parent: "none" },
      language: "en",
      subject: { candidateId: 5, jobId: 9 },
      values: {},
      needsRefs: false,
    });
    expect(body).toMatchObject({ language: "pl", candidate_id: 5, job_id: 9 });
    expect(body).not.toHaveProperty("parent_generated_contract_id");
  });
});

describe("błędy API", () => {
  it("czyta 422 z ciała Bloba (odpowiedź DOCX)", async () => {
    const blob = new Blob(
      [
        JSON.stringify({
          detail: {
            code: "document_fields_missing",
            message: "Uzupełnij: Imię i nazwisko.",
            missing: ["Imię i nazwisko"],
          },
        }),
      ],
      { type: "application/json" },
    );
    const parsed = await readDocumentError({ response: { status: 422, data: blob } }, "fallback");
    expect(parsed).toEqual({
      code: "document_fields_missing",
      message: "Uzupełnij: Imię i nazwisko.",
      missing: ["Imię i nazwisko"],
      status: 422,
    });
  });

  it("zwykły detail tekstowy i brak ciała", async () => {
    expect(
      (await readDocumentError({ response: { status: 409, data: { detail: "Już podpisany." } } }, "x")).message,
    ).toBe("Już podpisany.");
    expect((await readDocumentError(new Error("net"), "Nie udało się.")).message).toBe("Nie udało się.");
  });
});

describe("adres kreatora", () => {
  const params = (qs: string) => new URLSearchParams(qs);

  it("?new=<typ>&parent=<id>", () => {
    const intent = parseDocumentsIntent(params("tab=documents&new=annex_rate_change&parent=42"));
    expect(intent).toEqual({ newType: "annex_rate_change", parentId: 42, contractId: null });
    expect(intentOpensWizard(intent)).toBe(true);
  });

  it("śmieci w adresie nie otwierają kreatora z dziwnym typem", () => {
    const intent = parseDocumentsIntent(params("new=<script>&parent=-3&contract=abc"));
    expect(intent).toEqual({ newType: null, parentId: null, contractId: null });
    expect(intentOpensWizard(intent)).toBe(false);
  });

  it("?new=1 otwiera kreator bez typu; sam kontrakt też", () => {
    expect(parseDocumentsIntent(params("new=1")).newType).toBe("");
    expect(intentOpensWizard(parseDocumentsIntent(params("new=1")))).toBe(true);
    expect(intentOpensWizard(parseDocumentsIntent(params("contract=7")))).toBe(true);
  });

  it("link z modułu Kontrakty", () => {
    expect(documentsHref({ newType: "termination_agreement", contractId: 7 })).toBe(
      "/contracts/b2b-generator?tab=documents&new=termination_agreement&contract=7",
    );
  });
});

describe("wiersze", () => {
  it("umowa bazowa kontraktu — obowiązująca wygrywa z anulowaną", () => {
    const rows = [
      { id: 1, contract_id: 7, contract_status: "cancelled" },
      { id: 2, contract_id: 7, contract_status: "active" },
      { id: 3, contract_id: 8, contract_status: "active" },
    ];
    expect(findRegisterRowForContract(rows, 7)?.id).toBe(2);
    expect(findRegisterRowForContract(rows, 99)).toBeNull();
  });

  it("status podpisu i ponowne pobranie z danymi wrażliwymi", () => {
    expect(documentStatusLabel({ status: "issued", signature_status: "unsigned" }).label).toBe("Niepodpisany");
    expect(documentStatusLabel({ status: "signed", signature_status: "signed_both" }).label).toBe("Podpisany");
    expect(documentStatusLabel({ status: "cancelled", signature_status: "unsigned" }).label).toBe("Anulowany");
    expect(redownloadNeedsInput({ requires_sensitive_input: true, sensitive_fields: ["pesel"] })).toBe(true);
    expect(redownloadNeedsInput({ requires_sensitive_input: false, sensitive_fields: [] })).toBe(false);
  });

  it("rodziny w stałej kolejności, puste odpadają", () => {
    expect(typesByFamily([RATE, TERMINATION]).map((g) => g.label)).toEqual([
      "Aneksy",
      "Rozwiązanie umowy",
    ]);
  });
});

// ── Generator aneksów (ticket 29.09.2026) ───────────────────────────────────

const RATE_ANNEX: DocumentTypeDef = {
  ...TERMINATION,
  key: "annex_rate_change",
  family: "annex",
  allows_external: true,
  fields: [
    field("contract_number", "Numer umowy", { required: true, group: "base" }),
    field("rate_items", "Stawki", { kind: "rate_items", required: true, group: "change" }),
  ],
};

describe("generator aneksów — pozycje stawki", () => {
  it("drops blank rows and parses Polish amounts", () => {
    expect(
      cleanRateItems([
        { rate: "135,50", client_id: null, from: "", to: null },
        { rate: "", client_id: null, from: null, to: null },
      ]),
    ).toEqual([{ rate: 135.5, client_id: null, from: null, to: null }]);
  });

  it("mirrors the server rule: several rates need a date or a client", () => {
    expect(rateItemsProblems([{ rate: "135" }])).toEqual([]);
    expect(
      rateItemsProblems([{ rate: "135" }, { rate: "140", from: "2027-01-01" }]),
    ).toEqual([]);
    expect(rateItemsProblems([{ rate: "135" }, { rate: "140" }])[0]).toMatch(
      /daty „od” albo klienta/,
    );
    expect(
      rateItemsProblems([{ rate: "135", from: "2026-12-01", to: "2026-11-01" }])[0],
    ).toMatch(/wcześniejsza niż „od”/);
    expect(rateItemsProblems([{ rate: "abc", client_id: 1 }])[0]).toMatch(/podaj stawkę/);
  });

  it("treats a list with only blank rows as missing and sends clean items", () => {
    const values = { contract_number: "1/2026", rate_items: [{ rate: "" }] };
    expect(missingRequired(RATE_ANNEX, values)).toEqual(["Stawki"]);
    const body = buildDocumentRequest({
      type: RATE_ANNEX,
      language: "pl",
      subject: {},
      values: { contract_number: "1/2026", rate_items: [{ rate: "150", from: "2026-11-01" }] },
      needsRefs: false,
    });
    expect(body.values.rate_items).toEqual([
      { rate: 150, client_id: null, from: "2026-11-01", to: null },
    ]);
    expect(body.parent_generated_contract_id).toBeUndefined();
    expect(invalidListFields(RATE_ANNEX, { rate_items: [{ rate: "0" }] })).toHaveLength(1);
  });
});

describe("generator aneksów — wariant Partnera i rejestr", () => {
  const defaults = { sole_trader: ["12", "2"], company: ["13", "2"] } as const;

  it("switches the default paragraph with the variant", () => {
    expect(
      paragraphAfterVariantChange(
        { paragraph: "12", paragraph_section: "2" },
        "sole_trader",
        "company",
        { ...defaults },
      ),
    ).toEqual({ paragraph: "13", paragraph_section: "2" });
  });

  it("keeps a paragraph the user typed", () => {
    expect(
      paragraphAfterVariantChange(
        { paragraph: "15", paragraph_section: "3" },
        "sole_trader",
        "company",
        { ...defaults },
      ),
    ).toBeNull();
  });

  it("maps registry fields and builds the locative seat", () => {
    expect(
      registryLookupValues(
        [
          ["name", "partner_legal_name"],
          ["seat_locative", "partner_seat_locative"],
          ["regon", "partner_regon"],
        ],
        { name: "Softex Sp. z o.o.", seat: "Warszawa", regon: null },
        (city) => `w ${city}`,
      ),
    ).toEqual({
      partner_legal_name: "Softex Sp. z o.o.",
      partner_seat_locative: "w Warszawa",
    });
  });

  it("sends every annex link to the annex generator tab", () => {
    expect(documentsHref({ newType: "annex_rate_change", contractId: 7 })).toBe(
      "/contracts/b2b-generator?tab=annexes&new=annex_rate_change&contract=7",
    );
    expect(annexesHref({ newType: "annex_party_data", parentId: 3 })).toBe(
      "/contracts/b2b-generator?tab=annexes&new=annex_party_data&parent=3",
    );
    expect(documentsHref({ newType: "termination_agreement", parentId: 3 })).toBe(
      "/contracts/b2b-generator?tab=documents&new=termination_agreement&parent=3",
    );
  });
});
