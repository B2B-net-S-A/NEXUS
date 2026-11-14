/**
 * Lista płac w Księgowości (K7a) — czyste funkcje ekranu listy płac: kwoty z API
 * (złote jako tekst), grupy umów z sumami, liczby nad tabelą, podstawa
 * pozycji, problemy i to, które przyciski działają.
 */
import type { StatusDotTone } from "@/components/ds";
import type {
  GrossInput,
  GrossInputBody,
  PayrollKind,
  PayrollLine,
  PayrollLineResult,
  PayrollList,
  PayrollListStatus,
  PayrollMonth,
  PayrollProblem,
  RegistrationKind,
} from "@/lib/api/payroll-lists";

import { datePl, gr } from "../ledger-model";

/**
 * Grosze z kwoty API („5646.86” → 564686). Trzecia cyfra po przecinku
 * zaokrągla pół w górę; brak albo nieczytelna kwota = `null`.
 */
export function grosze(amount: string | number | null | undefined): number | null {
  if (amount == null || amount === "") return null;
  const text = String(amount).trim();
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) {
    const value = Number(text);
    return Number.isFinite(value) ? Math.round(value * 100) : null;
  }
  const fraction = (match[3] ?? "").padEnd(3, "0");
  let cents = Number(match[2]) * 100 + Number(fraction.slice(0, 2));
  if (Number(fraction[2]) >= 5) cents += 1;
  return match[1] && cents ? -cents : cents;
}

/** „5 646,86” — kwota API w złotych; brak = „—”. */
export function zl(amount: string | number | null | undefined): string {
  return gr(grosze(amount));
}

/** „168”, „7,5” — godziny i MD bez zbędnych zer. */
export function quantity(raw: string | number | null | undefined): string {
  const value = Number(raw);
  if (raw == null || raw === "" || !Number.isFinite(value)) return "—";
  return String(value).replace(".", ",");
}

/** „1 pozycja”, „3 pozycje”, „5 pozycji” — odmiana po liczbie. */
export function plural(count: number, one: string, few: string, many: string): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return `${count} ${one}`;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} ${few}`;
  return `${count} ${many}`;
}

/** Stan rozliczenia klienta (kontraktor na zleceniu) po polsku. */
export const SETTLEMENT_STATUS: Record<string, string> = {
  checking: "w sprawdzaniu",
  ok: "sprawdzone, nieprzyjęte",
  warnings: "z ostrzeżeniami, nieprzyjęte",
  needs_fix: "do poprawy",
  no_md: "bez MD",
  accepted: "przyjęte",
};

/** Źródło kwoty pozycji (lustro `SOURCE_LABEL` z serwera). */
export const SOURCE_LABELS: Record<string, string> = {
  payroll_line: "„Mój miesiąc” i premie",
  client_settlement: "rozliczenie klienta",
  manual: "kwota wpisana przez Rozliczenia",
  missing: "brak kwoty",
};

/** Pola danych osoby potrzebne do KEDU i PIT-11 (`basis.missing_files`). */
export const FILE_FIELD_LABELS: Record<string, string> = {
  address: "adres zamieszkania",
  tax_office_code: "urząd skarbowy",
  zus_title_code: "kod tytułu ubezpieczenia",
};

/** „10/2026” — miesiąc listy. */
export function periodLabel(year: number, month: number): string {
  return `${String(month).padStart(2, "0")}/${year}`;
}

/** Segment adresu miesiąca w „Ludzie → Rozliczenia” (`/people/payroll/2026-10`). */
export function peoplePayrollHref(year: number, month: number): string {
  return `/people/payroll/${year}-${String(month).padStart(2, "0")}`;
}

export const KIND_ORDER: readonly PayrollKind[] = ["uop", "zlecenie", "dzielo"];

export const KIND_GROUPS: Record<PayrollKind, string> = {
  uop: "Umowy o pracę",
  zlecenie: "Umowy zlecenia — zespół i kontraktorzy u klientów",
  dzielo: "Umowy o dzieło",
};

const KIND_SHORT: Record<PayrollKind, string> = { uop: "UoP", zlecenie: "zlecenia", dzielo: "dzieła" };

/** „UoP i zlecenia”, „UoP, zlecenia i dzieła” — formy umów na liście. */
export function kindsTitle(lines: readonly PayrollLine[]): string {
  const names = KIND_ORDER.filter((kind) => lines.some((line) => line.kind === kind)).map((kind) => KIND_SHORT[kind]);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} i ${names[names.length - 1]}`;
}

export const AMOUNT_COLUMNS = [
  { key: "gross", label: "Brutto" },
  { key: "social_employee", label: "Społeczne" },
  { key: "health", label: "Zdrowotna" },
  { key: "pit", label: "Zaliczka PIT" },
  { key: "net", label: "Do wypłaty" },
  { key: "employer_social", label: "Pracodawca" },
] as const;

export type AmountKey = (typeof AMOUNT_COLUMNS)[number]["key"];

export interface LineGroup {
  kind: string;
  label: string;
  lines: PayrollLine[];
  /** Sumy kolumn w groszach — pozycja bez kwoty liczy się jak zero. */
  sums: Record<AmountKey, number>;
}

/** Pozycje w grupach umów (UoP, zlecenia, dzieła) z sumami kolumn. */
export function groupLines(lines: readonly PayrollLine[]): LineGroup[] {
  const kinds: string[] = [...KIND_ORDER];
  for (const line of lines) if (!kinds.includes(line.kind)) kinds.push(line.kind);
  return kinds.flatMap((kind) => {
    const items = lines.filter((line) => line.kind === kind);
    if (!items.length) return [];
    const sums = Object.fromEntries(
      AMOUNT_COLUMNS.map((column) => [
        column.key,
        items.reduce((sum, line) => sum + (grosze(line[column.key]) ?? 0), 0),
      ]),
    ) as Record<AmountKey, number>;
    const label = KIND_GROUPS[kind as PayrollKind] ?? items[0].kind_label;
    return [{ kind, label, lines: items, sums }];
  });
}

/** „Zlecenie — zespół”, „Zlecenie — kontraktor u klienta”, „Umowa o pracę”. */
export function personSubline(line: PayrollLine): string {
  if (line.kind === "uop") return line.kind_label;
  return `${line.kind_label} — ${line.candidate_id != null ? "kontraktor u klienta" : "zespół"}`;
}

export interface BasisText {
  main: string;
  sub: string | null;
}

/** Kolumna „Podstawa”: godziny × stawka albo skąd kwota. */
export function basisText(line: PayrollLine): BasisText {
  const basis = line.basis ?? {};
  const bonus = grosze(basis.bonus_total) ?? 0;
  const hours = Number(basis.hours);
  if (line.source === "payroll_line" && hours > 0 && basis.hourly_rate) {
    return {
      main: `${quantity(basis.hours)} h × ${zl(basis.hourly_rate)}`,
      sub: bonus > 0 ? `„Mój miesiąc” + premie ${gr(bonus)}` : "„Mój miesiąc”",
    };
  }
  if (line.source === "manual") {
    const sub = [basis.outside_month ? "umowa poza miesiącem" : null, basis.note || null].filter(Boolean).join(" · ");
    return { main: "kwota Rozliczeń", sub: sub || null };
  }
  if (line.source === "client_settlement") {
    return { main: "rozliczenie klienta", sub: basis.md_charged ? `${quantity(basis.md_charged)} MD` : null };
  }
  if (line.source === "missing") {
    return { main: "brak kwoty", sub: basis.settlement_status ? "rozliczenie nieprzyjęte" : "bez rozliczenia klienta" };
  }
  if (line.source === "payroll_line") {
    return { main: "„Mój miesiąc”", sub: bonus > 0 ? `w tym premie ${gr(bonus)}` : null };
  }
  return { main: line.source_label, sub: null };
}

export interface PayrollKpi {
  id: string;
  label: string;
  value: string;
  title?: string;
}

function due(iso: string | null | undefined): string {
  return iso ? ` (do ${datePl(iso).slice(0, 5)})` : "";
}

/** Liczby nad tabelą: osoby, brutto, wypłata, ZUS, PIT, PPK, pracodawca. */
export function kpiStats(list: PayrollList): PayrollKpi[] {
  const totals = list.totals;
  const deadlines = totals.deadlines;
  const flat = grosze(totals.pit_flat) ?? 0;
  const ppk = (grosze(totals.ppk_employee) ?? 0) + (grosze(totals.ppk_employer) ?? 0);
  const stats: PayrollKpi[] = [
    { id: "people", label: "Osób na liście", value: String(totals.people ?? 0) },
    { id: "gross", label: "Brutto", value: `${zl(totals.gross)} zł` },
    { id: "net", label: `Do wypłaty${due(deadlines?.pay_date ?? list.pay_date)}`, value: `${zl(totals.net)} zł` },
    {
      id: "zus",
      label: `ZUS razem${due(deadlines?.zus)}`,
      value: `${zl(totals.zus_due)} zł`,
      title: "Składki osób i pracodawcy, zdrowotna, Fundusz Pracy i FGŚP — jeden przelew na rachunek składkowy",
    },
    flat > 0
      ? {
          id: "pit",
          label: `PIT-4 i PIT-8AR${due(deadlines?.pit)}`,
          value: `${zl(totals.pit)} zł`,
          title: `Zaliczki (PIT-4) ${zl(totals.pit_scale)} zł, podatek ryczałtowy (PIT-8AR) ${zl(totals.pit_flat)} zł`,
        }
      : { id: "pit", label: `PIT-4${due(deadlines?.pit)}`, value: `${zl(totals.pit)} zł` },
  ];
  if (ppk > 0) {
    stats.push({
      id: "ppk",
      label: `PPK${due(deadlines?.ppk)}`,
      value: `${gr(ppk)} zł`,
      title: `Wpłaty osób ${zl(totals.ppk_employee)} zł, pracodawcy ${zl(totals.ppk_employer)} zł`,
    });
  }
  stats.push({
    id: "employer",
    label: "Składki pracodawcy",
    value: `${zl(totals.employer_social)} zł`,
    title: "Emerytalna, rentowa i wypadkowa pracodawcy, Fundusz Pracy i FGŚP",
  });
  return stats;
}

export const LIST_STATUS: Record<PayrollListStatus, { label: string; tone: StatusDotTone }> = {
  draft: { label: "Szkic do zatwierdzenia", tone: "warning" },
  approved: { label: "Zatwierdzona", tone: "success" },
  cancelled: { label: "Anulowana", tone: "neutral" },
};

function by(name: string | null): string {
  return name ? ` (${name})` : "";
}

/** Drobny druk pod stanem listy: kto i kiedy, co dalej. */
export function statusNote(list: PayrollList): string {
  if (list.status === "draft") {
    return `policzona ${datePl(list.computed_at)}${by(list.computed_by)}`;
  }
  if (list.status === "approved") {
    const parts = [`zatwierdzona ${datePl(list.approved_at)}${by(list.approved_by)}`];
    if (list.paid_at) parts.push(`bank wykonał przelewy ${datePl(list.paid_at)}`);
    else if (list.transfers_created_at) parts.push(`plik przelewów pobrany ${datePl(list.transfers_created_at)}`);
    return parts.join(" · ");
  }
  return `anulowana ${datePl(list.cancelled_at)}${list.cancel_reason ? `: ${list.cancel_reason}` : ""}`;
}

export interface ActionState {
  enabled: boolean;
  /** Dlaczego nieaktywne (dymek i tekst pod przyciskami). */
  reason: string | null;
}

export interface ListActions {
  compute: ActionState;
  payslips: ActionState;
  kedu: ActionState;
  transfers: ActionState;
  approve: ActionState & { visible: boolean };
  cancel: { visible: boolean };
}

/** Które przyciski nagłówka działają — z tego, co mówi serwer o miesiącu. */
export function listActions(month: PayrollMonth): ListActions {
  const list = month.list;
  const draft = list?.status === "draft";
  const approved = list?.status === "approved";
  const withAmounts = list?.lines.some((line) => line.gross != null) ?? false;
  const off = (reason: string): ActionState => ({ enabled: false, reason });
  const on: ActionState = { enabled: true, reason: null };
  return {
    compute: month.can_compute
      ? on
      : off(
          month.period_status !== "closed"
            ? "Najpierw zamknij miesiąc w Rozliczeniach — lista liczy się z zamrożonych kwot."
            : "Zatwierdzonej listy się nie przelicza — najpierw ją anuluj.",
        ),
    payslips: !list
      ? off("Najpierw przelicz listę.")
      : list.status === "cancelled"
        ? off("Lista jest anulowana.")
        : withAmounts
          ? on
          : off("Na liście nie ma pozycji z kwotą."),
    kedu: approved ? on : off("Deklaracje ZUS powstają z zatwierdzonej listy."),
    transfers: approved ? on : off("Przelewy powstają z zatwierdzonej listy."),
    approve: {
      visible: draft,
      enabled: draft && Boolean(list?.can_approve),
      reason: draft && !list?.can_approve ? (list?.approve_refusal ?? "Tej listy nie zatwierdzisz.") : null,
    },
    cancel: { visible: Boolean(list) && list?.status !== "cancelled" && !list?.paid_at },
  };
}

export interface ProblemGroup {
  code: string;
  label: string;
  blocking: boolean;
  people: string[];
}

/** Problemy listy pogrupowane po rodzaju (blokujące najpierw) z osobami. */
export function groupProblems(problems: readonly PayrollProblem[]): ProblemGroup[] {
  const groups = new Map<string, ProblemGroup>();
  for (const problem of problems) {
    const key = `${problem.blocking ? "1" : "0"}:${problem.code}`;
    let group = groups.get(key);
    if (!group) {
      group = { code: problem.code, label: problem.label, blocking: problem.blocking, people: [] };
      groups.set(key, group);
    }
    if (problem.person && !group.people.includes(problem.person)) group.people.push(problem.person);
  }
  return [...groups.values()].sort((a, b) => Number(b.blocking) - Number(a.blocking));
}

/** „Anna Przykładowa, Jan Testowy i jeszcze 2”. */
export function peopleText(people: readonly string[], shown = 3): string {
  if (people.length <= shown) return people.join(", ");
  return `${people.slice(0, shown).join(", ")} i jeszcze ${people.length - shown}`;
}

/** Najcięższy problem pozycji: blokujący, do uwagi albo brak. */
export function lineMarker(line: PayrollLine): "blocking" | "warning" | null {
  if (line.problems.some((problem) => problem.blocking)) return "blocking";
  return line.problems.length ? "warning" : null;
}

/** Kwota Rozliczeń wpisana dla osoby albo kontraktu tej pozycji. */
export function inputFor(line: PayrollLine, inputs: readonly GrossInput[]): GrossInput | null {
  if (line.contract_id != null) return inputs.find((item) => item.contract_id === line.contract_id) ?? null;
  if (line.user_id != null) {
    return inputs.find((item) => item.user_id === line.user_id && item.kind === line.kind) ?? null;
  }
  return null;
}

/**
 * Ciało `PUT …/inputs` dla pozycji: kontrakt u klienta albo osoba z formą
 * umowy. Zapis kwoty niesie też podstawę Funduszu Pracy (`null` = kwota
 * brutto) — serwer zastępuje cały wpis; usunięcie idzie bez opisu.
 */
export function inputBody(
  line: PayrollLine,
  gross: string | null,
  note?: string,
  fundBasis: string | null = null,
): GrossInputBody | null {
  const base = line.contract_id != null ? { contract_id: line.contract_id } : line.user_id != null ? { user_id: line.user_id } : null;
  if (!base) return null;
  return { ...base, kind: line.kind, gross, ...(gross != null ? { note, fund_basis: fundBasis } : {}) };
}

/** Kwoty Rozliczeń wpisane po ostatnim przeliczeniu szkicu — lista ich jeszcze nie zna. */
export function inputsAfterCompute(month: PayrollMonth): boolean {
  const list = month.list;
  if (!list || list.status !== "draft" || !list.computed_at) return false;
  const computed = Date.parse(list.computed_at);
  return month.inputs.some((item) => item.entered_at != null && Date.parse(item.entered_at) > computed);
}

const GROSS_MAX = 10_000_000_00;

/**
 * Kwota brutto z formularza → tekst dla API („1234.50”). Zero jest dozwolone
 * (osoba pominięta w miesiącu); minus, więcej niż dwie cyfry po przecinku
 * i ponad 10 mln zł = `null`.
 */
export function parseGross(raw: string): string | null {
  const text = raw.replace(/[\s ]/g, "").replace(",", ".");
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (cents > GROSS_MAX) return null;
  return `${Number(whole)}.${fraction.padEnd(2, "0")}`;
}

/** Kwota API do pola formularza („1234.5” → „1234,50”). */
export function amountInput(amount: string | null | undefined): string {
  const cents = grosze(amount);
  if (cents == null) return "";
  return `${cents < 0 ? "-" : ""}${Math.floor(Math.abs(cents) / 100)},${String(Math.abs(cents) % 100).padStart(2, "0")}`;
}

export interface BreakdownRow {
  label: string;
  value: string;
  strong?: boolean;
}

export interface BreakdownSection {
  title: string;
  rows: BreakdownRow[];
}

type Spec = { key: string; label: string; strong?: boolean; optional?: boolean };

const TAX_KIND: Record<string, string> = {
  scale: "Zaliczka PIT (skala)",
  flat: "Podatek ryczałtowy (PIT-8AR)",
  exempt: "PIT — zwolnienie",
  none: "PIT — bez podatku",
};

const SECTIONS: readonly { title: string; rows: readonly Spec[] }[] = [
  {
    title: "Składki osoby",
    rows: [
      { key: "pension_employee", label: "Emerytalna" },
      { key: "disability_employee", label: "Rentowa" },
      { key: "sickness_employee", label: "Chorobowa" },
      { key: "social_employee", label: "Społeczne razem", strong: true },
      { key: "health", label: "Zdrowotna" },
    ],
  },
  {
    title: "Podatek",
    rows: [
      { key: "revenue", label: "Przychód" },
      { key: "exempt_revenue", label: "W tym zwolniony (ulga)", optional: true },
      { key: "kup", label: "Koszty uzyskania" },
      { key: "tax_base", label: "Podstawa opodatkowania" },
      { key: "tax_reduction", label: "Kwota zmniejszająca (PIT-2)", optional: true },
      { key: "pit", label: "Zaliczka PIT", strong: true },
    ],
  },
  {
    title: "PPK",
    rows: [
      { key: "ppk_employee", label: "Wpłata osoby", optional: true },
      { key: "ppk_employer", label: "Wpłata pracodawcy", optional: true },
    ],
  },
  {
    title: "Pracodawca",
    rows: [
      { key: "pension_employer", label: "Emerytalna" },
      { key: "disability_employer", label: "Rentowa" },
      { key: "accident_employer", label: "Wypadkowa" },
      { key: "labour_fund", label: "Fundusz Pracy i Solidarnościowy" },
      { key: "fgsp", label: "FGŚP" },
      { key: "employer_social", label: "Składki pracodawcy razem", strong: true },
      { key: "employer_cost", label: "Koszt pracodawcy", strong: true },
    ],
  },
];

function amountOf(result: PayrollLineResult, key: string): string | null {
  const value = result[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}

/** Rozpisanie wyniku silnika na sekcje; puste wiersze opcjonalne znikają. */
export function breakdown(result: PayrollLineResult): BreakdownSection[] {
  return SECTIONS.flatMap((section) => {
    const rows = section.rows.flatMap((spec): BreakdownRow[] => {
      const amount = amountOf(result, spec.key);
      if (amount == null || (spec.optional && !grosze(amount))) return [];
      const label = spec.key === "pit" && result.tax_kind ? (TAX_KIND[result.tax_kind] ?? spec.label) : spec.label;
      return [{ label, value: zl(amount), strong: spec.strong }];
    });
    return rows.length ? [{ title: section.title, rows }] : [];
  });
}

export interface ErrorDetail {
  status: number | null;
  code: string | null;
  /** `detail` FastAPI, gdy jest obiektem (`{code, message, …}`). */
  detail: Record<string, unknown> | null;
}

/** Kod i dane błędu z odpowiedzi API (axios albo pobranie pliku). */
export function errorDetail(error: unknown): ErrorDetail {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)?.response;
  const raw = (response?.data as { detail?: unknown } | null | undefined)?.detail;
  const detail = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
  return {
    status: typeof response?.status === "number" ? response.status : null,
    code: typeof detail?.code === "string" ? detail.code : null,
    detail,
  };
}

export interface FileProblem {
  title: string;
  message: string;
  items: string[];
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/**
 * Odmowa pliku z listą osób — do okna, nie do dymku: KEDU bez danych osób
 * (`kedu_data_missing`, osoba i braki) albo zgłoszenia ZUS bez nikogo do
 * zgłoszenia (`nothing_to_register`, kto i dlaczego pominięty).
 */
export function fileProblem(error: unknown): FileProblem | null {
  const { code, detail } = errorDetail(error);
  if (!detail) return null;
  const message = typeof detail.message === "string" ? detail.message : "";
  if (code === "kedu_data_missing" && Array.isArray(detail.people)) {
    const items = detail.people.flatMap((item) => {
      const row = item as { person?: unknown; missing?: unknown } | null;
      if (typeof row?.person !== "string") return [];
      const missing = texts(row.missing);
      return [`${row.person}: ${missing.length ? missing.join(", ") : "brak danych"}`];
    });
    return { title: "Deklaracja ZUS — brakuje danych osób", message, items };
  }
  if (code === "nothing_to_register" && Array.isArray(detail.skipped)) {
    const items = detail.skipped.flatMap((item) => {
      const row = item as { name?: unknown; kind?: unknown; reason?: unknown } | null;
      if (typeof row?.name !== "string") return [];
      const kind = typeof row.kind === "string" && row.kind ? ` (${row.kind})` : "";
      return [`${row.name}${kind}: ${typeof row.reason === "string" ? row.reason : "pominięta"}`];
    });
    return { title: "Zgłoszenia ZUS — nie ma kogo zgłosić", message, items };
  }
  return null;
}

export const REGISTRATION_KINDS: Record<RegistrationKind, string> = {
  ZUA: "zgłoszenie do ubezpieczeń",
  ZZA: "zgłoszenie do ubezpieczenia zdrowotnego",
  ZWUA: "wyrejestrowanie z ubezpieczeń",
};

/** Pierwszy i ostatni dzień miesiąca („2026-10-01”, „2026-10-31”). */
export function monthRange(year: number, month: number): { from: string; to: string } {
  const mm = String(month).padStart(2, "0");
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return { from: `${year}-${mm}-01`, to: `${year}-${mm}-${String(last).padStart(2, "0")}` };
}

/** Najdłuższy zakres zgłoszeń: kwartał. */
export const REGISTRATION_MAX_DAYS = 92;

/** Dlaczego zakresu dat nie da się pokazać; `null` = zakres dobry. */
export function rangeProblem(from: string, to: string): string | null {
  const iso = /^\d{4}-\d{2}-\d{2}$/;
  if (!iso.test(from) || !iso.test(to)) return "Podaj obie daty.";
  const days = (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000;
  if (!Number.isFinite(days)) return "Podaj obie daty.";
  if (days < 0) return "Data „od” jest po dacie „do”.";
  if (days + 1 > REGISTRATION_MAX_DAYS) return "Zakres najwyżej kwartał (92 dni).";
  return null;
}
