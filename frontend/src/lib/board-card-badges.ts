/**
 * Odznaki karty na Tablicy — Pipeline v4 (decyzja Artura 23.09.2026), od
 * Rekrutacji v5 na 8 kolumnach (makiety
 * https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW).
 *
 * To, czego nie widać z kolumny, mówi karta:
 * skąd osoba przyszła, kto ją ma na 12 h, że czeka na przegląd DL, za ile
 * poszła do klienta, co się dzieje z rozmową u klienta i czy po zatrudnieniu
 * jest zamówienie. Wszystko liczy się z pól tablicy — tu tylko prezentacja,
 * żadnych reguł, które serwer musiałby powtórzyć.
 */

import { boardCardBadge } from "@/lib/recommendation-card";
import { agreementBadge } from "@/lib/b2b-agreement";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { BoardColumnKey, StageBadgeKey } from "@/lib/board-stages";
import { cardBadgeLabel } from "@/lib/candidate-followup";
import { WHY_CANDIDATE_LABEL } from "@/lib/pipeline-next-action";
import { autoMatchBadgeLabel, autoMatchBadgeTitle } from "@/lib/candidate-notes-view";
import { rateArrowLine, rateChangeBadgeText } from "@/lib/rate-change";
import { warsawToday } from "@/lib/warsaw-date";
import { addedToBaseTitle, addedToBaseView, newInBaseDaysText } from "@/lib/added-to-base";

export type CardBadgeTone =
  | "own"
  | "lock"
  | "free"
  | "reassign"
  | "wait"
  | "ok"
  | "urgent"
  | "info"
  | "neutral"
  | "rate";

export interface CardBadge {
  key: string;
  label: string;
  tone: CardBadgeTone;
  title?: string;
}

/** 0370: podpowiedź do odznak prepów — ruch karty nie jest blokowany. */
const PREP_BADGE_TITLE: Partial<Record<string, string>> = {
  prep_missing:
    "Przed rozmową u klienta brakuje prepu z kandydatem (Prep 1 — Delivery Lead, Prep 2 — rekruter). Umów go w kalendarzu „Rozmowy u klienta”.",
  prep_weak:
    "Prep odbył się, ale wypadł słabo (transkrypt z Teams). Warto umówić jeszcze jedną rozmowę przed spotkaniem u klienta.",
};

export interface CardBadgeContext {
  column: BoardColumnKey | null;
  /** Rekrutacja Nordei — przegląd DL kończy akceptacja do kolejki Cpro
   *  (13.10.2026), nie wysyłka do klienta. */
  cproEnabled: boolean;
  viewerId: number | null;
  now: Date;
  /** Odznaka etapu karty — „Z ogłoszenia" z etapu nie powtarza się ze źródła. */
  stageBadge?: string | null;
  /** Przegląd przed wysłaniem do klienta w tej rekrutacji należy do patrzącego
   *  (serwer: `viewer_owns_dl_review`) — „Czeka na Ciebie” zamiast „Czeka na DL”. */
  viewerOwnsDlReview?: boolean;
}

export const CARD_BADGE_TONE_CLASS: Record<CardBadgeTone, string> = {
  own: "bg-primary/15 text-primary",
  lock: "bg-muted text-muted-foreground",
  free: "bg-warning/15 text-warning",
  reassign: "bg-primary/10 text-primary",
  wait: "bg-warning/15 text-warning",
  ok: "bg-success/15 text-success",
  urgent: "bg-destructive/10 text-destructive",
  info: "bg-info/15 text-info",
  neutral: "bg-muted text-muted-foreground",
  rate: "bg-muted text-foreground tabular-nums",
};

const RATE_UNIT_LABEL: Record<string, string> = {
  hourly: "zł/h",
  daily: "zł/MD",
  monthly: "zł/mies.",
};

function firstName(full: string | null | undefined): string {
  return (full ?? "").trim().split(/\s+/)[0] || "ktoś";
}

/** „9 h", „<1 h" — ile zostało blokady. */
export function hoursLeft(until: string, now: Date): string {
  const ms = new Date(until).getTime() - now.getTime();
  if (ms <= 3_600_000) return "<1 h";
  return `${Math.floor(ms / 3_600_000)} h`;
}

function daysLabel(days: number): string {
  if (days <= 0) return "dziś";
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

// ── „Do wysłania do klienta” (13.10.2026) ───────────────────────────────────

const DAY_MS = 86_400_000;

/**
 * Karta czeka na Delivery Leada: kolumna „QC CV”, karta nie stoi już
 * w kolejce Cpro, a CV przeszło QC albo ktoś je przepuścił. Poza Nordeą DL
 * wysyła do klienta, u Nordei akceptuje do kolejki Cpro (13.10.2026). Przy
 * niesprawdzonym lub niezaliczonym QC ruch ma rekruter.
 */
export function isReadyForDlSend(
  item: KanbanItem,
  column: BoardColumnKey | null,
  inCproQueue: boolean,
): boolean {
  if (column !== "cv_qc" || inCproQueue) return false;
  return item.qc?.status === "passed" || item.qc?.status === "overridden";
}

function timeOf(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Od kiedy karta jest gotowa do wysłania: późniejsze z wejścia do kolumny
 * i zaliczenia QC — karta bywa w „QC CV” kilka dni, zanim QC przejdzie.
 * `null` = tablica nie zna którejś z dat (starszy serwer).
 */
function dlReadySince(item: KanbanItem): number | null {
  const moved = timeOf(item.moved_at);
  const ok = timeOf(item.qc?.ok_at);
  return moved == null || ok == null ? null : Math.max(moved, ok);
}

/** Dni KALENDARZOWE w Europe/Warsaw od gotowości — ta sama arytmetyka co
 *  `waitingFor` (`lib/api/boardTasks.ts`); bez dat zostają dni na etapie. */
function dlWaitingDays(item: KanbanItem, now: Date): number {
  const since = dlReadySince(item);
  if (since == null) return item.days_in_stage ?? 0;
  const dayNumber = (d: Date) => Date.parse(`${warsawToday(d)}T00:00:00Z`) / DAY_MS;
  return Math.max(0, Math.round(dayNumber(now) - dayNumber(new Date(since))));
}

/**
 * Kolejka przeglądu „po kolei” z kart kolumny „QC CV”: tylko gotowe do
 * wysłania (u Nordei — do akceptacji), najdłużej czekające pierwsze. Karty
 * w kolejce Cpro (ta sama kolumna, znacznik „W kolejce Cpro”) czekają już
 * na osobę od Cpro.
 */
export function dlSendQueue(
  qcColumnItems: readonly KanbanItem[],
  inCproQueue: (item: KanbanItem) => boolean,
  now: Date,
): KanbanItem[] {
  const since = (item: KanbanItem) =>
    dlReadySince(item) ?? now.getTime() - (item.days_in_stage ?? 0) * DAY_MS;
  return qcColumnItems
    .filter((item) => isReadyForDlSend(item, "cv_qc", inCproQueue(item)))
    .sort((a, b) => since(a) - since(b));
}

export function formatClientRate(item: KanbanItem): string | null {
  if (item.client_rate_value == null || item.client_rate_value === "") return null;
  const value = Number(item.client_rate_value);
  if (!Number.isFinite(value)) return null;
  const unit = RATE_UNIT_LABEL[item.client_rate_unit ?? "hourly"] ?? "zł/h";
  const currency = item.client_rate_currency && item.client_rate_currency !== "PLN"
    ? ` ${item.client_rate_currency}`
    : "";
  const shown = Number.isInteger(value) ? String(value) : value.toFixed(2);
  return `do klienta ${shown}${currency} ${unit}`;
}

/**
 * 0404: zgłoszenie z linku rekrutacji po przeglądzie AI. Werdykt liczy serwer
 * (`services/application_screening.py`); tu tylko etykieta. „Dodaj mimo to”
 * (osoba odrzucona przez AI, dodana ręcznie) mówi to wprost.
 */
export function aiScreeningBadge(
  meta: KanbanItem["entry_ai_screening"],
): { label: string; tone: CardBadgeTone; title: string } | null {
  if (!meta) return null;
  const must =
    meta.must_total != null && meta.must_total > 0
      ? ` Must-have w CV: ${meta.must_found ?? 0} z ${meta.must_total}.`
      : "";
  if (meta.overridden) {
    return {
      label: "AI: odrzucony · dodany ręcznie",
      tone: "neutral",
      title: `Zgłoszenie z ogłoszenia. AI uznało je za niepasujące, ktoś dodał osobę mimo to.${must}`,
    };
  }
  if (!meta.assessed) {
    return {
      label: "AI nie oceniło",
      tone: "info",
      title: `Zgłoszenie z ogłoszenia. AI nie oceniło CV (brak czytelnego CV albo awaria) — sprawdź sam.${must}`,
    };
  }
  if (meta.verdict === "fits") {
    return {
      label: "AI: pasuje",
      tone: "ok",
      title: `Zgłoszenie z ogłoszenia. AI: doświadczenie pasuje do roli.${must}`,
    };
  }
  return {
    label: "AI: do sprawdzenia",
    tone: "info",
    title: `Zgłoszenie z ogłoszenia. AI nie jest pewne dopasowania — sprawdź CV.${must}`,
  };
}

function sourceBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge | null {
  switch (item.entry_source) {
    case "added_manual": {
      const own = item.claim_user_id != null && item.claim_user_id === ctx.viewerId;
      return {
        key: "source",
        label: own ? "Dodałeś sam" : `Dodał(a): ${firstName(item.added_to_job_by_name)}`,
        tone: "neutral",
        title: item.added_to_job_by_name
          ? `Do rekrutacji dodał(a): ${item.added_to_job_by_name}`
          : undefined,
      };
    }
    case "application": {
      const ai = aiScreeningBadge(item.entry_ai_screening);
      return ai
        ? { key: "source", label: ai.label, tone: ai.tone, title: ai.title }
        : { key: "source", label: "Z ogłoszenia", tone: "neutral" };
    }
    case "proposal":
      return { key: "source", label: "Propozycja", tone: "neutral" };
    case "auto_match":
      return {
        key: "source",
        label: autoMatchBadgeLabel(item.entry_auto_match) ?? "Z automatu",
        tone: "neutral",
        title: autoMatchBadgeTitle(item.entry_auto_match),
      };
    default:
      return null;
  }
}

/**
 * Runda 10 (F04): znacznik etapu „Z ogłoszenia" tylko wtedy, gdy osoba
 * naprawdę przyszła z ogłoszenia. Ręczne dodanie też ląduje na etapie
 * „Ogłoszenia" szablonu, a karta mówiła wtedy „Z ogłoszenia" obok „Dodałeś
 * sam". Źródło nieznane (proces sprzed 0352) zostawia dawny znacznik.
 */
export function cardStageBadge(
  item: Pick<KanbanItem, "entry_source">,
  badge: StageBadgeKey | null | undefined,
): StageBadgeKey | null {
  if (!badge) return null;
  if (badge === "posting" && item.entry_source && item.entry_source !== "application") {
    return null;
  }
  return badge;
}

/**
 * „W bazie od” (13.10.2026): osoba dodana do bazy w ostatnich 14 dniach —
 * rekruter wybiera w „Nowych” najpierw świeże osoby. Źródło i blokada są na
 * karcie ikonami, więc to krótki napis; pełna data i autor w dymku.
 */
function newInBaseBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge | null {
  const view = addedToBaseView(
    { at: item.candidate_added_at, exact: item.candidate_added_exact },
    ctx.now,
  );
  if (!view?.isNew || view.days == null) return null;
  return {
    key: "new_in_base",
    label: `Nowy · ${newInBaseDaysText(view.days)}`,
    tone: "info",
    title: addedToBaseTitle(view, item.candidate_added_by_name),
  };
}

function claimBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge {
  if (item.claim_user_id != null && item.claim_until) {
    const left = hoursLeft(item.claim_until, ctx.now);
    if (item.claim_user_id === ctx.viewerId) {
      return {
        key: "claim",
        label: `Twój · ${left}`,
        tone: "own",
        title: "Masz tę osobę na wyłączność w tej rekrutacji — potem każdy może ją przejąć.",
      };
    }
    return {
      key: "claim",
      label: `${firstName(item.claim_user_name)} · ${left}`,
      tone: "lock",
      title: `Tę osobę prowadzi ${item.claim_user_name ?? "inna osoba"} — do końca blokady nie da się jej ruszyć.`,
    };
  }
  return {
    key: "claim",
    label: "Wolny",
    tone: "free",
    title: "Nikt nie ma tej osoby na wyłączność — „Biorę” daje Ci 12 h.",
  };
}

export function cardBadges(item: KanbanItem, ctx: CardBadgeContext): CardBadge[] {
  const out: CardBadge[] = [];
  const column = ctx.column;
  if (item.entry_source === "reassign") {
    out.push({
      key: "reassign",
      // Numer rekrutacji („ZOB-1725”) jest krótszy i jednoznaczny; tytuł
      // zostaje, gdy rekrutacja numeru nie ma (np. założona w NEXUSIE).
      label: item.reassign_from_reference
        ? `↻ z ${item.reassign_from_reference}`
        : item.reassign_from_title
          ? `Przepięcie · ${item.reassign_from_title}`
          : "Przepięcie",
      tone: "reassign",
      title: item.reassign_from_title
        ? `Osoba była już wysłana do klienta przy podobnej rekrutacji: ${item.reassign_from_title}.`
        : "Osoba była już wysłana do klienta przy podobnej rekrutacji.",
    });
  }
  if (column === "new" || column === "screening") {
    const source = sourceBadge(item, ctx);
    const duplicatesStage = ctx.stageBadge === "posting" && item.entry_source === "application";
    if (source && !duplicatesStage) out.push(source);
    out.push(claimBadge(item, ctx));
    const fresh = newInBaseBadge(item, ctx);
    if (fresh) out.push(fresh);
  }
  // Przegląd DL (Rekrutacja v5): osoby w „QC CV" poza Nordeą — Delivery Lead
  // sprawdza CV, wpisuje stawkę do klienta i wysyła.
  // DL czeka dopiero na CV, które przeszło QC (albo przepuszczone) — przy
  // niesprawdzonym lub niezaliczonym QC ruch ma rekruter. Dni liczą się od
  // gotowości, nie od wejścia do kolumny; Delivery Lead tej rekrutacji czyta
  // „Czeka na Ciebie” (13.10.2026).
  if (isReadyForDlSend(item, column, ctx.stageBadge === "cpro")) {
    const waited = daysLabel(dlWaitingDays(item, ctx.now));
    out.push(
      ctx.viewerOwnsDlReview
        ? {
            key: "dl_review",
            label: `Czeka na Ciebie · ${waited}`,
            tone: "wait",
            title: ctx.cproEnabled
              ? "Przejrzyj CV, wpisz stawkę do Cpro i zaakceptuj do kolejki Cpro."
              : "Przejrzyj CV, wpisz stawkę do klienta i wyślij.",
          }
        : {
            key: "dl_review",
            label: `Czeka na DL · ${waited}`,
            tone: "wait",
            title: ctx.cproEnabled
              ? "Delivery Lead przegląda CV, wpisuje stawkę do Cpro i akceptuje osobę do kolejki Cpro."
              : "Delivery Lead przegląda CV i wpisuje stawkę do klienta przed wysłaniem.",
          },
    );
  }
  // 0413: stan karty rekomendacji — braki są informacją, nic nie blokują.
  const cardBadge = boardCardBadge(item.card, item.contact_attempts ?? 0, column);
  if (cardBadge && item.card !== undefined) {
    out.push({ key: "recommendation_card", ...cardBadge });
  }
  const rate = formatClientRate(item);
  if (
    rate &&
    (column === "cv_sent" ||
      column === "client_interview" ||
      column === "contract" ||
      column === "hired")
  ) {
    out.push({ key: "client_rate", label: rate, tone: "rate" });
  }
  // 0418: kandydat zmienił stawkę w trakcie procesu — plakietka do zamknięcia
  // sprawy (decyzja DL albo wynik negocjacji), w każdej kolumnie.
  if (item.rate_change) {
    const rc = item.rate_change;
    const arrow = rateArrowLine(rc);
    out.push({
      key: "rate_change",
      label: arrow ? `${arrow} · ${rateChangeBadgeText(rc)}` : rateChangeBadgeText(rc),
      tone: rc.status === "agreed" ? "ok" : rc.status === "negotiating" ? "info" : "wait",
      title:
        "Kandydat zmienił stawkę w trakcie procesu. Szczegóły i historia w panelu osoby.",
    });
  }
  if (column === "cv_sent" && (item.days_in_stage ?? 0) >= 5) {
    out.push({
      key: "client_silence",
      label: `${item.days_in_stage} dni bez odpowiedzi`,
      tone: "wait",
    });
  }
  // 0372: follow-up z kandydatem, gdy klient milczy — kto dzwoni (jeden
  // telefon na OSOBĘ, także gdy jest w kilku procesach). Tylko termin do
  // jutra: plakietka „za 9 dni” byłaby szumem na każdej karcie.
  if (
    (column === "cv_sent" || column === "client_interview") &&
    item.followup &&
    item.followup.state !== "scheduled"
  ) {
    const f = item.followup;
    out.push({
      key: "followup",
      label: cardBadgeLabel(f, ctx.viewerId),
      tone: f.state === "overdue" ? "urgent" : f.state === "today" ? "wait" : "neutral",
      title:
        f.process_count > 1
          ? `Kandydat czeka na klienta w ${f.process_count} procesach — dzwoni jedna osoba i mówi o wszystkich.`
          : "Klient milczy od 14 dni — telefon do kandydata, że dalej jest w procesie.",
    });
  }
  // Odznaka rozmowy stoi w KAŻDEJ kolumnie: do 24.09.2026 tylko w „Rozmowie
  // u klienta”, więc osoba przesunięta dalej (np. na „Umowę”) z zaległym
  // telefonem po rozmowie wyglądała na załatwioną.
  if (item.interview_badge) {
    const { kind, tone } = item.interview_badge;
    const title = PREP_BADGE_TITLE[kind];
    out.push({
      key: "interview",
      label: item.interview_badge.label,
      tone:
        tone === "urgent" ? "urgent" : tone === "ok" ? "ok" : tone === "wait" ? "wait" : "info",
      ...(title ? { title } : {}),
    });
  }
  // 04.10.2026: stan umowy z Generatora w każdej kolumnie — co trzecia umowa
  // powstaje jeszcze w „Rozmowie u klienta”.
  const agreement = agreementBadge(item.agreement, ctx.now);
  if (agreement) {
    out.push({
      key: "agreement",
      label: agreement.label,
      tone: agreement.tone === "success" ? "ok" : agreement.tone === "warning" ? "wait" : "info",
      title: agreement.title,
    });
  }
  if (column === "hired" && item.order_status) {
    out.push(
      item.order_status === "missing"
        ? {
            key: "order",
            label: "Brak zamówienia",
            tone: "urgent",
            title: "Umowa podpisana, ale zamówienia od klienta jeszcze nie ma — Delivery i Finanse dostały powiadomienie.",
          }
        : { key: "order", label: "Zamówienie ✓", tone: "ok" },
    );
  }
  return out;
}

/**
 * PR 4 ścieżki kandydata (04.10.2026): źródło, blokada 12 h i stan karty
 * rekomendacji to ikony z krótkim dopiskiem — pełna treść w podpowiedzi
 * i w panelu osoby. Karta ma mówić przede wszystkim, czyj jest ruch.
 * `null` = plakietka zostaje pełnym napisem.
 */
export interface CompactCardBadge {
  /** Krótki dopisek obok ikony (`null` = sama ikona). */
  short: string | null;
  /** Pełna treść dla podpowiedzi i czytników ekranu. */
  full: string;
}

export const COMPACT_BADGE_KEYS: ReadonlySet<string> = new Set([
  "source",
  "claim",
  "recommendation_card",
]);

export function compactCardBadge(badge: CardBadge): CompactCardBadge | null {
  if (!COMPACT_BADGE_KEYS.has(badge.key)) return null;
  const full = badge.title ? `${badge.label} — ${badge.title}` : badge.label;
  if (badge.key === "claim") {
    // „Twój · 11 h” → „11 h” (kolor mówi „mój”); cudza blokada zostaje
    // z imieniem („Anna · 3 h”); „Wolny” → sama ikona.
    if (badge.tone === "lock") return { short: badge.label, full };
    if (badge.tone === "own") return { short: badge.label.split(" · ")[1] ?? null, full };
    return { short: null, full };
  }
  if (badge.key === "recommendation_card") {
    // „2 próby kontaktu” zostaje napisem — to informacja o telefonach, nie o karcie.
    if (/^\d/.test(badge.label)) return null;
    const missing = /brakuje (\d+)/.exec(badge.label);
    if (missing) return { short: `−${missing[1]}`, full };
    return { short: badge.tone === "ok" ? "✓" : null, full };
  }
  return { short: null, full };
}

/** Przycisk na karcie w „Nowych"/„Screeningu": „Biorę" (wolna) / „Przejmij" (cudza, DL). */
export function claimAction(
  item: KanbanItem,
  ctx: CardBadgeContext,
): "take" | "takeover" | null {
  if ((ctx.column !== "new" && ctx.column !== "screening") || !item.can_take) return null;
  const heldByOther =
    item.claim_user_id != null && item.claim_user_id !== ctx.viewerId && Boolean(item.claim_until);
  return heldByOther ? "takeover" : "take";
}

// ── Rekrutacja v5: chip QC, strzałka „→" i „kto ma ruch" na karcie ─────────

export type QcChipTone = "ok" | "urgent" | "wait" | "neutral";

export interface QcChip {
  label: string;
  tone: QcChipTone;
  title: string;
}

/** Chip QC na karcie w kolumnie „QC CV" (`item.qc` z tablicy). */
export function qcChip(item: KanbanItem): QcChip {
  const qc = item.qc ?? null;
  if (!qc || qc.status === "unchecked") {
    return {
      label: "QC nie sprawdzone",
      tone: "neutral",
      title: "Nikt jeszcze nie uruchomił kontroli CV — kliknij, żeby sprawdzić.",
    };
  }
  if (qc.status === "passed") {
    return { label: "QC ✓", tone: "ok", title: "CV przeszło kontrolę przed wysłaniem." };
  }
  if (qc.status === "overridden") {
    return {
      label: "QC przepuszczone",
      tone: "wait",
      title: "Delivery Lead albo admin przepuścił CV mimo uwag QC (z powodem).",
    };
  }
  const n = qc.blocking_failed;
  return {
    label: `QC: ${n} do poprawy`,
    tone: "urgent",
    title: "CV ma braki, które blokują wysłanie — kliknij, żeby zobaczyć poprawki.",
  };
}

/**
 * Znany z karty brak przed przejściem do NASTĘPNEJ kolumny — strzałka jest
 * wtedy szara (ale klikalna: okno „Przesuń dalej" mówi, co zrobić). `null` =
 * karta nie zna braku; pełną listę liczy serwer w oknie.
 */
export function knownForwardGap(
  item: KanbanItem,
  from: BoardColumnKey | null,
): string | null {
  if (from === "screening" && item.screening_done === false) {
    return item.screening_requirement === "why_candidate"
      ? "Brak „Dlaczego ten kandydat”"
      : "Brak arkusza screeningu";
  }
  if (from === "cv_qc" && item.qc?.status === "failed") {
    return `QC: ${item.qc.blocking_failed} do poprawy`;
  }
  return null;
}

export interface CardNextStep {
  /** „Twój ruch", imię rekrutera, „DL", „Klient"… — kto ma ruch. */
  who: string;
  /** Ruch należy do patrzącego (podświetlenie tokenem primary). */
  mine: boolean;
  label: string;
}

/** Plakietka ruchu patrzącego (24.09.2026: „Ty" czytało się jak etykieta osoby). */
export const MY_MOVE_LABEL = "Twój ruch";

const ROLE_WHO: Record<string, string> = {
  client: "Klient",
  candidate: "Kandydat",
  delivery: "Delivery",
};

function firstNameOrNull(full: string | null | undefined): string | null {
  return cardShortName(full);
}

/**
 * Krótka nazwa osoby na karcie: pierwsze słowo, bez dwukropka na końcu.
 * Konta integracji nazywają się „Integracje: JJIT” — karta pokazywała
 * „Integracje:” w dwóch wierszach (04.10.2026).
 */
export function cardShortName(full: string | null | undefined): string | null {
  const first = full?.trim().split(/\s+/)[0]?.replace(/:+$/, "");
  return first ? first : null;
}

/**
 * Krótsze nazwy kroków na KARCIE Tablicy (04.10.2026): kolumna ma ok. 160 px
 * na tekst, a „Przygotuj CV do QC” obok „Twój ruch”, dni i strzałki łamało
 * się na „Przygo / CV d…”. Pełna nazwa zostaje w `title` i dla czytnika
 * ekranu; reguła „kto ma ruch” (`pipeline-next-action.ts` i lustro
 * w backendzie) się nie zmienia.
 */
const SHORT_STEP_LABEL: Record<string, string> = {
  "Przygotuj CV do QC": "CV do QC",
  "Umów interview / feedback klienta": "Umów rozmowę",
  "Przegląd CV i wysłanie do klienta": "Przegląd i wysyłka",
  "Uzupełnij arkusz screeningu": "Arkusz screeningu",
  // „Dlaczego ten kandydat” nie mieści się w wierszu karty przy 1280 px
  // (ucinało do „Dlacze… ten…”) — pole stoi w sekcji „Ocena” formularza.
  [WHY_CANDIDATE_LABEL]: "Wpisz ocenę",
  "Zweryfikuj i przenieś dalej": "Zweryfikuj",
  "Reakcja kandydata na ofertę": "Reakcja na ofertę",
  // Cykl rozmowy u klienta (05.10.2026).
  "Wybierz termin rozmowy": "Wybierz termin",
  "Potwierdź termin u klienta": "Potwierdź termin",
  "Prep z kandydatem przed rozmową": "Prep z kandydatem",
  "Telefon po rozmowie i debrief": "Telefon i debrief",
  "Czekamy na decyzję klienta": "Decyzja klienta",
};

/** „Rozmowa 08.10 — prep z kandydatem” → „Prep · rozmowa 08.10”. */
const PREP_BEFORE_INTERVIEW = /^Rozmowa (\d{2}\.\d{2}) — prep z kandydatem$/;

export function shortStepLabel(label: string): string {
  const prep = PREP_BEFORE_INTERVIEW.exec(label);
  if (prep) return `Prep · rozmowa ${prep[1]}`;
  return SHORT_STEP_LABEL[label] ?? label;
}

/**
 * Ruch po naszej stronie (rekruter / przegląd): czyj? Blokada „Biorę" w Nowych
 * wygrywa z rekruterem karty; bez obu albo gdy to patrzący — „Twój ruch".
 * Bez `viewerId` (harness, starszy kontekst) zostaje „Twój ruch", jak dawne „Ty".
 */
function recruiterSideWho(
  item: KanbanItem,
  owner: string,
  viewerId: number | null | undefined,
): { who: string; mine: boolean } {
  const claimActive = owner === "review" && item.claim_user_id != null;
  const personId = claimActive ? item.claim_user_id : (item.recruiter_id ?? null);
  const personName = claimActive ? item.claim_user_name : item.recruiter_name;
  if (personId == null || viewerId == null || personId === viewerId) {
    return { who: MY_MOVE_LABEL, mine: true };
  }
  const name = firstNameOrNull(personName);
  return name ? { who: name, mine: false } : { who: MY_MOVE_LABEL, mine: true };
}

/**
 * Dół karty: kto ma ruch i co zrobić. Opiera się na `nextActionFor` (lustro
 * backendu), a w kolumnie „QC CV" — której tamta reguła nie zna w szczegółach
 * (wynik QC, kolejka Cpro) — mówi, czy ruch jest po stronie rekrutera
 * (poprawki), Delivery Leada (przegląd i wysłanie poza Nordeą) czy osoby od Cpro.
 */
export function cardNextStep(
  action: { label: string; owner: string; kind: string },
  item: KanbanItem,
  ctx: {
    column: BoardColumnKey | null;
    cproEnabled: boolean;
    stageBadge?: string | null;
    /** Patrzący — „Twój ruch" tylko wtedy, gdy karta jest jego (albo niczyja). */
    viewerId?: number | null;
    /** Przegląd przed wysłaniem do klienta należy do patrzącego (serwer). */
    viewerOwnsDlReview?: boolean;
  },
): CardNextStep | null {
  const recruiter = () => recruiterSideWho(item, "recruiter", ctx.viewerId);
  if (ctx.column === "cv_qc") {
    if (item.qc?.status === "failed") {
      return { ...recruiter(), label: "Popraw CV wg QC" };
    }
    if (ctx.stageBadge !== "cpro" && item.qc?.status !== "passed" && item.qc?.status !== "overridden") {
      return { ...recruiter(), label: "Sprawdź QC CV" };
    }
    if (ctx.stageBadge === "cpro") {
      return { who: "Osoba od Cpro", mine: false, label: "Wrzuć CV do Cpro" };
    }
    // U Nordei Delivery Lead akceptuje osobę do kolejki Cpro (13.10.2026).
    const label = ctx.cproEnabled
      ? "Przegląd CV i akceptacja do Cpro"
      : "Przegląd CV i wysłanie do klienta";
    // Delivery Lead tej rekrutacji widzi swój ruch jak rekruter swój; pozostali
    // (także DL innej rekrutacji i admin) — „DL”.
    if (ctx.viewerOwnsDlReview && isReadyForDlSend(item, ctx.column, false)) {
      return { who: MY_MOVE_LABEL, mine: true, label };
    }
    return { who: "DL", mine: false, label };
  }
  if (action.kind === "none" || action.owner === "none" || !action.label) return null;
  const role = ROLE_WHO[action.owner];
  if (role) return { who: role, mine: false, label: action.label };
  return { ...recruiterSideWho(item, action.owner, ctx.viewerId), label: action.label };
}
