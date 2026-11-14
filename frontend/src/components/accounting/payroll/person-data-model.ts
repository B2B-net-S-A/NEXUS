/**
 * Dane kadrowo-płacowe osoby (K7a) — formularz okna „Dane płacowe”: pola
 * z odpowiedzi API, ciało `PUT` (tylko zmienione pola i wersja) i proste
 * sprawdzenia przed zapisem. Serwer sprawdza to samo i więcej (np. PESEL
 * zajęty przez inną osobę) — tu chodzi o szybką podpowiedź przy polu.
 *
 * PESEL, numer dokumentu i rachunek nigdy nie wracają z API w całości, więc
 * ich pola są puste: wpisana wartość zastępuje zapisaną, pusta niczego nie
 * zmienia.
 */
import type { AddressKey, PersonAddress, PersonData, PersonDataUpdate, Relief } from "@/lib/api/payroll-lists";

export const ADDRESS_FIELDS: readonly { key: AddressKey; label: string; placeholder?: string }[] = [
  { key: "country", label: "Kraj", placeholder: "PL" },
  { key: "voivodeship", label: "Województwo" },
  { key: "county", label: "Powiat" },
  { key: "commune", label: "Gmina" },
  { key: "city", label: "Miejscowość" },
  { key: "street", label: "Ulica" },
  { key: "house_number", label: "Nr domu" },
  { key: "flat_number", label: "Nr lokalu" },
  { key: "postal_code", label: "Kod pocztowy", placeholder: "00-000" },
  { key: "post_office", label: "Poczta" },
];

export const RELIEFS: readonly { key: Relief; label: string }[] = [
  { key: "family4", label: "Ulga dla rodzin 4+" },
  { key: "return", label: "Ulga na powrót" },
  { key: "senior", label: "Ulga dla seniora" },
];

export const PIT2_OPTIONS = [
  { value: "0", label: "brak" },
  { value: "12", label: "1/12" },
  { value: "24", label: "1/24" },
  { value: "36", label: "1/36" },
] as const;

export type Pit2Value = (typeof PIT2_OPTIONS)[number]["value"];

export interface PersonForm {
  /** Nowy PESEL — pusty = bez zmiany (zapisanego nie pokazujemy). */
  pesel: string;
  document_type: "" | "id_card" | "passport";
  /** Nowy numer dokumentu — pusty = bez zmiany. */
  document_number: string;
  birth_date: string;
  sex: "" | "F" | "M";
  /** NIP osoby bez PESEL-u (PIT-11). */
  nip: string;
  first_name: string;
  last_name: string;
  citizenship: string;
  address: Record<AddressKey, string>;
  tax_office_code: string;
  tax_office_name: string;
  zus_title_code: string;
  nfz_code: string;
  work_time: string;
  pit2: Pit2Value;
  kup: "standard" | "increased";
  reliefs: Relief[];
  youth_relief_waived: boolean;
  student_exempt_until: string;
  mandate_pension_insurance: boolean;
  mandate_sickness_voluntary: boolean;
  mandate_accident_insurance: boolean;
  ppk_participates: boolean;
  ppk_employee_rate: string;
  ppk_employee_extra: string;
  ppk_employer_extra: string;
  labour_fund_exempt_until: string;
  fgsp_exempt_until: string;
  /** Nowy rachunek do wypłaty (kontraktor) — pusty = bez zmiany. */
  bank_account: string;
}

const FULL_TIME = "1/1";

/** „2.00” → „2”, „0.50” → „0,5” — procent PPK do pola. */
function rateField(raw: string | null | undefined, fallback: string): string {
  const value = Number(raw ?? fallback);
  return Number.isFinite(value) ? String(value).replace(".", ",") : fallback;
}

function rateNumber(raw: string): number {
  const text = raw.trim().replace(",", ".");
  return text ? Number(text) : 0;
}

function savedAddress(address: PersonAddress | null, key: AddressKey): string {
  const value = (address?.[key] ?? "").trim();
  return key === "country" ? value.toUpperCase() || "PL" : value;
}

/** Stan formularza z odpowiedzi API (pola z pełnymi numerami puste). */
export function personForm(data: PersonData): PersonForm {
  return {
    pesel: "",
    document_type: data.document_type ?? "",
    document_number: "",
    birth_date: data.birth_date ?? "",
    sex: data.sex ?? "",
    nip: data.nip ?? "",
    first_name: data.first_name ?? "",
    last_name: data.last_name ?? "",
    citizenship: data.citizenship ?? "",
    address: Object.fromEntries(
      ADDRESS_FIELDS.map((field) => [field.key, savedAddress(data.address, field.key)]),
    ) as Record<AddressKey, string>,
    tax_office_code: data.tax_office_code ?? "",
    tax_office_name: data.tax_office_name ?? "",
    zus_title_code: data.zus_title_code ?? "",
    nfz_code: data.nfz_code ?? "",
    work_time: data.work_time || FULL_TIME,
    pit2: String(data.pit2 ?? 0) as Pit2Value,
    kup: data.kup ?? "standard",
    reliefs: [...(data.reliefs ?? [])],
    youth_relief_waived: Boolean(data.youth_relief_waived),
    student_exempt_until: data.student_exempt_until ?? "",
    mandate_pension_insurance: data.mandate?.pension_insurance ?? true,
    mandate_sickness_voluntary: data.mandate?.sickness_voluntary ?? false,
    mandate_accident_insurance: data.mandate?.accident_insurance ?? true,
    ppk_participates: data.ppk != null,
    ppk_employee_rate: rateField(data.ppk?.employee_rate, "2"),
    ppk_employee_extra: rateField(data.ppk?.employee_extra, "0"),
    ppk_employer_extra: rateField(data.ppk?.employer_extra, "0"),
    labour_fund_exempt_until: data.labour_fund_exempt_until ?? "",
    fgsp_exempt_until: data.fgsp_exempt_until ?? "",
    bank_account: "",
  };
}

const compact = (value: string) => value.replace(/\s/g, "");

/** Tekst do API: przycięty, pusty = `null` (czyści pole). */
function textOrNull(value: string): string | null {
  const text = value.trim();
  return text ? text : null;
}

/**
 * Ciało `PUT` z samymi zmianami i `expected_version`; `null`, gdy nic się nie
 * zmieniło. Imię i nazwisko z podpowiedzi konta (`names_confirmed: false`)
 * idą zawsze — zapis je potwierdza.
 */
export function personUpdate(data: PersonData, form: PersonForm): PersonDataUpdate | null {
  const body: PersonDataUpdate = { expected_version: data.version };
  const pesel = compact(form.pesel);
  if (pesel) body.pesel = pesel;
  if (form.document_type !== (data.document_type ?? "")) body.document_type = form.document_type || null;
  const documentNumber = compact(form.document_number).toUpperCase();
  if (documentNumber) body.document_number = documentNumber;
  if (form.birth_date !== (data.birth_date ?? "")) body.birth_date = form.birth_date || null;
  if (form.sex !== (data.sex ?? "")) body.sex = form.sex || null;
  const nip = form.nip.replace(/\D/g, "");
  if (nip !== (data.nip ?? "")) body.nip = nip || null;

  for (const key of ["first_name", "last_name"] as const) {
    const value = form[key].trim();
    if (value !== (data[key] ?? "").trim() || (!data.names_confirmed && value)) body[key] = value || null;
  }
  const citizenship = form.citizenship.trim().toUpperCase();
  if (citizenship !== (data.citizenship ?? "").toUpperCase()) body.citizenship = citizenship || null;

  const addressChanged = ADDRESS_FIELDS.some((field) => {
    const value = form.address[field.key].trim();
    return field.key === "country"
      ? (value.toUpperCase() || "PL") !== savedAddress(data.address, "country")
      : value !== savedAddress(data.address, field.key);
  });
  if (addressChanged) {
    const empty = ADDRESS_FIELDS.every((field) => field.key === "country" || !form.address[field.key].trim());
    body.address = empty
      ? null
      : (Object.fromEntries(
          ADDRESS_FIELDS.map((field) => {
            const value = form.address[field.key].trim();
            return [field.key, field.key === "country" ? value.toUpperCase() || "PL" : value || null];
          }),
        ) as PersonAddress);
  }

  const texts: [keyof PersonForm & keyof PersonData, string][] = [
    ["tax_office_code", compact(form.tax_office_code)],
    ["tax_office_name", form.tax_office_name.trim()],
    ["zus_title_code", compact(form.zus_title_code)],
    ["nfz_code", compact(form.nfz_code).toUpperCase()],
  ];
  for (const [key, value] of texts) {
    if (value !== ((data[key] as string | null) ?? "")) {
      (body as unknown as Record<string, string | null>)[key] = textOrNull(value);
    }
  }
  if (data.user_id != null) {
    const workTime = compact(form.work_time);
    if ((workTime || FULL_TIME) !== (data.work_time || FULL_TIME)) body.work_time = workTime || null;
  }

  if (Number(form.pit2) !== data.pit2) body.pit2 = Number(form.pit2) as PersonDataUpdate["pit2"];
  if (form.kup !== data.kup) body.kup = form.kup;
  const reliefs = [...form.reliefs].sort();
  if (reliefs.join(",") !== [...(data.reliefs ?? [])].sort().join(",")) body.reliefs = reliefs;
  if (form.youth_relief_waived !== Boolean(data.youth_relief_waived)) body.youth_relief_waived = form.youth_relief_waived;
  if (data.candidate_id != null && form.student_exempt_until !== (data.student_exempt_until ?? "")) {
    body.student_exempt_until = form.student_exempt_until || null;
  }
  if (form.mandate_pension_insurance !== data.mandate.pension_insurance) {
    body.mandate_pension_insurance = form.mandate_pension_insurance;
  }
  if (form.mandate_sickness_voluntary !== data.mandate.sickness_voluntary) {
    body.mandate_sickness_voluntary = form.mandate_sickness_voluntary;
  }
  if (form.mandate_accident_insurance !== data.mandate.accident_insurance) {
    body.mandate_accident_insurance = form.mandate_accident_insurance;
  }

  if (!form.ppk_participates) {
    if (data.ppk) body.ppk = { participates: false };
  } else {
    const rates = {
      employee_rate: form.ppk_employee_rate.trim().replace(",", ".") || "0",
      employee_extra: form.ppk_employee_extra.trim().replace(",", ".") || "0",
      employer_extra: form.ppk_employer_extra.trim().replace(",", ".") || "0",
    };
    const same =
      data.ppk != null &&
      Number(data.ppk.employee_rate) === Number(rates.employee_rate) &&
      Number(data.ppk.employee_extra ?? "0") === Number(rates.employee_extra) &&
      Number(data.ppk.employer_extra ?? "0") === Number(rates.employer_extra);
    if (!same) body.ppk = { participates: true, ...rates };
  }

  for (const key of ["labour_fund_exempt_until", "fgsp_exempt_until"] as const) {
    if (form[key] !== (data[key] ?? "")) body[key] = form[key] || null;
  }
  const account = compact(form.bank_account);
  if (data.candidate_id != null && account) body.bank_account = account;

  return Object.keys(body).length > 1 ? body : null;
}

const PESEL_WEIGHTS = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3];
const NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7];

/** Suma kontrolna PESEL-u (jak `pesel.checksum_ok` na serwerze). */
export function peselChecksumOk(value: string): boolean {
  if (!/^\d{11}$/.test(value)) return false;
  const total = PESEL_WEIGHTS.reduce((sum, weight, index) => sum + Number(value[index]) * weight, 0);
  return (10 - (total % 10)) % 10 === Number(value[10]);
}

/** Suma kontrolna NIP-u (jak `nip_checksum_valid` na serwerze; wynik 10 = nieważny). */
export function nipChecksumOk(value: string): boolean {
  if (!/^\d{10}$/.test(value)) return false;
  const control = NIP_WEIGHTS.reduce((sum, weight, index) => sum + Number(value[index]) * weight, 0) % 11;
  return control !== 10 && control === Number(value[9]);
}

function rateProblem(raw: string, label: string, low: number, high: number): string | null {
  const value = rateNumber(raw);
  if (!Number.isFinite(value) || value < low || value > high) {
    return `${label}: od ${String(low).replace(".", ",")} do ${String(high).replace(".", ",")}%.`;
  }
  return null;
}

/** Proste sprawdzenia przed zapisem — te same zdania co na serwerze. */
export function personFormProblems(form: PersonForm, data: PersonData): string[] {
  const problems: (string | null)[] = [];
  const pesel = compact(form.pesel);
  if (pesel) {
    if (!/^\d{11}$/.test(pesel)) problems.push("PESEL to 11 cyfr.");
    else if (!peselChecksumOk(pesel)) problems.push("PESEL ma złą cyfrę kontrolną — sprawdź numer.");
  }
  const documentNumber = compact(form.document_number);
  if (documentNumber && !/^[A-Za-z0-9]{5,20}$/.test(documentNumber)) problems.push("Numer dokumentu: 5–20 liter i cyfr.");
  if ((documentNumber || data.document_masked) && !form.document_type && !data.pesel_masked && !pesel) {
    problems.push("Podaj rodzaj dokumentu.");
  }
  const nip = form.nip.replace(/\D/g, "");
  if (form.nip.trim() && !nipChecksumOk(nip)) problems.push("NIP osoby: 10 cyfr z poprawną cyfrą kontrolną.");
  if (form.citizenship.trim() && !/^[A-Za-z]{2}$/.test(form.citizenship.trim())) {
    problems.push("Obywatelstwo: dwuliterowy kod, np. PL.");
  }
  const country = form.address.country.trim();
  if (country && !/^[A-Za-z]{2}$/.test(country)) problems.push("Kraj: dwuliterowy kod, np. PL.");
  const postal = form.address.postal_code.trim();
  if ((country.toUpperCase() || "PL") === "PL" && postal && !/^\d{2}-\d{3}$/.test(postal)) {
    problems.push("Kod pocztowy: w formacie 00-000.");
  }
  const office = compact(form.tax_office_code);
  if (office && !/^\d{4}$/.test(office)) problems.push("Kod urzędu skarbowego: 4 cyfry.");
  const title = compact(form.zus_title_code);
  if (title && !/^\d{6}$/.test(title)) problems.push("Kod tytułu ubezpieczenia: 6 cyfr, np. 011000.");
  const nfz = compact(form.nfz_code);
  if (nfz && !/^(0[1-9]|1[0-6])R$/i.test(nfz)) problems.push("Oddział NFZ: od 01R do 16R.");
  if (data.user_id != null) {
    const match = /^([1-9]\d?)\/([1-9]\d?)$/.exec(compact(form.work_time));
    if (compact(form.work_time) && (!match || Number(match[1]) > Number(match[2]))) {
      problems.push("Wymiar etatu: ułamek, np. 1/1 albo 1/2.");
    }
  }
  if (form.ppk_participates) {
    problems.push(rateProblem(form.ppk_employee_rate, "PPK — wpłata podstawowa osoby", 0.5, 2));
    problems.push(rateProblem(form.ppk_employee_extra, "PPK — wpłata dodatkowa osoby", 0, 2));
    problems.push(rateProblem(form.ppk_employer_extra, "PPK — wpłata dodatkowa pracodawcy", 0, 2.5));
  }
  const account = compact(form.bank_account).replace(/^PL/i, "");
  if (data.candidate_id != null && account && !/^\d{26}$/.test(account)) problems.push("Rachunek: 26 cyfr numeru NRB.");
  return problems.filter((problem): problem is string => problem != null);
}
