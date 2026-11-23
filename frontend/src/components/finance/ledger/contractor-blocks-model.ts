// Zajęcia wierzytelności i „Spór / wstrzymane” (Finanse → Przelewy, 0763).
// Kwoty, należność na dziś i blokady liczy serwer; tu tylko formularz
// i komunikaty dla osoby, która go wypełnia.

import type {
  Garnishment,
  GarnishmentAuthority,
  GarnishmentInput,
  GarnishmentInterest,
  ReleasedFromBatch,
} from "@/lib/api/finance-payments";

export interface GarnishmentForm {
  authority_kind: GarnishmentAuthority;
  authority_name: string;
  case_number: string;
  served_on: string;
  principal_amount: string;
  costs_amount: string;
  interest_mode: GarnishmentInterest;
  interest_amount: string;
  interest_rate: string;
  interest_from: string;
  authority_account: string;
  note: string;
}

export const AUTHORITY_OPTIONS: {
  value: GarnishmentAuthority;
  label: string;
}[] = [
  { value: "bailiff", label: "Komornik" },
  { value: "tax_office", label: "Urząd skarbowy (e-Urząd)" },
  { value: "other", label: "Inny organ" },
];

export const INTEREST_OPTIONS: { value: GarnishmentInterest; label: string }[] =
  [
    { value: "unknown", label: "Nieustalone — płatność czeka" },
    { value: "none", label: "Bez odsetek" },
    { value: "fixed", label: "Kwota odsetek z pisma" },
    { value: "rate", label: "Stopa roczna od dnia" },
  ];

export function emptyGarnishmentForm(today: string): GarnishmentForm {
  return {
    authority_kind: "bailiff",
    authority_name: "",
    case_number: "",
    served_on: today,
    principal_amount: "",
    costs_amount: "0",
    interest_mode: "unknown",
    interest_amount: "",
    interest_rate: "",
    interest_from: "",
    authority_account: "",
    note: "",
  };
}

export function formFromGarnishment(row: Garnishment): GarnishmentForm {
  return {
    authority_kind: row.authority_kind,
    authority_name: row.authority_name,
    case_number: row.case_number,
    served_on: row.served_on,
    principal_amount: row.principal_amount,
    costs_amount: row.costs_amount,
    interest_mode: row.interest_mode,
    interest_amount: row.interest_amount ?? "",
    interest_rate: row.interest_rate ?? "",
    interest_from: row.interest_from ?? "",
    authority_account: row.authority_account ?? "",
    note: row.note ?? "",
  };
}

/** Kwota z pola („1 234,50” albo „1234.5”) → „1234.50”; zła = `null`. */
export function amountText(raw: string): string | null {
  const plain = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(plain)) return null;
  return Number(plain).toFixed(2);
}

/** Formularz → treść żądania albo zdanie, czego brakuje. */
export function garnishmentInput(
  form: GarnishmentForm,
): { body: GarnishmentInput } | { error: string } {
  if (!form.authority_name.trim() || !form.case_number.trim()) {
    return { error: "Podaj organ i sygnaturę sprawy." };
  }
  if (!form.served_on) return { error: "Podaj datę doręczenia zajęcia." };
  const principal = amountText(form.principal_amount);
  if (principal === null || Number(principal) <= 0) {
    return { error: "Kwota należności musi być większa od zera." };
  }
  const costs = form.costs_amount.trim()
    ? amountText(form.costs_amount)
    : "0.00";
  if (costs === null) return { error: "Koszty to kwota (np. 120,00)." };
  let interestAmount: string | null = null;
  let interestRate: string | null = null;
  let interestFrom: string | null = null;
  if (form.interest_mode === "fixed") {
    interestAmount = amountText(form.interest_amount);
    if (interestAmount === null)
      return { error: "Wpisz kwotę odsetek z pisma organu." };
  }
  if (form.interest_mode === "rate") {
    const rate = form.interest_rate.replace(",", ".").trim();
    if (!/^\d{1,2}(\.\d{1,3})?$/.test(rate)) {
      return { error: "Stopa odsetek to procent rocznie (np. 11,25)." };
    }
    if (!form.interest_from)
      return { error: "Podaj dzień, od którego liczyć odsetki." };
    interestRate = rate;
    interestFrom = form.interest_from;
  }
  const account = form.authority_account.replace(/\s/g, "");
  return {
    body: {
      authority_kind: form.authority_kind,
      authority_name: form.authority_name.trim(),
      case_number: form.case_number.trim(),
      served_on: form.served_on,
      principal_amount: principal,
      costs_amount: costs,
      interest_mode: form.interest_mode,
      interest_amount: interestAmount,
      interest_rate: interestRate,
      interest_from: interestFrom,
      authority_account: account || null,
      note: form.note.trim() || null,
    },
  };
}

/** Komunikat po zmianie, która zdjęła faktury z paczek czekających na bank
 * albo zostawiła je tam, bo plik mógł już pójść do banku. */
export function releasedMessage(released: ReleasedFromBatch[]): string | null {
  if (released.length === 0) return null;
  const list = (rows: ReleasedFromBatch[]) =>
    Array.from(new Set(rows.map((r) => r.batch_id)))
      .map((id) => `#${id}`)
      .join(", ");
  const gone = released.filter((r) => r.released);
  const kept = released.filter((r) => !r.released);
  const parts: string[] = [];
  if (gone.length > 0) {
    parts.push(
      `Zdjęto z paczki ${list(gone)} (${gone.length}) — podział płatności się zmienił.`,
    );
  }
  const downloaded = kept.filter((r) => r.reason === "downloaded");
  if (downloaded.length > 0) {
    parts.push(
      `Paczka ${list(downloaded)} ma pobrany plik — jeśli bank go jeszcze nie wykonał, zdejmij fakturę z paczki i utwórz nową.`,
    );
  }
  const executed = kept.filter((r) => r.reason === "executed");
  if (executed.length > 0) {
    parts.push(
      `W paczce ${list(executed)} bank wykonał już część przelewów — pozycja zostaje, brakujący przelew dopasuj z wyciągu.`,
    );
  }
  return parts.join(" ");
}
