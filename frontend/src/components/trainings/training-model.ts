// Czyste reguły ekranów „Szkolenia” po stronie NEXUSA (testy bez przeglądarki i bez API).
// Lustro `backend/app/services/trainings/core.py`: `STATUS_LABELS`, `DELIVERABLE_LABELS`,
// `DEFAULT_FORMATS`, `FEES`, `can_publish`, `fee_total`, `handover`.

import type {
  DeliverableInput,
  DeliverableKey,
  FeeKey,
  HandoverState,
  OrderInput,
  TrainingFee,
  TrainingFees,
  TrainingOrder,
  TrainingRow,
  TrainingStatus,
  TrainingView,
  TrainingsMe,
} from "@/lib/api/trainings";

export const STATUS_LABELS: Record<TrainingStatus, string> = {
  draft: "Szkic zamówienia",
  ordered: "Czeka na wycenę trenera",
  quoted: "Wycena do decyzji",
  returned: "Wycena odesłana do poprawy",
  accepted: "Umowa do podpisu trenera",
  trainer_signed: "Umowa czeka na podpis B2B Network",
  signed: "Umowa podpisana",
  cancelled: "Anulowane",
};

export type StatusTone = "neutral" | "info" | "warning" | "success" | "danger";

export const STATUS_TONES: Record<TrainingStatus, StatusTone> = {
  draft: "neutral",
  ordered: "info",
  quoted: "warning",
  returned: "info",
  accepted: "info",
  trainer_signed: "warning",
  signed: "success",
  cancelled: "danger",
};

export const DELIVERABLE_KEYS: readonly DeliverableKey[] = [
  "materials",
  "presentation",
  "audio",
  "other",
];

export const DELIVERABLE_LABELS: Record<DeliverableKey, string> = {
  materials: "Materiały dla uczestników",
  presentation: "Prezentacja",
  audio: "Pliki audio",
  other: "Inne pliki",
};

export const DEFAULT_FORMATS: Record<DeliverableKey, string> = {
  materials: "PDF",
  presentation: "PPTX do edycji i PDF dla uczestników",
  audio: "gotowy plik MP3 albo M4A, jeden na część",
  other: "",
};

/** Termin w dniach po szkoleniu (Zał. 1 pkt 4) — jak w makiecie umowy. */
export const DEFAULT_DUE_DAYS: Record<DeliverableKey, number | null> = {
  materials: 2,
  presentation: 2,
  audio: 7,
  other: null,
};

/** Domyślnie zaznaczone: materiały i prezentacja; audio i inne TCM dokłada sam. */
const DEFAULT_CHECKED: ReadonlySet<DeliverableKey> = new Set(["materials", "presentation"]);

export const FEE_SHORT: Record<FeeKey, string> = {
  fee_prep: "A. Program i materiały",
  fee_delivery: "B. Przeprowadzenie",
  fee_presentation: "C. Prezentacja",
  fee_audio: "D. Pliki audio",
  fee_rights: "E. Prawa autorskie",
};

export const HANDOVER_LABELS: Record<HandoverState, string> = {
  missing: "Nie przekazano",
  submitted: "Do sprawdzenia",
  accepted: "Przyjęte",
  returned: "Zwrócone do poprawy",
};

export const HANDOVER_TONES: Record<HandoverState, StatusTone> = {
  missing: "neutral",
  submitted: "warning",
  accepted: "success",
  returned: "danger",
};

export const EDITABLE_ORDER: readonly TrainingStatus[] = ["draft", "ordered", "quoted", "returned"];
export const CANCELLABLE: readonly TrainingStatus[] = [
  "draft",
  "ordered",
  "quoted",
  "returned",
  "accepted",
  "trainer_signed",
];

// ── Kroki ────────────────────────────────────────────────────────────────────

export const CONSULTANT_STEPS = [
  "Zamówienie",
  "Wycena",
  "Umowa",
  "Szkolenie",
  "Przekazanie",
  "Zapłata",
  "Biblioteka",
] as const;

/** Szkolenie pracownika nie ma wyceny, umowy B2B ani zapłaty. */
export const EMPLOYEE_STEPS = ["Zamówienie", "Szkolenie", "Biblioteka"] as const;

export interface StepState {
  labels: readonly string[];
  /** Indeks bieżącego kroku; `-1` przy anulowanym szkoleniu. */
  current: number;
  /** Wszystkie kroki zrobione (szkolenie w bibliotece). */
  complete: boolean;
  cancelled: boolean;
}

type StepInput = Pick<TrainingView, "status" | "trainer_kind" | "published_at" | "handover"> & {
  order: Pick<TrainingOrder, "session_date">;
  payment: TrainingView["payment"];
};

/** Dzień w kalendarzu firmy (Europe/Warsaw) jako `RRRR-MM-DD`. */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Warsaw" }).format(now);
}

function sessionAhead(sessionDate: string | null, today: string): boolean {
  return sessionDate === null || sessionDate >= today;
}

export function trainingSteps(view: StepInput, today: string): StepState {
  const employee = view.trainer_kind === "employee";
  const labels = employee ? EMPLOYEE_STEPS : CONSULTANT_STEPS;
  const last = labels.length - 1;
  if (view.status === "cancelled") {
    return { labels, current: -1, complete: false, cancelled: true };
  }
  const at = (current: number, complete = false): StepState => ({
    labels,
    current,
    complete,
    cancelled: false,
  });
  if (view.published_at) return at(last, true);
  if (view.status === "draft") return at(0);
  if (employee) {
    return at(sessionAhead(view.order.session_date, today) ? 1 : 2);
  }
  if (view.status === "ordered" || view.status === "quoted" || view.status === "returned") {
    return at(1);
  }
  if (view.status === "accepted" || view.status === "trainer_signed") return at(2);
  // signed
  if (view.payment.paid_at) return at(6);
  if (view.payment.invoice_ready_at) return at(5);
  const anyHandedOver = view.handover.some((item) => item.state !== "missing");
  if (!anyHandedOver && sessionAhead(view.order.session_date, today)) return at(3);
  return at(4);
}

// ── Kwoty ────────────────────────────────────────────────────────────────────

function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Suma A–E jak `core.fee_total`: `null`, gdy żadna pozycja nie ma kwoty. */
export function feeTotal(items: readonly Pick<TrainingFee, "amount">[]): number | null {
  const values = items.map((item) => toNumber(item.amount));
  if (values.every((value) => value === null)) return null;
  return values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
}

export interface FeeComparisonRow {
  key: FeeKey;
  label: string;
  amount: number | null;
  previous: number | null;
  /** Różnica do poprzedniego szkolenia; `null`, gdy brak którejś kwoty. */
  diff: number | null;
}

export interface FeeComparison {
  rows: FeeComparisonRow[];
  total: number | null;
  previousTotal: number | null;
  totalDiff: number | null;
}

function diffOf(amount: number | null, previous: number | null): number | null {
  return amount === null || previous === null ? null : amount - previous;
}

export function compareFees(current: TrainingFees, previous: TrainingFees | null): FeeComparison {
  const previousByKey = new Map(
    (previous?.items ?? []).map((item) => [item.key, toNumber(item.amount)] as const),
  );
  const rows = current.items.map((item) => {
    const amount = toNumber(item.amount);
    const before = previous ? previousByKey.get(item.key) ?? null : null;
    return {
      key: item.key,
      label: FEE_SHORT[item.key] ?? item.label,
      amount,
      previous: before,
      diff: diffOf(amount, before),
    };
  });
  const total = toNumber(current.total) ?? feeTotal(current.items);
  const previousTotal = previous ? toNumber(previous.total) ?? feeTotal(previous.items) : null;
  return { rows, total, previousTotal, totalDiff: diffOf(total, previousTotal) };
}

/**
 * Poprzednie szkolenie tego samego trenera z rejestru: ten sam kontrakt
 * (dwie osoby o tym samym nazwisku to dwa kontrakty), trener z umową, z kwotą,
 * nie anulowane, wcześniejsze od bieżącego. Najnowsze z nich.
 */
export function previousTrainingOf(
  rows: readonly TrainingRow[],
  current: Pick<TrainingView, "id" | "trainer_kind" | "trainer_contract_id"> & {
    order: Pick<TrainingOrder, "session_date">;
  },
): TrainingRow | null {
  if (current.trainer_kind !== "consultant" || current.trainer_contract_id === null) return null;
  const contractId = current.trainer_contract_id;
  const sessionDate = current.order.session_date;
  const candidates = rows.filter(
    (row) =>
      row.id !== current.id &&
      row.trainer_kind === "consultant" &&
      row.status !== "cancelled" &&
      row.total !== null &&
      row.trainer_contract_id === contractId &&
      (sessionDate && row.session_date ? row.session_date < sessionDate : row.id < current.id),
  );
  const sorted = [...candidates].sort((a, b) => {
    const byDate = (b.session_date ?? "").localeCompare(a.session_date ?? "");
    return byDate !== 0 ? byDate : b.id - a.id;
  });
  return sorted[0] ?? null;
}

const AMOUNT = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
  useGrouping: true,
});

/** „4 100” (bez waluty, kwoty netto w tabeli), pusta = „—”. Grupuje też 4 cyfry. */
export function formatAmount(value: number | null): string {
  if (value === null) return "—";
  const text = AMOUNT.format(value);
  return Math.abs(value) >= 1000 && Math.abs(value) < 10000
    ? text.replace(/^(-?\d)(\d{3})/, "$1 $2")
    : text;
}

// ── Publikacja ───────────────────────────────────────────────────────────────

/**
 * Dlaczego przycisk „Opublikuj” jest wyłączony; `null` = można publikować.
 * Regułę „nagranie publikuje druga osoba” rozstrzyga serwer (wiersz pliku nie
 * mówi, kto go wgrał), ekran mówi o niej w podpowiedzi.
 */
export function publishBlockReason(
  view: Pick<TrainingView, "status" | "trainer_kind" | "payment" | "files" | "can_publish">,
  me: Pick<TrainingsMe, "can_manage">,
): string | null {
  if (!me.can_manage) return "Publikuje Talent Community Manager albo administrator.";
  if (view.status === "cancelled") return "Szkolenie jest anulowane.";
  if (view.status !== "signed") {
    return view.trainer_kind === "employee"
      ? "Najpierw wyślij zamówienie."
      : "Najpierw obie strony podpisują umowę.";
  }
  if (view.trainer_kind === "consultant" && !view.payment.paid_at) {
    return "Szkolenie trenera z umową B2B wejdzie do biblioteki po zapłacie, bo dopiero wtedy przechodzą prawa autorskie (§ 8 ust. 3 umowy).";
  }
  const visible = view.files.some((file) => file.for_participants && file.status !== "replaced");
  if (!visible) return "Zaznacz przynajmniej jeden plik dla uczestników.";
  if (!view.can_publish) return "To szkolenie nie może jeszcze wejść do biblioteki.";
  return null;
}

/** Dlaczego „Zapłacone” jest wyłączone; `null` = Finanse mogą oznaczyć. */
export function paymentBlockReason(
  view: Pick<TrainingView, "status" | "trainer_kind" | "payment">,
  me: Pick<TrainingsMe, "can_pay">,
): string | null {
  if (view.trainer_kind !== "consultant") return "Szkolenie pracownika nie ma zapłaty.";
  if (!me.can_pay) return "Zapłatę oznacza zespół Finansów.";
  if (view.status !== "signed") return "Najpierw obie strony podpisują umowę.";
  if (!view.payment.invoice_ready_at) return "Zapłatę oznaczysz po przyjęciu wszystkich plików.";
  return null;
}

// ── Przekazanie plików ───────────────────────────────────────────────────────

export interface HandoverSummary {
  required: number;
  accepted: number;
  toReview: number;
  returned: number;
}

export function handoverSummary(view: Pick<TrainingView, "handover">): HandoverSummary {
  const required = view.handover.filter((item) => item.required);
  return {
    required: required.length,
    accepted: required.filter((item) => item.state === "accepted").length,
    toReview: view.handover.filter((item) => item.state === "submitted").length,
    returned: view.handover.filter((item) => item.state === "returned").length,
  };
}

/** Czy TCM może przyjąć albo zwrócić ten plik pozycji (stan pozycji i pliku). */
export function canReviewFile(
  state: HandoverState,
  fileStatus: TrainingView["files"][number]["status"],
): { accept: boolean; return: boolean } {
  if (fileStatus === "replaced") return { accept: false, return: false };
  return {
    accept: fileStatus !== "accepted",
    // Przyjęty plik można jeszcze cofnąć do poprawy (serwer to dopuszcza).
    return: fileStatus !== "returned" && state !== "missing",
  };
}

// ── Zamówienie ───────────────────────────────────────────────────────────────

export interface DeliverableDraft extends DeliverableInput {
  checked: boolean;
}

export function defaultDeliverables(): DeliverableDraft[] {
  return DELIVERABLE_KEYS.map((key) => ({
    key,
    checked: DEFAULT_CHECKED.has(key),
    label: key === "other" ? "" : DELIVERABLE_LABELS[key],
    required: true,
    format: DEFAULT_FORMATS[key],
    due_days: DEFAULT_DUE_DAYS[key],
  }));
}

/** Pozycje zamówienia → formularz: zapisane zaznaczone, reszta z domyślnych, odznaczona. */
export function deliverablesFromOrder(
  saved: readonly DeliverableInput[],
): DeliverableDraft[] {
  const byKey = new Map(saved.map((item) => [item.key, item] as const));
  return defaultDeliverables().map((draft) => {
    const item = byKey.get(draft.key);
    return item ? { ...item, checked: true } : { ...draft, checked: false };
  });
}

export function deliverablesPayload(drafts: readonly DeliverableDraft[]): DeliverableInput[] {
  return drafts
    .filter((draft) => draft.checked)
    .map(({ key, label, required, format, due_days }) => ({
      key,
      label: label.trim(),
      required,
      format: format.trim(),
      due_days,
    }));
}

/** Błąd formularza zamówienia przed wysłaniem do serwera; `null` = można zapisać. */
export function orderFormProblem(input: Pick<OrderInput, "title">, drafts: readonly DeliverableDraft[]): string | null {
  if (!input.title.trim()) return "Podaj nazwę szkolenia.";
  const other = drafts.find((draft) => draft.key === "other");
  if (other?.checked && !other.label.trim()) return "Nazwij „Inne pliki”.";
  const badDue = drafts.find(
    (draft) =>
      draft.checked &&
      draft.due_days !== null &&
      (!Number.isInteger(draft.due_days) || draft.due_days < 0 || draft.due_days > 60),
  );
  if (badDue) return "Termin przekazania podaj w dniach od szkolenia (0–60).";
  return null;
}

export function emptyOrder(): OrderInput {
  return {
    title: "",
    topic: "",
    description: "",
    session_date: null,
    time_from: "",
    time_to: "",
    duration_minutes: null,
    platform: "Microsoft Teams",
    join_url: "",
    expected_participants: null,
    quote_due_on: null,
    participant_materials: "",
    deliverables: [],
    knowledge_test: false,
    extra_terms: "",
    rehearsal: false,
    mandatory_roles: [],
  };
}

/** Etykiety ról w „Obowiązkowe dla roli” (0698); nieznana rola pokazuje się kluczem. */
export const MANDATORY_ROLE_LABELS: Record<string, string> = {
  admin: "Administratorzy",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Leadzi",
  talent_community_manager: "Talent Community Managerowie",
  finance: "Finanse",
  recruiter: "Rekruterzy",
  trainee: "Praktykanci",
  automation: "Automatyzacje",
  employee: "Pracownicy (Ludzie)",
  board: "Rada nadzorcza",
  back_office: "Back office",
};

export function mandatoryRoleLabel(role: string): string {
  return MANDATORY_ROLE_LABELS[role] ?? role;
}

/** „wt 18 lis, 15:00” z chwili startu próby (strefa przeglądarki = firma). */
export function rehearsalLabel(start: string | null): string | null {
  if (!start) return null;
  const date = new Date(start);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("pl-PL", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  }).format(date);
}

export function orderFromView(view: Pick<TrainingView, "order" | "join_url">): OrderInput {
  return {
    ...view.order,
    join_url: view.join_url ?? "",
    deliverables: view.order.deliverables.map((item) => ({ ...item })),
  };
}

// ── Pliki ────────────────────────────────────────────────────────────────────

export function formatBytes(size: number | null): string {
  if (size === null || size < 0) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(1).replace(".", ",")} GB`;
}

/** Sekunda startu rozdziału: dokładna z transkryptu, z agendy minuta × 60. */
export function chapterSecond(chapter: { start_minute: number; start_second?: number }): number {
  return chapter.start_second ?? chapter.start_minute * 60;
}

/** „12:40” albo „1:02:10” z sekundy startu rozdziału. */
export function chapterClock(second: number): string {
  const h = Math.floor(second / 3600);
  const m = Math.floor((second % 3600) / 60);
  const sec = Math.floor(second % 60);
  const mm = String(m).padStart(h > 0 ? 2 : 1, "0");
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** „01:35” z minuty startu rozdziału. */
export function chapterTime(startMinute: number): string {
  const hours = Math.floor(startMinute / 60);
  const minutes = startMinute % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function isPlayable(contentType: string | null, kind?: string): boolean {
  if (kind === "recording") return true;
  return Boolean(contentType && /^(video|audio)\//.test(contentType));
}

export function fileExtension(name: string): string {
  const match = /\.([a-z0-9]{1,5})$/i.exec(name);
  return match ? match[1].toUpperCase() : "PLIK";
}
