// Czyste reguły ekranów „Szkolenia” w panelu konsultanta (testy bez przeglądarki i bez API).
// Lustro `backend/app/services/trainings/core.py`: `check_fees`, `normalize_agenda`, `handover`.

import type {
  DeliverableKey,
  FeeKey,
  HandoverState,
  PortalTraining,
  PortalTrainingRow,
  TrainingAgendaItem,
  TrainingFee,
} from "@/lib/api/consultant-portal";

export const AGENDA_MAX = 12;
export const MINUTES_MIN = 5;
export const MINUTES_MAX = 600;

export const STEPS = ["Zamówienie", "Wycena", "Umowa", "Szkolenie", "Przekazanie", "Faktura"] as const;

/** Krótkie etykiety pozycji A–E do tabeli wyceny; pełne nazwy są w umowie. */
export const FEE_SHORT: Record<FeeKey, string> = {
  fee_prep: "A. Program i materiały",
  fee_delivery: "B. Przeprowadzenie",
  fee_presentation: "C. Prezentacja",
  fee_audio: "D. Pliki audio",
  fee_rights: "E. Prawa autorskie",
};

export const HANDOVER_LABELS: Record<HandoverState, string> = {
  missing: "Do wgrania",
  submitted: "Czeka na sprawdzenie",
  accepted: "Przyjęte",
  returned: "Do poprawy",
};

/** Dzień w kalendarzu firmy (Europe/Warsaw) jako `RRRR-MM-DD`. */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Warsaw" }).format(now);
}

/** Data `DD.MM.RRRR`; bez daty pusty napis, bo konsultant nie dostaje „—”. */
export function shortDay(iso: string | null): string {
  if (!iso) return "";
  const [year, month, day] = iso.split("T")[0].split("-");
  return `${day}.${month}.${year}`;
}

/** Pozycja C dotyczy tylko zamówienia z prezentacją, D tylko z audio; A, B i E zawsze. */
export function feeApplies(fee: Pick<TrainingFee, "needs">, ordered: DeliverableKey[]): boolean {
  return fee.needs === null || ordered.includes(fee.needs);
}

/** Kwota z pola: przecinek albo kropka, spacje tysięcy; `null` = puste albo nie liczba. */
export function parseAmount(value: string): number | null {
  const clean = value.replace(/\s/g, "").replace(",", ".");
  if (!clean) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
  return Number(clean);
}

/** Suma netto pozycji, które dotyczą zamówienia; pozostałe się nie liczą. */
export function feeSum(
  fees: Pick<TrainingFee, "key" | "needs">[],
  amounts: Partial<Record<FeeKey, string>>,
  ordered: DeliverableKey[],
): number {
  return fees
    .filter((fee) => feeApplies(fee, ordered))
    .reduce((sum, fee) => sum + (parseAmount(amounts[fee.key] ?? "") ?? 0), 0);
}

/** Brakujące albo błędne kwoty pozycji, które dotyczą zamówienia. */
export function missingFees(
  fees: Pick<TrainingFee, "key" | "needs">[],
  amounts: Partial<Record<FeeKey, string>>,
  ordered: DeliverableKey[],
): FeeKey[] {
  return fees
    .filter((fee) => feeApplies(fee, ordered) && parseAmount(amounts[fee.key] ?? "") === null)
    .map((fee) => fee.key);
}

export function agendaTotal(items: TrainingAgendaItem[]): number {
  return items.reduce((sum, item) => sum + (item.title.trim() ? Number(item.minutes) || 0 : 0), 0);
}

/** Zdanie o błędzie agendy albo `null`, gdy agenda przejdzie przez serwer. */
export function agendaProblem(items: TrainingAgendaItem[]): string | null {
  const filled = items.filter((item) => item.title.trim());
  if (filled.length === 0) return "Dodaj przynajmniej jeden moduł agendy.";
  if (filled.length > AGENDA_MAX) return `Agenda może mieć najwyżej ${AGENDA_MAX} modułów.`;
  const bad = filled.some((item) => {
    const minutes = Number(item.minutes);
    return !Number.isInteger(minutes) || minutes < MINUTES_MIN || minutes > MINUTES_MAX;
  });
  return bad ? `Czas każdego modułu podaj w minutach (${MINUTES_MIN}–${MINUTES_MAX}).` : null;
}

/** „180 min (3 h)”: suma minut agendy. */
export function minutesLabel(total: number): string {
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return `${total} min (${hours} h${rest ? ` ${rest} min` : ""})`;
}

/** „1 600 zł”: polski zapis nie grupuje czterech cyfr sam, a ekran NEXUSA pokazuje „1 600”. */
export function moneyLabel(value: number | string | null): string {
  if (value === null || value === "") return "";
  const amount = Number(value);
  const text = amount.toLocaleString("pl-PL", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const grouped =
    Math.abs(amount) >= 1000 && Math.abs(amount) < 10000 ? text.replace(/^(-?\d)(\d{3})/, "$1 $2") : text;
  return `${grouped} zł`;
}

/** Krok paska: 0 Zamówienie … 5 Faktura, 6 = wszystko za nami (zapłacone). */
export function currentStep(training: Pick<PortalTraining, "status" | "order" | "payment">, today: string): number {
  const { status, payment } = training;
  if (payment.paid_at) return STEPS.length;
  if (status === "ordered" || status === "returned" || status === "quoted" || status === "draft") return 1;
  if (status === "accepted" || status === "trainer_signed") return 2;
  if (status === "signed") {
    if (payment.invoice_ready_at) return 5;
    const day = training.order.session_date;
    return day && day >= today ? 3 : 4;
  }
  return 0;
}

export type StageTone = "warning" | "info" | "neutral" | "success" | "danger";

export interface Stage {
  label: string;
  tone: StageTone;
  /** Czy ruch jest po stronie konsultanta (przycisk w liście mówi wtedy, co zrobić). */
  yours: boolean;
}

/** Pigułka etapu na liście „Twoje szkolenia”. */
export function stageOf(
  row: Pick<PortalTrainingRow, "status" | "session_date" | "invoice_ready_at" | "paid_at">,
  today: string,
): Stage {
  if (row.paid_at) return { label: "Zapłacone", tone: "success", yours: false };
  switch (row.status) {
    case "ordered":
      return { label: "Do wyceny", tone: "warning", yours: true };
    case "returned":
      return { label: "Popraw wycenę", tone: "warning", yours: true };
    case "quoted":
      return { label: "Czekamy na decyzję o wycenie", tone: "info", yours: false };
    case "accepted":
      return { label: "Umowa do podpisu", tone: "warning", yours: true };
    case "trainer_signed":
      return { label: "Umowa czeka na nasz podpis", tone: "info", yours: false };
    case "signed":
      if (row.invoice_ready_at) return { label: "Wystaw fakturę", tone: "warning", yours: true };
      if (row.session_date && row.session_date >= today) return { label: "Szkolenie przed Tobą", tone: "info", yours: false };
      return { label: "Przekaż pliki", tone: "warning", yours: true };
    case "cancelled":
      return { label: "Anulowane", tone: "neutral", yours: false };
    default:
      return { label: "Zamówienie w przygotowaniu", tone: "neutral", yours: false };
  }
}

/** „01:35” dla minuty nagrania (rozdziały z agendy). */
/** „wt 18 lis, 15:00” z chwili startu próby technicznej (0698). */
export function rehearsalWhen(start: string | null): string | null {
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

export function clockLabel(minute: number): string {
  const hours = Math.floor(minute / 60);
  const rest = minute % 60;
  return `${String(hours).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function extensionLabel(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot >= 0 ? fileName.slice(dot + 1).toUpperCase() : "PLIK";
}

export function isPlayable(file: { content_type: string | null; file_name: string }): "video" | "audio" | null {
  const type = file.content_type ?? "";
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  const ext = extensionLabel(file.file_name);
  if (["MP4", "WEBM", "MOV", "M4V"].includes(ext)) return "video";
  if (["MP3", "M4A", "WAV", "OGG"].includes(ext)) return "audio";
  return null;
}

/** Pliki projektu montażowego i surowe nagrania nie są gotowym plikiem (Zał. 1 pkt 4). */
export const EDITOR_PROJECT_EXTENSIONS = ["drp", "prproj", "aep", "fcpx", "veg", "aup3", "logicx"];

export function isEditorProject(fileName: string): boolean {
  return EDITOR_PROJECT_EXTENSIONS.includes(extensionLabel(fileName).toLowerCase());
}
