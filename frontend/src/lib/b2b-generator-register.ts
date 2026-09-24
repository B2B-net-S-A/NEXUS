// Czyste reguły Generatora Umów B2B — wyniesione z komponentu
// (`components/v2/pages/B2BContractGeneratorV2.tsx`), bo tamten ma ponad 4 tys.
// linii i te decyzje dają się sprawdzić bez montowania formularza.
import type {
  B2BContractStatus,
  B2BGeneratedContractRow,
} from "@/lib/api";
import { formatIsoDatePl } from "@/lib/date-pl";

// ── Zakładki w adresie (`?tab=`) ────────────────────────────────────────────

export type GeneratorTab =
  | "generator"
  | "generated"
  | "no-project"
  | "closed"
  | "documents"
  | "roles";

export const GENERATOR_TABS: readonly GeneratorTab[] = [
  "generator",
  "generated",
  "no-project",
  "closed",
  "documents",
  "roles",
] as const;

// Czytelne aliasy, bo link wpisuje też człowiek („?tab=ended"). Wartość
// kanoniczna to identyfikator zakładki — ten sam, który trafia do adresu.
const TAB_ALIASES: Record<string, GeneratorTab> = {
  current: "generated",
  "without-project": "no-project",
  ended: "closed",
};

export function generatorTabFromParam(
  value: string | null | undefined,
): GeneratorTab | null {
  if (!value) return null;
  const v = value.trim();
  if ((GENERATOR_TABS as readonly string[]).includes(v)) return v as GeneratorTab;
  return TAB_ALIASES[v] ?? null;
}

/** Zakładka rejestru, w której leży wiersz o danym statusie. */
export function registerTabForStatus(status: B2BContractStatus): GeneratorTab {
  if (status === "suspended") return "no-project";
  if (status === "closed") return "closed";
  return "generated";
}

/** Link do rejestru z wyszukiwaniem po numerze umowy. */
export function registerSearchHref(
  contractNumber: string,
  status: B2BContractStatus,
): string {
  const params = new URLSearchParams({
    tab: registerTabForStatus(status),
    q: contractNumber,
  });
  return `/contracts/b2b-generator?${params.toString()}`;
}

/**
 * Czy wiersz da się wczytać do formularza i poprawić pod tym samym numerem —
 * lustro bramki `GET /generated/{id}/form` i `/rerender`: autor albo admin
 * (`can_edit`), tylko niepodpisana umowa „W trakcie”, z dostępem do treści
 * dokumentu (`can_download` — rola bez stawek formularza nie zobaczy).
 */
export function canCorrectInForm(
  row: Pick<
    B2BGeneratedContractRow,
    "can_edit" | "can_download" | "contract_status" | "signature_status"
  >,
): boolean {
  return (
    row.can_edit &&
    row.can_download &&
    row.contract_status === "in_progress" &&
    row.signature_status !== "signed_both"
  );
}

/** Link otwierający zapisaną umowę w formularzu do poprawki (`?edit=`). */
export function generatorEditHref(generatedId: number): string {
  return `/contracts/b2b-generator?tab=generator&edit=${generatedId}`;
}

/** Link do formularza z wybranym kandydatem i rekrutacją (krok 08 „Umowa"). */
export function generatorPrefillHref(
  candidateId: number | null | undefined,
  jobId: number | null | undefined,
): string {
  if (!candidateId) return "/contracts/b2b-generator";
  const params = new URLSearchParams({
    tab: "generator",
    candidate: String(candidateId),
  });
  if (jobId) params.set("job", String(jobId));
  return `/contracts/b2b-generator?${params.toString()}`;
}

// ── Stronicowanie rejestru („Pokaż więcej") ─────────────────────────────────

export const B2B_REGISTER_PAGE_SIZE = 100;

/**
 * Klucz sortowania „1500/2026" → [2026, 1500]. Numer spoza formatu (stary,
 * wpisany ręcznie) ląduje na końcu listy — lepiej niż wyrzucić wiersz.
 */
function contractNumberKey(value: string): [number, number] {
  const match = /^\s*(\d+)\s*\/\s*(\d{4})\s*$/.exec(value ?? "");
  if (!match) return [-1, -1];
  return [Number(match[2]), Number(match[1])];
}

/**
 * Strony rejestru złożone w jedną listę.
 *
 * Serwer tnie okno po `created_at` (świeża umowa z ręcznie wpisanym niskim
 * numerem nie wypada z pierwszej strony), a sortuje po numerze WEWNĄTRZ
 * strony — po doładowaniu kolejnej trzeba posortować całość jeszcze raz, bo
 * inaczej numery skakałyby na granicy stron. Deduplikacja po `id`, bo umowa
 * wygenerowana między pobraniem stron przesuwa okno o jeden wiersz i ten sam
 * wpis przyszedłby dwa razy.
 */
export function mergeRegisterPages(
  pages: readonly (readonly B2BGeneratedContractRow[])[],
): B2BGeneratedContractRow[] {
  const byId = new Map<number, B2BGeneratedContractRow>();
  for (const page of pages) {
    for (const row of page) {
      if (!byId.has(row.id)) byId.set(row.id, row);
    }
  }
  return Array.from(byId.values()).sort((a, b) => {
    const [ay, as] = contractNumberKey(a.contract_number);
    const [by, bs] = contractNumberKey(b.contract_number);
    return by - ay || bs - as || b.id - a.id;
  });
}

/**
 * Offset następnej strony albo `undefined`, gdy ostatnia była niepełna.
 * Niepełna strona to koniec rejestru — pełna MOŻE nim być (dokładnie 100
 * wierszy), więc przycisk raz za dużo jest ceną za brak osobnego licznika.
 */
export function nextRegisterOffset(
  lastPage: readonly unknown[],
  pageCount: number,
  pageSize: number = B2B_REGISTER_PAGE_SIZE,
): number | undefined {
  return lastPage.length >= pageSize ? pageCount * pageSize : undefined;
}

// ── Okno „Status umowy" ─────────────────────────────────────────────────────

export interface ContractStatusOption {
  value: B2BContractStatus;
  /** Wyszarzona pozycja — widoczna, żeby trigger nie był pusty, ale niewybieralna. */
  disabled: boolean;
}

/**
 * Pozycje listy statusów dla wiersza — lustro reguł PATCH-a
 * `/api/b2b-generator/generated/{id}`.
 *
 * - „Aktywna" = podpisana obustronnie. Ręcznie tylko dla podpisanej albo dla
 *   wiersza, który już jest aktywny (bez tej pozycji trigger byłby pusty).
 *   Zawieszona wraca przyciskiem „Przywróć" (wymaga projektu), anulowana
 *   i niepodpisana — przez „W trakcie" i „Oznacz jako podpisaną".
 * - „W trakcie" zawsze na liście, wybieralna w dwóch przypadkach: powrót
 *   z „Anulowanej" i cofnięcie pomyłkowego zakończenia NIEPODPISANEJ umowy.
 * - „Anulowana" tylko dla niepodpisanej umowy, która jeszcze się nie
 *   zakończyła — zakończona wraca najpierw na „W trakcie".
 * - „Zawieszona" tylko dla umowy obowiązującej.
 */
export function contractStatusOptions(
  row: Pick<B2BGeneratedContractRow, "contract_status" | "signature_status">,
): ContractStatusOption[] {
  const current = row.contract_status;
  const signed = row.signature_status === "signed_both";
  const options: ContractStatusOption[] = [];

  const activeAllowed =
    current === "active" ||
    (signed && current !== "suspended" && current !== "cancelled");
  if (activeAllowed) options.push({ value: "active", disabled: false });

  const returnToProgress =
    current === "cancelled" || (current === "closed" && !signed);
  options.push({ value: "in_progress", disabled: !returnToProgress });

  const cancelAllowed = !signed && current !== "closed";
  if (cancelAllowed || current === "cancelled") {
    options.push({ value: "cancelled", disabled: false });
  }

  if (current === "active" || current === "suspended") {
    options.push({ value: "suspended", disabled: false });
  }

  options.push({ value: "closed", disabled: false });
  return options;
}

// ── Ostrzeżenia w wierszu rejestru ──────────────────────────────────────────

export interface RowWarning {
  /** `info` = plakietka informacyjna (np. „Z Excela”), nie ostrzeżenie. */
  tone: "info" | "warning" | "danger";
  text: string;
}

// ── Wiersze z rejestru Excela działu (0363) ─────────────────────────────────

/** Etykiety kodów `legacy_flags` z importu — tylko te, które coś mówią
 *  użytkownikowi rejestru. Nieznany kod nie jest pokazywany. */
export const EXCEL_FLAG_LABELS: Readonly<Record<string, RowWarning>> = {
  likely_ended: {
    tone: "warning",
    text: "W Excelu oznaczona jako zakończona — brak daty, sprawdź status",
  },
  without_project: { tone: "warning", text: "W Excelu: bez projektu" },
  row_highlight_orange: {
    tone: "warning",
    text: "W Excelu wyróżniona (nie doszła do skutku / bez projektu)",
  },
  start_date_unknown: { tone: "warning", text: "Data startu nieznana w Excelu" },
  start_date_uncertain: { tone: "warning", text: "Data startu niepewna w Excelu" },
  number_collision: { tone: "danger", text: "Numer powtórzony w Excelu" },
  deleted_number_reused: {
    tone: "danger",
    text: "Numer był wydany i usunięty w NEXUSIE",
  },
  candidate_ambiguous: {
    tone: "warning",
    text: "Kilku kandydatów o tym nazwisku — bez powiązania",
  },
};

export function isExcelRow(row: Pick<B2BGeneratedContractRow, "source">): boolean {
  return row.source === "excel";
}

/**
 * Plakietki wiersza z Excela: „Z Excela”, flagi importu, aneks danych firmy
 * i brak w ostatnio wgranym pliku. Wiersze z Excela są tylko do odczytu —
 * akcje chowa backend (`can_edit`/`can_delete`/`can_download` = false).
 */
export function excelRowBadges(
  row: Pick<
    B2BGeneratedContractRow,
    | "source"
    | "legacy_flags"
    | "needs_business_data_annex"
    | "business_data_annex_done_at"
    | "excel_missing_since"
  >,
): RowWarning[] {
  const badges: RowWarning[] = [];
  if (isExcelRow(row)) badges.push({ tone: "info", text: "Z Excela" });
  for (const flag of row.legacy_flags ?? []) {
    const label = EXCEL_FLAG_LABELS[flag];
    if (label) badges.push(label);
  }
  if (row.needs_business_data_annex) {
    badges.push(
      row.business_data_annex_done_at
        ? {
            tone: "info",
            text: `Aneks „dane firmy” zrobiony ${formatIsoDatePl(row.business_data_annex_done_at)}`,
          }
        : { tone: "warning", text: "Czeka na aneks „dane firmy”" },
    );
  }
  if (row.excel_missing_since) {
    badges.push({ tone: "warning", text: "Brak w ostatnim pliku Excela" });
  }
  return badges;
}

/**
 * Rozjazdy rejestru z modułem Kontrakty. Rejestr nie wie, że kontrakt się
 * skończył albo został usunięty (audyt 23.09.2026 — trzy umowy „Aktywne"
 * przy zakończonych kontraktach), więc wiersz to mówi, a status zmienia
 * człowiek.
 */
export function registerRowWarnings(
  row: Pick<
    B2BGeneratedContractRow,
    | "contract_status"
    | "signature_status"
    | "contract_id"
    | "linked_contract_status"
    | "linked_contract_end_date"
    | "source"
    | "legacy_flags"
    | "needs_business_data_annex"
    | "business_data_annex_done_at"
    | "excel_missing_since"
  >,
): RowWarning[] {
  const warnings: RowWarning[] = [...excelRowBadges(row)];
  const linked = row.linked_contract_status ?? null;
  const end = row.linked_contract_end_date ?? null;
  const live = row.contract_status === "active" || row.contract_status === "suspended";

  if (live && (linked === "ended" || linked === "void")) {
    warnings.push({
      tone: "danger",
      text: end
        ? `Kontrakt zakończony ${formatIsoDatePl(end)} — zmień status umowy`
        : "Kontrakt zakończony — zmień status umowy",
    });
  } else if (linked === "ending") {
    warnings.push({
      tone: "warning",
      text: end
        ? `Kontrakt kończy się ${formatIsoDatePl(end)}`
        : "Kontrakt się kończy",
    });
  }

  // Umowa z Excela nigdy nie miała kontraktu w NEXUSIE — brak nie jest
  // „usuniętym kontraktem”.
  if (
    row.signature_status === "signed_both" &&
    row.contract_id == null &&
    !isExcelRow(row)
  ) {
    warnings.push({
      tone: "danger",
      text: "Kontrakt usunięty — brak kontraktora",
    });
  }
  return warnings;
}

// ── Istniejąca umowa tej pary (kandydat, rekrutacja) ───────────────────────

const LIVE_STATUSES: ReadonlySet<B2BContractStatus> = new Set([
  "in_progress",
  "active",
  "suspended",
]);

/**
 * Żywa umowa tej osoby w tej rekrutacji — formularz ostrzega przed drugą.
 * `ignoreId` to wiersz, który formularz właśnie opisuje (po „Pobierz DOCX"),
 * żeby świeżo zapisana umowa nie ostrzegała sama przed sobą.
 */
export function existingContractFor(
  rows: readonly B2BGeneratedContractRow[],
  candidateId: number | null | undefined,
  ignoreId: number | null = null,
): B2BGeneratedContractRow | null {
  if (!candidateId) return null;
  return (
    rows.find(
      (r) =>
        r.candidate_id === candidateId &&
        r.id !== ignoreId &&
        LIVE_STATUSES.has(r.contract_status),
    ) ?? null
  );
}

// ── Nagłówek `X-Generated-Contract-Id` ──────────────────────────────────────

/** Id wiersza rejestru z nagłówka odpowiedzi (axios zwraca je małymi literami). */
export function generatedIdFromHeaders(headers: unknown): number | null {
  if (!headers || typeof headers !== "object") return null;
  const raw = (headers as Record<string, unknown>)["x-generated-contract-id"];
  if (typeof raw !== "string" || !/^\d+$/.test(raw.trim())) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

// ── Waluty ──────────────────────────────────────────────────────────────────

export const B2B_CURRENCIES = ["PLN", "EUR", "USD", "GBP", "CHF"] as const;
