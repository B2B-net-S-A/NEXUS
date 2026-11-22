// „Kartka” w Generatorze umów — pierwszy akapit umowy B2B (komparycja)
// wypełniany na żywo tym, co się wpisuje, z brakami w tekście jako „[REGON]”
// (makieta A, decyzja Artura 19.11.2026).
//
// To TYLKO podgląd. Treść umowy tworzy na serwerze szablon
// `backend/app/templates/contract/umowa_b2b_{pl,en}.{html,docx}`
// (`render_context.build_render_context`). Stałe zdania kartki stoją w
// `PAPER_PHRASES` i test lustra (`__tests__/b2b-agreement-paper.test.ts`)
// sprawdza, że każde z nich stoi dosłownie w szablonie HTML — zmiana szablonu
// bez zmiany kartki kończy się czerwonym testem, a nie kartką, która mówi co
// innego niż umowa. Formy „Panem/Panią”, „Mr/Ms” — lustro `gender.py`.
import type { GeneratorFormStep } from "@/lib/b2b-generator-wizard";
import { formatIsoDatePl } from "@/lib/date-pl";

export type PaperSegment =
  | { kind: "text"; text: string; strong?: boolean }
  | { kind: "value"; text: string; strong?: boolean }
  | {
      kind: "gap";
      /** Co wpisać — w tekście jako „[REGON]”. */
      label: string;
      /** `data-gen-field` pola formularza. */
      field: string;
      step: GeneratorFormStep;
      strong?: boolean;
    };

export interface PaperParagraph {
  tone: "title" | "subtitle" | "body" | "muted";
  segments: PaperSegment[];
}

export interface PaperInput {
  language: "pl" | "en";
  variant: "jdg" | "company";
  gender: "m" | "k";
  contractNumber: string;
  /** ISO `RRRR-MM-DD`. */
  signingDate: string;
  partnerName: string;
  partnerInstrumental: string;
  partnerLegalName: string;
  partnerBusinessAddress: string;
  addressForService: boolean;
  correspondenceAddress: string;
  partnerNip: string;
  partnerRegon: string;
  /** Telefon tak, jak trafi do umowy (z prefiksem kraju). */
  phone: string;
  email: string;
  /** Spółka: miejscowość siedziby (EN „registered office in Warszawa”). */
  seat: string;
  /** Spółka: „w Warszawie” (PL „z siedzibą w Warszawie”). */
  seatLocative: string;
  registryCourt: string;
  krs: string;
  shareCapital: string;
  /** Spółka PL: gotowa fraza w bierniku z formularza. */
  representation: string;
  representativeName: string;
  representativeFunction: string;
}

/** Stałe zdania kartki — każde stoi dosłownie w szablonie HTML umowy. */
export const PAPER_PHRASES = {
  pl: {
    title: "Umowa o współpracę B2B",
    number: "nr ",
    concludedOn: "zawarta w dniu ",
    concludedIn: " roku w Warszawie pomiędzy:",
    company: "B2B.net S.A.",
    companySeat: " z siedzibą w Warszawie",
    companyAs: "dalej jako „Spółka” lub „B2BNET”",
    and: "a",
    jdgBusiness: " działalność gospodarczą pod firmą: ",
    jdgRegistered:
      ", zarejestrowaną w Centralnej Ewidencji i Informacji o Działalności Gospodarczej pod adresem",
    forService: " do doręczeń",
    nip: ", NIP: ",
    regon: ", REGON: ",
    correspondence: " adres do korespondencji: ",
    coSeat: "z siedzibą ",
    coAddress: ", pod adresem ",
    coRegister:
      ", wpisaną do Rejestru Przedsiębiorców Krajowego Rejestru Sądowego, prowadzonego przez ",
    coKrs: ", pod numerem KRS: ",
    coCapital: ", o kapitale zakładowym ",
    coRepresented: ", reprezentowaną przez ",
    contact: "Dane kontaktowe:",
    phone: "Tel. ",
    email: "; Adres e-mail: ",
    partnerAs: " w dalszej części umowy „Partnerem”",
    preamble: "Zważywszy, że:",
  },
  en: {
    title: "B2B cooperation agreement",
    number: "No. ",
    concludedOn: "concluded on ",
    concludedIn: " in Warsaw between:",
    company: "B2B.net S.A.",
    companySeat: " with its registered office in Warsaw",
    companyAs: 'hereinafter referred to as the "Company" or "B2BNET"',
    and: "and",
    jdgBusiness: "conducting business activity under the name: ",
    jdgRegistered:
      ", registered in the Central Register and Information on Economic Activity at the address",
    forService: " for service",
    nip: ", NIP: ",
    regon: ", REGON: ",
    correspondence: " correspondence address: ",
    coSeat: "with its registered office in ",
    coAddress: ", at the address: ",
    coRegister:
      ", entered in the Register of Entrepreneurs of the National Court Register kept by ",
    coKrs: ", under KRS number: ",
    coCapital: ", with share capital of ",
    coRepresented: ", represented by ",
    contact: "Contact details:",
    phone: "Tel. ",
    email: "; E-mail address: ",
    partnerAs: 'hereinafter referred to as the "Partner"',
    preamble: "Whereas:",
  },
} as const;

// Lustro `_FUNCTION_EN` w `company_variant.py` (umowa EN tłumaczy funkcję).
const FUNCTION_EN: Record<string, string> = {
  "prezes zarządu": "President of the Management Board",
  "wiceprezes zarządu": "Vice-President of the Management Board",
  "członek zarządu": "Member of the Management Board",
  prokurent: "Commercial Proxy (Prokurent)",
  komplementariusz: "General Partner",
  wspólnik: "Partner",
};

// Lustro `_AMOUNT` w `company_variant.py` (spacja, kropka albo twarda spacja).
const AMOUNT = /^\s*\d{1,3}(?:[ . ]?\d{3})*(?:,\d{1,2})?\s*(?:zł|pln)?\s*$/i;

/** „5000” → „5.000,00 zł” (EN „PLN 5,000.00”); nieczytelna kwota bez zmian. */
export function formatShareCapital(raw: string, language: "pl" | "en"): string {
  const text = raw.trim();
  if (!text) return "";
  if (!AMOUNT.test(text)) return text;
  const digits = text.replace(/zł|pln/gi, "").trim();
  const [wholeRaw, fracRaw = ""] = digits.split(",", 2);
  const whole = wholeRaw.replace(/[ . ]/g, "");
  const frac = `${fracRaw}00`.slice(0, 2);
  const groups: string[] = [];
  for (let rest = whole; rest; rest = rest.slice(0, -3)) {
    groups.unshift(rest.slice(-3));
  }
  return language === "en"
    ? `PLN ${groups.join(",")}.${frac}`
    : `${groups.join(".")},${frac} zł`;
}

/** „Mr Jan Kowalski – President of the Management Board” (lustro `representation_en`). */
export function representationEn(
  name: string,
  fn: string,
  gender: "m" | "k",
): string {
  const person = name.trim();
  if (!person) return "";
  const title = gender === "k" ? "Ms" : "Mr";
  const raw = fn.trim();
  const translated = FUNCTION_EN[raw.toLowerCase()] ?? raw;
  return translated ? `${title} ${person} – ${translated}` : `${title} ${person}`;
}

const text = (t: string, strong?: boolean): PaperSegment => ({
  kind: "text",
  text: t,
  strong,
});

function field(
  value: string,
  gap: { label: string; field: string; step: GeneratorFormStep },
  strong?: boolean,
): PaperSegment {
  const v = value.trim();
  return v ? { kind: "value", text: v, strong } : { kind: "gap", ...gap, strong };
}

/** Akapity kartki: tytuł, numer, data, strony, kontakt i początek preambuły. */
export function agreementPaper(input: PaperInput): PaperParagraph[] {
  const lang = input.language;
  const p = PAPER_PHRASES[lang];
  const company = input.variant === "company";
  const female = input.gender === "k";
  const signing = input.signingDate ? formatIsoDatePl(input.signingDate) : "";

  const party: PaperSegment[] = [];
  if (company) {
    party.push(
      field(
        input.partnerLegalName,
        { label: "nazwa spółki", field: "legalName", step: "partner" },
        true,
      ),
      text(" "),
      text(p.coSeat),
      lang === "pl"
        ? field(input.seatLocative, {
            label: "siedziba",
            field: "seatLocative",
            step: "partner",
          })
        : field(input.seat, { label: "siedziba", field: "seat", step: "partner" }),
      text(p.coAddress),
      field(input.partnerBusinessAddress, {
        label: "adres siedziby",
        field: "address",
        step: "partner",
      }),
      text(p.coRegister),
      field(input.registryCourt, {
        label: "sąd rejestrowy",
        field: "registryCourt",
        step: "partner",
      }),
      text(p.coKrs),
      field(input.krs, { label: "KRS", field: "krs", step: "partner" }),
      text(p.nip),
      field(input.partnerNip, { label: "NIP", field: "nip", step: "partner" }),
      text(p.regon),
      field(input.partnerRegon, { label: "REGON", field: "regon", step: "partner" }),
      text(p.coCapital),
      field(formatShareCapital(input.shareCapital, lang), {
        label: "kapitał",
        field: "shareCapital",
        step: "partner",
      }),
      text(p.coRepresented),
      lang === "pl"
        ? field(input.representation, {
            label: "reprezentacja",
            field: "representation",
            step: "partner",
          })
        : field(
            representationEn(
              input.representativeName,
              input.representativeFunction,
              input.gender,
            ),
            {
              label: "reprezentacja",
              field: "representativeName",
              step: "partner",
            },
          ),
      text(","),
    );
  } else {
    const person =
      lang === "pl"
        ? input.partnerInstrumental.trim() || input.partnerName.trim()
        : input.partnerName.trim();
    const personField =
      lang === "pl" && input.partnerName.trim()
        ? "partnerInstrumental"
        : "partnerName";
    const title =
      lang === "pl" ? (female ? "Panią" : "Panem") : female ? "Ms" : "Mr";
    party.push(
      text(`${title} `, true),
      field(
        person,
        { label: "imię i nazwisko", field: personField, step: "partner" },
        true,
      ),
      lang === "pl"
        ? text(` ${female ? "prowadzącą" : "prowadzącym"}${p.jdgBusiness}`)
        : text(` ${p.jdgBusiness}`),
      field(input.partnerLegalName, {
        label: "nazwa firmy",
        field: "legalName",
        step: "partner",
      }),
      text(p.jdgRegistered),
      ...(input.addressForService ? [text(p.forService)] : []),
      text(": "),
      field(input.partnerBusinessAddress, {
        label: "adres z CEIDG",
        field: "address",
        step: "partner",
      }),
      text(p.nip),
      field(input.partnerNip, { label: "NIP", field: "nip", step: "partner" }),
      text(p.regon),
      field(input.partnerRegon, { label: "REGON", field: "regon", step: "partner" }),
      text(","),
    );
  }
  const correspondence = input.correspondenceAddress.trim();
  if (correspondence) {
    party.push(text(p.correspondence), { kind: "value", text: correspondence }, text(","));
  }

  const partnerAs: PaperSegment[] =
    lang === "pl"
      ? [
          // Spółka to „ona”: „zwaną w dalszej części umowy” (render_context).
          text(company ? "zwaną" : female ? "zwana" : "zwany"),
          text(p.partnerAs),
        ]
      : [text(p.partnerAs)];

  return [
    { tone: "title", segments: [text(p.title)] },
    {
      tone: "subtitle",
      segments: [
        text(p.number),
        field(input.contractNumber, {
          label: "numer",
          field: "number",
          step: "warunki",
        }),
      ],
    },
    {
      tone: "body",
      segments: [
        text(p.concludedOn),
        field(signing, {
          label: "data podpisania",
          field: "signingDate",
          step: "warunki",
        }),
        text(p.concludedIn),
      ],
    },
    {
      tone: "muted",
      segments: [
        text(p.company, true),
        text(`${p.companySeat} (…), `),
        text(p.companyAs),
      ],
    },
    { tone: "body", segments: [text(p.and)] },
    { tone: "body", segments: party },
    { tone: "body", segments: [text(p.contact)] },
    {
      tone: "body",
      segments: [
        text(p.phone),
        field(input.phone, { label: "telefon", field: "phone", step: "partner" }),
        text(p.email),
        field(input.email, { label: "e-mail", field: "email", step: "partner" }),
      ],
    },
    { tone: "body", segments: partnerAs },
    { tone: "muted", segments: [text(`${p.preamble} 1) …`)] },
  ];
}

/** Liczba braków na kartce (wyróżnione „[…]”). */
export function paperGapCount(paragraphs: readonly PaperParagraph[]): number {
  return paragraphs.reduce(
    (n, para) => n + para.segments.filter((s) => s.kind === "gap").length,
    0,
  );
}
