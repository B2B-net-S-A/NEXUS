/**
 * Sprawdzenie firmy Partnera w CEIDG/KRS tuż przed „Pobierz DOCX” (ticket 6).
 *
 * Serwer (`GET /api/b2b-generator/company-verification`) pyta rejestr przy
 * każdym generowaniu i oddaje najnowsze dane firmy oraz ostrzeżenia o jej
 * statusie. Tu mieszka tylko decyzja, co z tym pokazać: różnice między
 * formularzem a rejestrem liczymy po normalizacji, żeby „ul. Prosta 1” i
 * „PROSTA 1” albo REGON 9- i 14-cyfrowy nie otwierały okna przy każdej umowie.
 *
 * Nic tu nie blokuje generowania — ostrzeżenia i brak weryfikacji są
 * informacją, użytkownik zawsze może kontynuować.
 */

export type RegistryWarning = { code: string; message: string };

export type RegistryCompany = {
  name: string | null;
  person: string | null;
  nip: string | null;
  regon: string | null;
  krs: string | null;
  address: string | null;
  entity_type: "sole_trader" | "company" | null;
};

export type CompanyVerification = {
  status: "verified" | "unverified";
  registry: "ceidg" | "krs" | null;
  checked_at: string;
  company: RegistryCompany | null;
  warnings: RegistryWarning[];
  /** Powód braku weryfikacji (rejestr niedostępny, brak firmy, brak NIP-u). */
  message: string | null;
};

export type PartnerRegistryFields = {
  legalName: string;
  address: string;
  regon: string;
};

export type RegistryDiffField = keyof PartnerRegistryFields;

export type RegistryDiff = {
  field: RegistryDiffField;
  label: string;
  form: string;
  registry: string;
};

const FIELD_LABELS: Record<RegistryDiffField, string> = {
  legalName: "Nazwa firmy",
  address: "Adres siedziby firmy",
  regon: "REGON",
};

/** Pole formularza → pole ładunku `/render`. */
export const REGISTRY_PAYLOAD_KEYS = {
  legalName: "partner_legal_name",
  address: "partner_business_address",
  regon: "partner_regon",
} as const satisfies Record<RegistryDiffField, string>;

function alnumUpper(value: string): string {
  return value.toLocaleUpperCase("pl-PL").replace(/[^\p{L}\p{N}]/gu, "");
}

// Skróty typu ulicy piszą ludzie różnie („ul.”, „ulica”, bez skrótu), a CEIDG
// i Biała Lista też każde po swojemu. Porównujemy więc sam adres.
const STREET_TYPES = /(^|[\s,])(UL|ULICA|AL|ALEJA|ALEJE|PL|PLAC|OS|OSIEDLE)\.?(?=\s)/gu;

function addressKey(value: string): string {
  return alnumUpper(value.toLocaleUpperCase("pl-PL").replace(STREET_TYPES, "$1"));
}

function regonKey(value: string): string {
  const digits = value.replace(/\D/g, "");
  // REGON 14-cyfrowy z pięcioma zerami na końcu to ten sam podmiot co 9-cyfrowy.
  return digits.length === 14 && digits.endsWith("00000") ? digits.slice(0, 9) : digits;
}

const KEYS: Record<RegistryDiffField, (value: string) => string> = {
  legalName: alnumUpper,
  address: addressKey,
  regon: regonKey,
};

const REGISTRY_VALUE: Record<RegistryDiffField, keyof RegistryCompany> = {
  legalName: "name",
  address: "address",
  regon: "regon",
};

/** Pola, w których rejestr mówi co innego niż formularz. Brak wartości
 *  w rejestrze to nie różnica — nie mamy czym zastąpić wpisu. */
export function registryDiffs(
  form: PartnerRegistryFields,
  company: RegistryCompany | null,
): RegistryDiff[] {
  if (!company) return [];
  const diffs: RegistryDiff[] = [];
  for (const field of Object.keys(FIELD_LABELS) as RegistryDiffField[]) {
    const registry = String(company[REGISTRY_VALUE[field]] ?? "").trim();
    if (!registry) continue;
    const current = form[field].trim();
    if (KEYS[field](current) === KEYS[field](registry)) continue;
    diffs.push({ field, label: FIELD_LABELS[field], form: current, registry });
  }
  return diffs;
}

/** Okno przed generowaniem tylko wtedy, gdy jest o czym powiedzieć. */
export function needsRegistryDialog(
  verification: CompanyVerification,
  diffs: RegistryDiff[],
): boolean {
  return (
    verification.status !== "verified" ||
    verification.warnings.length > 0 ||
    diffs.length > 0
  );
}

export function registryName(registry: CompanyVerification["registry"]): string {
  if (registry === "ceidg") return "CEIDG";
  if (registry === "krs") return "KRS";
  return "rejestrze";
}

/** Awaria samego zapytania do NEXUSA (sieć, 5xx) — też „nie zweryfikowano”. */
export function verificationFailed(): CompanyVerification {
  return {
    status: "unverified",
    registry: null,
    checked_at: new Date().toISOString(),
    company: null,
    warnings: [],
    message: "Nie udało się połączyć z usługą sprawdzania rejestru.",
  };
}

export function registryOverrides(
  diffs: RegistryDiff[],
): Partial<Record<(typeof REGISTRY_PAYLOAD_KEYS)[RegistryDiffField], string>> {
  return Object.fromEntries(
    diffs.map((d) => [REGISTRY_PAYLOAD_KEYS[d.field], d.registry]),
  );
}
